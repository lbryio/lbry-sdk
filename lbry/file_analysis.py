import asyncio
import json
import logging
import os
import pathlib
import re
import shlex
import shutil

from lbry.conf import TranscodeConfig

log = logging.getLogger(__name__)


class VideoFileAnalyzer:
    @staticmethod
    def _matches(needles: list, haystack: list):
        for needle in needles:
            if needle in haystack:
                return True
        return False

    async def _execute(self, command, arguments):
        process = await asyncio.create_subprocess_exec(self._conf.ffmpeg_folder + command, *shlex.split(arguments),
                                                       stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()  # returns when the streams are closed
        return stdout.decode() + stderr.decode(), process.returncode

    async def _verify_ffmpeg_installed(self):
        if self._ffmpeg_installed:
            return
        version, code = await self._execute("ffprobe", "-version")
        if code != 0 or not version.startswith("ffprobe"):
            raise Exception("Unable to locate ffprobe. Please install FFmpeg and ensure that it is callable via PATH.")
        version, code = await self._execute("ffmpeg", "-version")
        if code != 0 or not version.startswith("ffmpeg"):
            raise Exception("Unable to locate ffmpeg. Please install FFmpeg and ensure that it is callable via PATH.")
        log.debug("Using %s at %s", version.splitlines()[0].split(" Copyright")[0],
                  shutil.which(self._conf.ffmpeg_folder + "ffmpeg"))
        self._ffmpeg_installed = True

    def __init__(self, conf: TranscodeConfig):
        self._conf = conf
        self._available_encoders = ""
        self._ffmpeg_installed = False

    def _verify_container(self, scan_data: json):
        container = scan_data["format"]["format_name"]
        log.debug("   Detected container %s", container)
        if not self._matches(container.split(","), ["webm", "mp4", "3gp", "ogg"]):
            return "Container format is not in the approved list of WebM, MP4. Actual: " \
                   + container + " [" + scan_data["format"]["format_long_name"] + "]"
        return ""

    def _verify_video_encoding(self, scan_data: json):
        for stream in scan_data["streams"]:
            if stream["codec_type"] != "video":
                continue
            codec = stream["codec_name"]
            log.debug("   Detected video codec %s encoding %s", codec, stream["pix_fmt"])
            if not self._matches(codec.split(","), ["h264", "vp8", "vp9", "av1", "theora"]):
                return "Video codec is not in the approved list of H264, VP8, VP9, AV1, Theora. Actual: " \
                       + codec + " [" + stream["codec_long_name"] + "]"

            if self._matches(codec.split(","), ["h264"]) and stream["pix_fmt"] != "yuv420p":
                return "Video codec is H264, but its pixel format does not match the approved yuv420p. Actual: " \
                       + stream["pix_fmt"]

        return ""

    @staticmethod
    def _verify_bitrate(scan_data: json):
        if "bit_rate" not in scan_data["format"]:
            return ""

        bit_rate = float(scan_data["format"]["bit_rate"])
        log.debug("   Detected bitrate %s Mbps", str(bit_rate / 1000000.0))
        pixels = -1.0
        for stream in scan_data["streams"]:
            if stream["codec_type"] == "video":
                pieces = stream["r_frame_rate"].split('/', 1)
                frame_rate = float(pieces[0]) if len(pieces) == 1 \
                    else float(pieces[0]) / float(pieces[1])
                pixels = max(pixels, float(stream["height"]) * float(stream["width"]) * frame_rate)

        if pixels > 0.0 and pixels / bit_rate < 3.0:
            return "Bits per second is excessive for this data; this may impact web streaming performance. Actual: " \
                   + str(bit_rate / 1000000.0) + "Mbps"

        return ""

    async def _verify_faststart(self, scan_data: json, video_file):
        container = scan_data["format"]["format_name"]
        if self._matches(container.split(","), ["webm", "ogg"]):
            return ""

        result, _ = await self._execute("ffprobe", "-v debug \"" + video_file + "\"")
        iterator = re.finditer(r"\s+seeks:(\d+)\s+", result)
        for match in iterator:
            if int(match.group(1)) != 0:
                return "Video stream descriptors are not at the start of the file (the faststart flag was not used)."
        return ""

    def _verify_audio_encoding(self, scan_data: json):
        for stream in scan_data["streams"]:
            if stream["codec_type"] != "audio":
                continue
            codec = stream["codec_name"]
            log.debug("   Detected audio codec %s", codec)
            if not self._matches(codec.split(","), ["aac", "mp3", "flac", "vorbis", "opus"]):
                return "Audio codec is not in the approved list of AAC, FLAC, MP3, Vorbis, and Opus. Actual: " \
                       + codec + " [" + stream["codec_long_name"] + "]"

        return ""

    async def _verify_audio_volume(self, scan_data: json, seconds, video_file):
        try:
            validate_volume = int(seconds) > 0
        except ValueError:
            validate_volume = 0

        if not validate_volume:
            return ""

        result, _ = await self._execute("ffmpeg", f"-i \"{video_file}\" -t {seconds}"
                                        + f" -af volumedetect -vn -sn -dn -f null \"{os.devnull}\"")
        try:
            mean_volume = float(re.search(r"mean_volume:\s+([-+]?\d*\.\d+|\d+)", result).group(1))
            max_volume = float(re.search(r"max_volume:\s+([-+]?\d*\.\d+|\d+)", result).group(1))
        except Exception as e:
            log.debug("   Failure in volume analysis. Message: %s", str(e))
            return ""

        if max_volume < -5.0 and mean_volume < -22.0:
            return "Audio is at least five dB lower than prime. Actual max: " + str(max_volume) \
                   + ", mean: " + str(mean_volume)

        log.debug("   Detected audio volume mean, max as %f dB, %f dB", mean_volume, max_volume)

        return ""

    @staticmethod
    def _compute_crf(scan_data):
        height = 240.0
        for stream in scan_data["streams"]:
            if stream["codec_type"] == "video":
                height = max(height, float(stream["height"]))

        # https://developers.google.com/media/vp9/settings/vod/
        return int(-0.011 * height + 40)

    async def _get_video_encoder(self, scan_data):
        # use what the user said if it's there:
        # if it's not there, use h264 if we can because it's way faster than the others
        # if we don't have h264 use vp9; it's fairly compatible even though it's slow

        if not self._available_encoders:
            self._available_encoders, _ = await self._execute("ffmpeg", "-encoders -v quiet")

        encoder = self._conf.video_encoder.split(" ", 1)[0]
        if re.search(r"^\s*V..... " + encoder + r" ", self._available_encoders, re.MULTILINE):
            return self._conf.video_encoder

        if re.search(r"^\s*V..... libx264 ", self._available_encoders, re.MULTILINE):
            if encoder:
                log.warning("   Using libx264 since the requested encoder was unavailable. Requested: %s", encoder)
            return "libx264 -crf 19 -vf \"format=yuv420p\""

        if not encoder:
            encoder = "libx264"

        if re.search(r"^\s*V..... libvpx-vp9 ", self._available_encoders, re.MULTILINE):
            log.warning("   Using libvpx-vp9 since the requested encoder was unavailable. Requested: %s", encoder)
            crf = self._compute_crf(scan_data)
            return "libvpx-vp9 -crf " + str(crf) + " b:v 0"

        if re.search(r"^\s*V..... libtheora", self._available_encoders, re.MULTILINE):
            log.warning("   Using libtheora since the requested encoder was unavailable. Requested: %s", encoder)
            return "libtheora -q:v 7"

        raise Exception("The video encoder is not available. Requested: " + encoder)

    async def _get_audio_encoder(self, scan_data, video_encoder):
        # if the video encoding is theora or av1/vp8/vp9 use vorbis
        # or we don't have a video encoding but we have an ogg or webm container use vorbis
        # if we need to use vorbis see if the conf file has one else use our own params
        # else use the user-set value if it exists
        # else use aac

        if video_encoder:
            wants_opus = any(encoder in video_encoder for encoder in ["av1", "vp8", "vp9", "theora"])
        else:  # we're not re-encoding video
            container = scan_data["format"]["format_name"]
            wants_opus = self._matches(container.split(","), ["webm"])

        if not self._available_encoders:
            self._available_encoders, _ = await self._execute("ffmpeg", "-encoders -v quiet")

        if wants_opus and re.search(r"^\s*A..... libopus ", self._available_encoders, re.MULTILINE):
            return "libopus -b:a 160k"

        if wants_opus and re.search(r"^\s*A..... libvorbis ", self._available_encoders, re.MULTILINE):
            return "libvorbis -q:a 6"

        encoder = self._conf.audio_encoder.split(" ", 1)[0]
        if re.search(r"^\s*A..... " + encoder + r" ", self._available_encoders, re.MULTILINE):
            return self._conf.audio_encoder

        if re.search(r"^\s*A..... aac ", self._available_encoders, re.MULTILINE):
            return "aac -b:a 192k"

        if not encoder:
            encoder = "aac"
        raise Exception("The audio encoder is not available. Requested: " + encoder)

    async def _get_volume_filter(self, scan_data):
        return self._conf.volume_filter if self._conf.volume_filter else "-af loudnorm"

    def _get_best_container_extension(self, scan_data, video_encoder):
        # the container is chosen by the video format
        # if we are theora-encoded, we want ogg
        # if we are vp8/vp9/av1 we want webm
        # use mp4 for anything else

        if not video_encoder:  # not re-encoding video
            for stream in scan_data["streams"]:
                if stream["codec_type"] != "video":
                    continue
                codec = stream["codec_name"].split(",")
                if self._matches(codec, ["theora"]):
                    return "ogg"
                if self._matches(codec, ["vp8", "vp9", "av1"]):
                    return "webm"

        if "theora" in video_encoder:
            return "ogg"
        elif re.search("vp[89x]|av1", video_encoder.split(" ", 1)[0]):
            return "webm"
        return "mp4"

    async def verify_or_repair(self, validate, repair, file_path):
        if not validate and not repair:
            return file_path

        await self._verify_ffmpeg_installed()

        result, _ = await self._execute("ffprobe",
                                        f"-v quiet -print_format json -show_format -show_streams \"{file_path}\"")
        try:
            scan_data = json.loads(result)
        except Exception as e:
            log.debug("Failure in JSON parsing ffprobe results. Message: %s", str(e))
            if validate:
                raise Exception('Invalid video file: ' + file_path)
            log.info("Unable to optimize %s . FFmpeg output was unreadable.", file_path)
            return

        if "format" not in scan_data:
            if validate:
                raise Exception('Unexpected video file contents: ' + file_path)
            log.info("Unable to optimize %s . FFmpeg output is missing the format section.", file_path)
            return

        faststart_msg = await self._verify_faststart(scan_data, file_path)
        log.debug("Analyzing %s:", file_path)
        log.debug("   Detected faststart is %s", "false" if faststart_msg else "true")
        container_msg = self._verify_container(scan_data)
        bitrate_msg = self._verify_bitrate(scan_data)
        video_msg = self._verify_video_encoding(scan_data)
        audio_msg = self._verify_audio_encoding(scan_data)
        volume_msg = await self._verify_audio_volume(scan_data, self._conf.volume_analysis_time, file_path)
        messages = [container_msg, bitrate_msg, faststart_msg, video_msg, audio_msg, volume_msg]

        if not any(messages):
            return file_path

        if not repair:
            errors = "Streamability verification failed:\n"
            for message in messages:
                if message:
                    errors += "   " + message + "\n"

            raise Exception(errors)

        # the plan for transcoding:
        # we have to re-encode the video if it is in a nonstandard format
        # we also re-encode if we are h264 but not yuv420p (both errors caught in video_msg)
        # we also re-encode if our bitrate is too high

        try:
            transcode_command = f"-i \"{file_path}\" -y -c:s copy -c:d copy -c:v "

            video_encoder = ""
            if video_msg or bitrate_msg:
                video_encoder = await self._get_video_encoder(scan_data)
                transcode_command += video_encoder + " "
            else:
                transcode_command += "copy "

            transcode_command += "-movflags +faststart -c:a "

            if audio_msg or volume_msg:
                audio_encoder = await self._get_audio_encoder(scan_data, video_encoder)
                transcode_command += audio_encoder + " "
                if volume_msg:
                    volume_filter = await self._get_volume_filter(scan_data)
                    transcode_command += volume_filter + " "
            else:
                transcode_command += "copy "

            path = pathlib.Path(file_path)
            extension = self._get_best_container_extension(scan_data, video_encoder)

            # TODO: put it in a temp folder and delete it after we upload?
            output = path.parent / (path.stem + "_fixed." + extension)
            transcode_command += '"' + str(output) + '"'

            log.info("Proceeding on transcode via: ffmpeg %s", transcode_command)
            result, code = await self._execute("ffmpeg", transcode_command)
            if code != 0:
                raise Exception("Failure to complete the transcode command. Output: " + result)
        except Exception as e:
            if validate:
                raise
            log.info("Unable to transcode %s . Message: %s", file_path, str(e))
            # TODO: delete partial output file here if it exists?
            return file_path

        return output
