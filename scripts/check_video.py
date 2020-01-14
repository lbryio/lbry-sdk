#!/usr/bin/env python3

import asyncio
import logging
import sys
import lbry.wallet  # just to make the following line work:
from lbry.conf import TranscodeConfig
from lbry.file_analysis import VideoFileAnalyzer


def enable_logging():
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(message)s')  # %(asctime)s - %(levelname)s -
    handler.setFormatter(formatter)
    root.addHandler(handler)


async def main():
    if len(sys.argv) < 2:
        print("Usage: <path to video file>", file=sys.stderr)
        sys.exit(1)
    video_file = sys.argv[1]

    enable_logging()
    conf = TranscodeConfig()
    analyzer = VideoFileAnalyzer(conf)
    try:
        await analyzer.verify_or_repair(True, False, video_file)
        print("No concerns. Ship it!")
    except Exception as e:
        print(str(e))
        transcode = input("Would you like repair this via transcode now? [y/N] ")
        if transcode == "y":
            try:
                new_video_file = await analyzer.verify_or_repair(True, True, video_file)
                print("Successfully created ", new_video_file)
            except Exception as e:
                print("Unable to complete the transcode. Message: ", str(e))


if __name__ == '__main__':
    asyncio.run(main())
