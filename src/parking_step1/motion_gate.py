"""Conservative MOG2 gate for sampled vehicle-detector frames."""

from __future__ import annotations

import cv2
import numpy as np


class MotionGate:
    def __init__(self, width: int, height: int, roi: list[list[float]], *,
                 input_width: int, min_area_fraction: float, warmup_ms: int,
                 hold_ms: int, probe_ms: int, sample_fps: float):
        scaled_width = min(width, input_width)
        scaled_height = max(1, round(height * scaled_width / width))
        self.size = (scaled_width, scaled_height)
        self.subtractor = cv2.createBackgroundSubtractorMOG2(
            history=max(30, round(sample_fps * 8)), varThreshold=16,
            detectShadows=False)
        self.kernel = np.ones((3, 3), dtype=np.uint8)
        self.roi_mask = np.full((scaled_height, scaled_width), 255, dtype=np.uint8)
        if roi:
            self.roi_mask.fill(0)
            polygon = np.asarray([[round(x * (scaled_width - 1)),
                                   round(y * (scaled_height - 1))]
                                  for x, y in roi], dtype=np.int32)
            cv2.fillPoly(self.roi_mask, [polygon], 255)
        self.roi_pixels = max(1, cv2.countNonZero(self.roi_mask))
        self.min_area_fraction = min_area_fraction
        self.warmup_ms = warmup_ms
        self.hold_ms = hold_ms
        self.probe_ms = probe_ms
        self.first_ms: int | None = None
        self.last_motion_ms: int | None = None
        self.last_detector_ms: int | None = None

    def should_detect(self, frame: np.ndarray, timestamp_ms: int, *,
                      has_open_track: bool) -> bool:
        if self.first_ms is None:
            self.first_ms = timestamp_ms
        small = cv2.resize(frame, self.size, interpolation=cv2.INTER_AREA)
        foreground = self.subtractor.apply(small)
        foreground = cv2.bitwise_and(foreground, self.roi_mask)
        foreground = cv2.morphologyEx(foreground, cv2.MORPH_OPEN, self.kernel)
        motion = (cv2.countNonZero(foreground) / self.roi_pixels
                  >= self.min_area_fraction)
        if motion:
            self.last_motion_ms = timestamp_ms
        warmup = timestamp_ms - self.first_ms < self.warmup_ms
        hold = (self.last_motion_ms is not None and
                timestamp_ms - self.last_motion_ms <= self.hold_ms)
        probe = (self.last_detector_ms is None or
                 timestamp_ms - self.last_detector_ms >= self.probe_ms)
        detect = warmup or hold or has_open_track or probe
        if detect:
            self.last_detector_ms = timestamp_ms
        return detect
