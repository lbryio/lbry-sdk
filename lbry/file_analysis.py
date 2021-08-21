import asyncio
import json
import logging
import os
import pathlib
import platform
import re
import shlex
import shutil
import subprocess
from math import ceil

import lbry.utils
from lbry.conf import TranscodeConfig

log = logging.getLogger(__name__)


class VideoFileAnalyzer:

    def _replace_or_pop_env(self, variable):
        if variable + '_ORIG' in self._env_copy:
            self._env_copy[variable] = self._env_copy[variable + '_ORIG']
        else:
            self._env_copy.pop(variable, None)

    def __init__(self, conf: TranscodeConfig):
        self._conf = conf
        self._available_encoders = ""
        self._ffmpeg_installed = None
        self._which_ffmpeg = None
        self._which_ffprobe = None
        self._env_copy = dict(os.environ)
        self._checked_ffmpeg = False
        if lbry.utils.is_running_from_bundle():
            # handle the situation where PyInstaller overrides our runtime environment:
            self._replace_or_pop_env('LD_LIBRARY_PATH')

    @staticmethod
    def _execute(command, environment):
        # log.debug("Executing: %s", command)
        try:
            with subprocess.Popen(
                    shlex.split(command) if platform.system() != 'Windows' else command,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment
            ) as process:
                (stdout, stderr) = process.communicate()  # blocks until the process exits
                return stdout.decode(errors='replace') + stderr.decode(errors='replace'), process.returncode
        except subprocess.SubprocessError as e:
            return str(e), -1

    # This create_subprocess_exec call is broken in Windows Python 3.7, but it's prettier than what's here.
    # The recommended fix is switching to ProactorEventLoop, but that breaks UDP in Linux Python 3.7.
    # We work around that issue here by using run_in_executor. Check it again in Python 3.8.
    async def _execute_ffmpeg(self, arguments):
        arguments = self._which_ffmpeg + " " + arguments
        return await asyncio.get_event_loop().run_in_executor(None, self._execute, arguments, self._env_copy)

    async def _execute_ffprobe(self, arguments):
        arguments = self._which_ffprobe + " " + arguments
        return await asyncio.get_event_loop().run_in_executor(None, self._execute, arguments, self._env_copy)

    async def _verify_executables(self):
        try:
            await self._execute_ffprobe("-version")
            version, code = await self._execute_ffmpeg("-version")
        except Exception as e:
            code = -1
            version = str(e)
        if code != 0 or not version.startswith("ffmpeg"):
            log.warning("Unable to run ffmpeg, but it was requested. Code: %d; Message: %s", code, version)
            raise FileNotFoundError("Unable to locate or run ffmpeg or ffprobe. Please install FFmpeg "
                                    "and ensure that it is callable via PATH or conf.ffmpeg_path")
        log.debug("Using %s at %s", version.splitlines()[0].split(" Copyright")[0], self._which_ffmpeg)
        return version

    @staticmethod
    def _which_ffmpeg_and_ffmprobe(path):
        return shutil.which("ffmpeg", path=path), shutil.which("ffprobe", path=path)

    async def _verify_ffmpeg_installed(self):
        if self._ffmpeg_installed:
            return
        self._ffmpeg_installed = False
        path = self._conf.ffmpeg_path
        if hasattr(self._conf, "data_dir"):
            path += os.path.pathsep + os.path.join(getattr(self._conf, "data_dir"), "ffmpeg", "bin")
        path += os.path.pathsep + self._env_copy.get("PATH", "")
        self._which_ffmpeg, self._which_ffprobe = await asyncio.get_running_loop().run_in_executor(
            None, self._which_ffmpeg_and_ffmprobe, path
        )
        if not self._which_ffmpeg:
            log.warning("Unable to locate ffmpeg executable. Path: %s", path)
            raise FileNotFoundError(f"Unable to locate ffmpeg executable. Path: {path}")
        if not self._which_ffprobe:
            log.warning("Unable to locate ffprobe executable. Path: %s", path)
            raise FileNotFoundError(f"Unable to locate ffprobe executable. Path: {path}")
        if os.path.dirname(self._which_ffmpeg) != os.path.dirname(self._which_ffprobe):
            log.warning("ffmpeg and ffprobe are in different folders!")

        await self._verify_executables()
        self._ffmpeg_installed = True

    async def status(self, reset=False, recheck=False):
        if reset:
            self._available_encoders = ""
            self._ffmpeg_installed = None
        if self._checked_ffmpeg and not recheck:
            pass
        elif self._ffmpeg_installed is None:
            try:
                await self._verify_ffmpeg_installed()
            except FileNotFoundError:
                pass
            self._checked_ffmpeg = True
        return {
            "available": self._ffmpeg_installed,
            "which": self._which_ffmpeg,
            "analyze_audio_volume": int(self._conf.volume_analysis_time) > 0
        }

    @staticmethod
    def _verify_container(scan_data: json):
        container = scan_data["format"]["format_name"]
        log.debug("   Detected container is %s", container)
        splits = container.split(",")
        if not {"webm", "mp4", "3gp", "ogg"}.intersection(splits):
            return "Container format is not in the approved list of WebM, MP4. " \
                   f"Actual: {container} [{scan_data['format']['format_long_name']}]"

        if "matroska" in splits:
            for stream in scan_data["streams"]:
                if stream["codec_type"] == "video":
                    codec = stream["codec_name"]
                    if not {"vp8", "vp9", "av1"}.intersection(codec.split(",")):
                        return "WebM format requires VP8/9 or AV1 video. " \
                               f"Actual: {codec} [{stream['codec_long_name']}]"
                elif stream["codec_type"] == "audio":
                    codec = stream["codec_name"]
                    if not {"vorbis", "opus"}.intersection(codec.split(",")):
                        return "WebM format requires Vorbis or Opus audio. " \
                               f"Actual: {codec} [{stream['codec_long_name']}]"

        return ""

    @staticmethod
    def _verify_video_encoding(scan_data: json):
        for stream in scan_data["streams"]:
            if stream["codec_type"] != "video":
                continue
            codec = stream["codec_name"]
            log.debug("   Detected video codec is %s, format is %s", codec, stream["pix_fmt"])
            if not {"h264", "vp8", "vp9", "av1", "theora"}.intersection(codec.split(",")):
                return "Video codec is not in the approved list of H264, VP8, VP9, AV1, Theora. " \
                       f"Actual: {codec} [{stream['codec_long_name']}]"

            if "h264" in codec.split(",") and stream["pix_fmt"] != "yuv420p":
                return "Video codec is H264, but its pixel format does not match the approved yuv420p. " \
                       f"Actual: {stream['pix_fmt']}"

        return ""

    def _verify_bitrate(self, scan_data: json, file_path):
        bit_rate_max = float(self._conf.video_bitrate_maximum)
        if bit_rate_max <= 0:
            return ""

        if "bit_rate" in scan_data["format"]:
            bit_rate = float(scan_data["format"]["bit_rate"])
        else:
            bit_rate = os.stat(file_path).st_size / float(scan_data["format"]["duration"])
        log.debug("   Detected bitrate is %s Mbps. Allowed max: %s Mbps",
                  str(bit_rate / 1000000.0), str(bit_rate_max / 1000000.0))

        if bit_rate > bit_rate_max:
            return "The bit rate is above the configured maximum. Actual: " \
                   f"{bit_rate / 1000000.0} Mbps; Allowed max: {bit_rate_max / 1000000.0} Mbps"

        return ""

    async def _verify_fast_start(self, scan_data: json, video_file):
        container = scan_data["format"]["format_name"]
        if {"webm", "ogg"}.intersection(container.split(",")):
            return ""

        result, _ = await self._execute_ffprobe(f'-v debug "{video_file}"')
        match = re.search(r"Before avformat_find_stream_info.+?\s+seeks:(\d+)\s+", result)
        if match and int(match.group(1)) != 0:
            return "Video stream descriptors are not at the start of the file (the faststart flag was not used)."
        return ""

    @staticmethod
    def _verify_audio_encoding(scan_data: json):
        for stream in scan_data["streams"]:
            if stream["codec_type"] != "audio":
                continue
            codec = stream["codec_name"]
            log.debug("   Detected audio codec is %s", codec)
            if not {"aac", "mp3", "flac", "vorbis", "opus"}.intersection(codec.split(",")):
                return "Audio codec is not in the approved list of AAC, FLAC, MP3, Vorbis, and Opus. " \
                       f"Actual: {codec} [{stream['codec_long_name']}]"
            if int(stream['sample_rate']) > 48000:
                return "Sample rate out of range"

        return ""

    async def _verify_audio_volume(self, seconds, video_file):
        try:
            validate_volume = int(seconds) > 0
        except ValueError:
            validate_volume = False

        if not validate_volume:
            return ""

        result, _ = await self._execute_ffmpeg(f'-i "{video_file}" -t {seconds} '
                                               f'-af volumedetect -vn -sn -dn -f null "{os.devnull}"')
        try:
            mean_volume = float(re.search(r"mean_volume:\s+([-+]?\d*\.\d+|\d+)", result).group(1))
            max_volume = float(re.search(r"max_volume:\s+([-+]?\d*\.\d+|\d+)", result).group(1))
        except Exception as e:
            log.debug("   Failure in volume analysis. Message: %s", str(e))
            return ""

        if max_volume < -5.0 and mean_volume < -22.0:
            return "Audio is at least five dB lower than prime. " \
                   f"Actual max: {max_volume}, mean: {mean_volume}"

        log.debug("   Detected audio volume has mean, max of %f, %f dB", mean_volume, max_volume)

        return ""

    @staticmethod
    def _compute_crf(scan_data):
        height = 240.0
        for stream in scan_data["streams"]:
            if stream["codec_type"] == "video":
                height = max(height, float(stream["height"]))

        # https://developers.google.com/media/vp9/settings/vod/
        return int(-0.011 * height + 40)

    def _get_video_scaler(self):
        return self._conf.video_scaler

    async def _get_video_encoder(self, scan_data):
        # use what the user said if it's there:
        # if it's not there, use h264 if we can because it's way faster than the others
        # if we don't have h264 use vp9; it's fairly compatible even though it's slow

        if not self._available_encoders:
            self._available_encoders, _ = await self._execute_ffmpeg("-encoders -v quiet")

        encoder = self._conf.video_encoder.split(" ", 1)[0]
        if re.search(fr"^\s*V..... {encoder} ", self._available_encoders, re.MULTILINE):
            return self._conf.video_encoder

        if re.search(r"^\s*V..... libx264 ", self._available_encoders, re.MULTILINE):
            if encoder:
                log.warning("   Using libx264 since the requested encoder was unavailable. Requested: %s", encoder)
            return 'libx264 -crf 19 -vf "format=yuv420p"'

        if not encoder:
            encoder = "libx264"

        if re.search(r"^\s*V..... libvpx-vp9 ", self._available_encoders, re.MULTILINE):
            log.warning("   Using libvpx-vp9 since the requested encoder was unavailable. Requested: %s", encoder)
            crf = self._compute_crf(scan_data)
            return f"libvpx-vp9 -crf {crf} -b:v 0"

        if re.search(r"^\s*V..... libtheora", self._available_encoders, re.MULTILINE):
            log.warning("   Using libtheora since the requested encoder was unavailable. Requested: %s", encoder)
            return "libtheora -q:v 7"

        raise Exception(f"The video encoder is not available. Requested: {encoder}")

    async def _get_audio_encoder(self, extension):
        # if the video encoding is theora or av1/vp8/vp9 use opus (or fallback to vorbis)
        # or we don't have a video encoding but we have an ogg or webm container use opus
        # if we need to use opus/vorbis see if the conf file has it else use our own params
        # else use the user-set value if it exists
        # else use aac

        wants_opus = extension != "mp4"
        if not self._available_encoders:
            self._available_encoders, _ = await self._execute_ffmpeg("-encoders -v quiet")

        encoder = self._conf.audio_encoder.split(" ", 1)[0]
        if wants_opus and 'opus' in encoder:
            return self._conf.audio_encoder

        if wants_opus and re.search(r"^\s*A..... libopus ", self._available_encoders, re.MULTILINE):
            return "libopus -b:a 160k"

        if wants_opus and 'vorbis' in encoder:
            return self._conf.audio_encoder

        if wants_opus and re.search(r"^\s*A..... libvorbis ", self._available_encoders, re.MULTILINE):
            return "libvorbis -q:a 6"

        if re.search(fr"^\s*A..... {encoder} ", self._available_encoders, re.MULTILINE):
            return self._conf.audio_encoder

        if re.search(r"^\s*A..... aac ", self._available_encoders, re.MULTILINE):
            return "aac -b:a 192k"

        raise Exception(f"The audio encoder is not available. Requested: {encoder or 'aac'}")

    @staticmethod
    def _get_best_container_extension(scan_data, video_encoder):
        # the container is chosen by the video format
        # if we are theora-encoded, we want ogg
        # if we are vp8/vp9/av1 we want webm
        # use mp4 for anything else

        if video_encoder:  # not re-encoding video
            if "theora" in video_encoder:
                return "ogv"
            if re.search(r"vp[89x]|av1", video_encoder.split(" ", 1)[0]):
                return "webm"
            return "mp4"

        for stream in scan_data["streams"]:
            if stream["codec_type"] != "video":
                continue
            codec = stream["codec_name"].split(",")
            if "theora" in codec:
                return "ogv"
            if {"vp8", "vp9", "av1"}.intersection(codec):
                return "webm"

        return "mp4"

    async def _get_scan_data(self, validate, file_path):
        arguments = f'-v quiet -print_format json -show_format -show_streams "{file_path}"'
        result, _ = await self._execute_ffprobe(arguments)
        try:
            scan_data = json.loads(result)
        except Exception as e:
            log.debug("Failure in JSON parsing ffprobe results. Message: %s", str(e))
            raise ValueError(f'Absent or unreadable video file: {file_path}')

        if "format" not in scan_data or "duration" not in scan_data["format"]:
            log.debug("Format data is missing from ffprobe results for: %s", file_path)
            raise ValueError(f'Media file does not appear to contain video content: {file_path}')

        if float(scan_data["format"]["duration"]) < 0.1:
            log.debug("Media file appears to be an image: %s", file_path)
            raise ValueError(f'Assuming image file at: {file_path}')

        return scan_data

    @staticmethod
    def _build_spec(scan_data):
        assert scan_data

        duration = ceil(float(scan_data["format"]["duration"]))  # existence verified when scan_data made
        width = -1
        height = -1
        for stream in scan_data["streams"]:
            if stream["codec_type"] != "video":
                continue
            width = max(width, int(stream["width"]))
            height = max(height, int(stream["height"]))

        log.debug("   Detected duration: %d sec. with resolution: %d x %d", duration, width, height)

        spec = {"duration": duration}
        if height >= 0:
            spec["height"] = height
        if width >= 0:
            spec["width"] = width
        return spec

    async def verify_or_repair(self, validate, repair, file_path, ignore_non_video=False):
        if not validate and not repair:
            return file_path, {}

        if ignore_non_video and not file_path:
            return file_path, {}

        await self._verify_ffmpeg_installed()
        try:
            scan_data = await self._get_scan_data(validate, file_path)
        except ValueError:
            if ignore_non_video:
                return file_path, {}
            raise

        fast_start_msg = await self._verify_fast_start(scan_data, file_path)
        log.debug("Analyzing %s:", file_path)
        spec = self._build_spec(scan_data)
        log.debug("   Detected faststart is %s", "false" if fast_start_msg else "true")
        container_msg = self._verify_container(scan_data)
        bitrate_msg = self._verify_bitrate(scan_data, file_path)
        video_msg = self._verify_video_encoding(scan_data)
        audio_msg = self._verify_audio_encoding(scan_data)
        volume_msg = await self._verify_audio_volume(self._conf.volume_analysis_time, file_path)
        messages = [container_msg, bitrate_msg, fast_start_msg, video_msg, audio_msg, volume_msg]

        if not any(messages):
            return file_path, spec

        if not repair:
            errors = ["Streamability verification failed:"]
            errors.extend(filter(None, messages))
            raise Exception("\n   ".join(errors))

        # the plan for transcoding:
        # we have to re-encode the video if it is in a nonstandard format
        # we also re-encode if we are h264 but not yuv420p (both errors caught in video_msg)
        # we also re-encode if our bitrate or sample rate is too high

        try:
            transcode_command = [f'-i "{file_path}" -y -c:s copy -c:d copy -c:v']

            video_encoder = ""
            if video_msg or bitrate_msg:
                video_encoder = await self._get_video_encoder(scan_data)
                transcode_command.append(video_encoder)
                # could do the scaling only if bitrate_msg, but if we're going to the effort to re-encode anyway...
                transcode_command.append(self._get_video_scaler())
            else:
                transcode_command.append("copy")

            transcode_command.append("-movflags +faststart -c:a")
            extension = self._get_best_container_extension(scan_data, video_encoder)

            if audio_msg or volume_msg:
                audio_encoder = await self._get_audio_encoder(extension)
                transcode_command.append(audio_encoder)
                if volume_msg and self._conf.volume_filter:
                    transcode_command.append(self._conf.volume_filter)
                if audio_msg == "Sample rate out of range":
                    transcode_command.append(" -ar 48000 ")
            else:
                transcode_command.append("copy")

            # TODO: put it in a temp folder and delete it after we upload?
            path = pathlib.Path(file_path)
            output = path.parent / f"{path.stem}_fixed.{extension}"
            transcode_command.append(f'"{output}"')

            ffmpeg_command = " ".join(transcode_command)
            log.info("Proceeding on transcode via: ffmpeg %s", ffmpeg_command)
            result, code = await self._execute_ffmpeg(ffmpeg_command)
            if code != 0:
                raise Exception(f"Failure to complete the transcode command. Output: {result}")
        except Exception as e:
            if validate:
                raise
            log.info("Unable to transcode %s . Message: %s", file_path, str(e))
            # TODO: delete partial output file here if it exists?
            return file_path, spec

        return str(output), spec
