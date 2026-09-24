"""Read source frames in request order without seeking for every sampled frame."""

from __future__ import annotations

import cv2


class SequentialFrameReader:
    def __init__(self, capture: cv2.VideoCapture):
        self.capture = capture
        self.next_index: int | None = None

    def read(self, frame_index: int):
        frame_index = int(frame_index)
        if self.next_index is None or frame_index < self.next_index:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            self.next_index = frame_index
        while self.next_index < frame_index:
            if not self.capture.grab():
                return False, None
            self.next_index += 1
        ok, frame = self.capture.read()
        if ok:
            self.next_index = frame_index + 1
        return ok, frame
