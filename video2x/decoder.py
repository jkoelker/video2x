#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Name: Video Decoder
Author: K4YT3X
Date Created: June 17, 2021
Last Modified: June 17, 2021
"""

# built-in imports
import os
import pathlib
import queue
import subprocess
import threading

# third-party imports
from loguru import logger
from PIL import Image
import ffmpeg


# map Loguru log levels to FFmpeg log levels
LOGURU_FFMPEG_LOGLEVELS = {
    "trace": "trace",
    "debug": "debug",
    "info": "info",
    "success": "info",
    "warning": "warning",
    "error": "error",
    "critical": "fatal",
}


class VideoDecoder(threading.Thread):
    def __init__(
        self,
        input_path: pathlib.Path,
        input_width: int,
        input_height: int,
        frame_rate: float,
        processing_queue: queue.Queue,
        processing_settings: tuple,
        ignore_max_image_pixels=True,
    ):
        threading.Thread.__init__(self)
        self.running = False
        self.input_path = input_path
        self.input_width = input_width
        self.input_height = input_height
        self.processing_queue = processing_queue
        self.processing_settings = processing_settings

        # this disables the "possible DDoS" warning
        if ignore_max_image_pixels:
            Image.MAX_IMAGE_PIXELS = None

        self.exception = None
        self.decoder = subprocess.Popen(
            ffmpeg.compile(
                ffmpeg.input(input_path, r=frame_rate)["v"]
                .output("pipe:1", format="rawvideo", pix_fmt="rgb24", vsync="1")
                .global_args("-hide_banner")
                .global_args("-nostats")
                .global_args(
                    "-loglevel",
                    LOGURU_FFMPEG_LOGLEVELS.get(
                        os.environ.get("LOGURU_LEVEL", "INFO").lower()
                    ),
                ),
                overwrite_output=True,
            ),
            stdout=subprocess.PIPE,
            # stderr=subprocess.DEVNULL,
        )

    def run(self):
        self.running = True

        # the index of the frame
        frame_index = 0

        # create placeholder for previous frame
        # used in interpolate mode
        previous_image = None

        # continue running until an exception occurs
        # or all frames have been decoded
        while self.running:
            try:
                buffer = self.decoder.stdout.read(
                    3 * self.input_width * self.input_height
                )

                # source depleted (decoding finished)
                # after the last frame has been decoded
                # read will return nothing
                if len(buffer) == 0:
                    logger.debug("Decoding queue depleted")
                    break

                # convert raw bytes into image object
                image = Image.frombytes(
                    "RGB", (self.input_width, self.input_height), buffer
                )

                # if this is the first frame
                # there wouldn't be a "previous image"
                if previous_image is not None:
                    self.processing_queue.put(
                        (
                            frame_index,
                            (previous_image, image),
                            self.processing_settings,
                        )
                    )
                previous_image = image

                frame_index += 1

            # most likely "not enough image data"
            except ValueError as e:
                logger.exception(e)
                break

            # send exceptions into the client connection pipe
            except Exception as e:
                self.exception = e
                logger.exception(e)
                break

        # ensure the decoder has exited
        self.decoder.wait()
        logger.debug("Decoder thread exiting")

        self.running = False
        return super().run()

    def stop(self):
        self.running = False
