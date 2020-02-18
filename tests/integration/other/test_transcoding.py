import logging
import pathlib
import time

from ..blockchain.test_claim_commands import ClaimTestCase
from lbry.conf import TranscodeConfig
from lbry.file_analysis import VideoFileAnalyzer

log = logging.getLogger(__name__)


class MeasureTime:
    def __init__(self, text):
        print(text, end="...", flush=True)

    def __enter__(self):
        self.start = time.perf_counter()

    def __exit__(self, exc_type, exc_val, exc_tb):
        end = time.perf_counter()
        print(f" done in {end - self.start:.6f}s", flush=True)


class TranscodeValidation(ClaimTestCase):

    def make_name(self, name, extension=""):
        path = pathlib.Path(self.video_file_name)
        return path.parent / f"{path.stem}_{name}{extension or path.suffix}"

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.conf = TranscodeConfig()
        self.conf.volume_analysis_time = 0  # disable it as the test file isn't very good here
        self.analyzer = VideoFileAnalyzer(self.conf)
        file_ogg = self.make_name("ogg", ".ogg")
        self.video_file_ogg = str(file_ogg)
        if not file_ogg.exists():
            command = f'-i "{self.video_file_name}" -c:v libtheora -q:v 4 -c:a libvorbis -q:a 4 ' \
                      f'-c:s copy -c:d copy "{file_ogg}"'
            with MeasureTime(f"Creating {file_ogg.name}"):
                output, code = await self.analyzer._execute("ffmpeg", command)
                self.assertEqual(code, 0, output)

        file_webm = self.make_name("webm", ".webm")
        self.video_file_webm = str(file_webm)
        if not file_webm.exists():
            command = f'-i "{self.video_file_name}" -c:v libvpx-vp9 -crf 36 -b:v 0 -cpu-used 2 ' \
                      f'-c:a libopus -b:a 128k -c:s copy -c:d copy "{file_webm}"'
            with MeasureTime(f"Creating {file_webm.name}"):
                output, code = await self.analyzer._execute("ffmpeg", command)
                self.assertEqual(code, 0, output)

    async def test_should_work(self):
        new_file_name = await self.analyzer.verify_or_repair(True, False, self.video_file_name)
        self.assertEqual(self.video_file_name, new_file_name)
        new_file_name = await self.analyzer.verify_or_repair(True, False, self.video_file_ogg)
        self.assertEqual(self.video_file_ogg, new_file_name)
        new_file_name = await self.analyzer.verify_or_repair(True, False, self.video_file_webm)
        self.assertEqual(self.video_file_webm, new_file_name)

    async def test_volume(self):
        self.conf.volume_analysis_time = 200
        with self.assertRaisesRegex(Exception, "lower than prime"):
            await self.analyzer.verify_or_repair(True, False, self.video_file_name)

    async def test_container(self):
        file_name = self.make_name("bad_container", ".avi")
        if not file_name.exists():
            command = f'-i "{self.video_file_name}" -c copy -map 0 "{file_name}"'
            with MeasureTime(f"Creating {file_name.name}"):
                output, code = await self.analyzer._execute("ffmpeg", command)
                self.assertEqual(code, 0, output)

        with self.assertRaisesRegex(Exception, "Container format is not in the approved list"):
            await self.analyzer.verify_or_repair(True, False, file_name)

        fixed_file = await self.analyzer.verify_or_repair(True, True, file_name)
        pathlib.Path(fixed_file).unlink()

    async def test_video_codec(self):
        file_name = self.make_name("bad_video_codec_1")
        if not file_name.exists():
            command = f'-i "{self.video_file_name}" -c copy -map 0 -c:v libx265 -preset superfast "{file_name}"'
            with MeasureTime(f"Creating {file_name.name}"):
                output, code = await self.analyzer._execute("ffmpeg", command)
                self.assertEqual(code, 0, output)

        with self.assertRaisesRegex(Exception, "Video codec is not in the approved list"):
            await self.analyzer.verify_or_repair(True, False, file_name)
        with self.assertRaisesRegex(Exception, "faststart flag was not used"):
            await self.analyzer.verify_or_repair(True, False, file_name)

        fixed_file = await self.analyzer.verify_or_repair(True, True, file_name)
        pathlib.Path(fixed_file).unlink()

    async def test_video_format(self):
        file_name = self.make_name("bad_video_format_1")
        if not file_name.exists():
            command = f'-i "{self.video_file_name}" -c copy -map 0 -c:v libx264 ' \
                      f'-vf format=yuv444p "{file_name}"'
            with MeasureTime(f"Creating {file_name.name}"):
                output, code = await self.analyzer._execute("ffmpeg", command)
                self.assertEqual(code, 0, output)

        with self.assertRaisesRegex(Exception, "pixel format does not match the approved"):
            await self.analyzer.verify_or_repair(True, False, file_name)

        fixed_file = await self.analyzer.verify_or_repair(True, True, file_name)
        pathlib.Path(fixed_file).unlink()

    async def test_audio_codec(self):
        file_name = self.make_name("bad_audio_codec_1", ".mkv")
        if not file_name.exists():
            command = f'-i "{self.video_file_name}" -c copy -map 0 -c:a pcm_s16le "{file_name}"'
            with MeasureTime(f"Creating {file_name.name}"):
                output, code = await self.analyzer._execute("ffmpeg", command)
                self.assertEqual(code, 0, output)

        with self.assertRaisesRegex(Exception, "Audio codec is not in the approved list"):
            await self.analyzer.verify_or_repair(True, False, file_name)

        fixed_file = await self.analyzer.verify_or_repair(True, True, file_name)
        pathlib.Path(fixed_file).unlink()

    async def test_extension_choice(self):

        scan_data = await self.analyzer._get_scan_data(True, self.video_file_name)
        extension = self.analyzer._get_best_container_extension(scan_data, "")
        self.assertEqual(extension, pathlib.Path(self.video_file_name).suffix[1:])

        scan_data = await self.analyzer._get_scan_data(True, self.video_file_ogg)
        extension = self.analyzer._get_best_container_extension(scan_data, "")
        self.assertEqual(extension, "ogg")

        scan_data = await self.analyzer._get_scan_data(True, self.video_file_webm)
        extension = self.analyzer._get_best_container_extension(scan_data, "")
        self.assertEqual(extension, "webm")

        extension = self.analyzer._get_best_container_extension("", "libx264 -crf 23")
        self.assertEqual("mp4", extension)

        extension = self.analyzer._get_best_container_extension("", "libvpx-vp9 -crf 23")
        self.assertEqual("webm", extension)

        extension = self.analyzer._get_best_container_extension("", "libtheora")
        self.assertEqual("ogg", extension)

    async def test_no_ffmpeg(self):
        self.conf.ffmpeg_folder = "I don't really exist/"
        with self.assertRaisesRegex(Exception, "Unable to locate"):
            await self.analyzer.verify_or_repair(True, False, self.video_file_name)
