from __future__ import annotations

from dataclasses import dataclass
import math
import cv2
import numpy as np


@dataclass(frozen=True)
class Detection:
    track_id: int
    vehicle_type: str
    confidence: float
    box: tuple[float, float, float, float]

    @property
    def anchor(self) -> tuple[float, float]:
        x1, _, x2, y2 = self.box
        return ((x1 + x2) / 2, y2)


def in_roi(anchor: tuple[float, float], roi: list[list[float]], width: int, height: int) -> bool:
    if not roi:
        return True
    polygon = np.asarray([[round(x * width), round(y * height)] for x, y in roi], dtype=np.int32)
    return cv2.pointPolygonTest(polygon, anchor, False) >= 0


def side_of_line(anchor: tuple[float, float], line: list[list[float]], width: int, height: int) -> float:
    (ax, ay), (bx, by) = [(x * width, y * height) for x, y in line]
    return (bx - ax) * (anchor[1] - ay) - (by - ay) * (anchor[0] - ax)


def in_line_corridor(anchor: tuple[float, float], line: list[list[float]], width: int,
                     height: int, margin: float) -> bool:
    """Return whether an anchor is close to the configured line segment.

    The margin is measured in normalized frame units.  This gate is used only
    when no explicit ROI is supplied, so a line drawn by an operator still
    excludes parked/background vehicles from a full-frame run.
    """
    if not line or margin <= 0:
        return True
    x, y = anchor[0] / width, anchor[1] / height
    (ax, ay), (bx, by) = line
    vx, vy = bx - ax, by - ay
    length_sq = vx * vx + vy * vy
    if length_sq <= 1e-12:
        return False
    projection = ((x - ax) * vx + (y - ay) * vy) / length_sq
    if projection < 0 or projection > 1:
        return False
    closest_x, closest_y = ax + projection * vx, ay + projection * vy
    return math.hypot(x - closest_x, y - closest_y) <= margin


class EventEngine:
    def __init__(self, roi: list[list[float]], line: list[list[float]], width: int, height: int,
                 candidate_hits: int, grace_ms: int, line_gate_margin: float = 0.12,
                 min_motion_distance: float = 0.015, motion_window_ms: int = 1500):
        self.roi, self.line = roi, line
        self.width, self.height = width, height
        self.candidate_hits, self.grace_ms = candidate_hits, grace_ms
        self.line_gate_margin = line_gate_margin
        self.min_motion_distance = min_motion_distance
        self.motion_window_ms = motion_window_ms
        self.open: dict[int, dict] = {}
        self.finished: list[dict] = []
        self.counter = 0

    def update(self, timestamp_ms: int, detections: list[Detection]) -> None:
        visible = set()
        for det in detections:
            if not in_roi(det.anchor, self.roi, self.width, self.height):
                continue
            event = self.open.get(det.track_id)
            # Whenever a line exists, its corridor is an opening gate. With
            # an ROI this becomes ROI ∩ corridor, preventing parked vehicles
            # elsewhere in the ROI from opening events. Once open, keep the
            # track outside the corridor so departure/grace is not cut short.
            if event is None and self.line and not in_line_corridor(
                    det.anchor, self.line, self.width, self.height, self.line_gate_margin):
                continue
            visible.add(det.track_id)
            if event is None:
                self.counter += 1
                event = {
                    "event_id": f"EVT-{self.counter:06d}", "track_id": det.track_id,
                    "vehicle_type": det.vehicle_type, "start_ms": timestamp_ms,
                    "end_ms": timestamp_ms, "hits": 0, "confidence_sum": 0.0,
                    "confidence_max": 0.0, "crossed": False, "crossing_ms": None,
                    "last_side": None, "pending_crossing_ms": None, "state": "CANDIDATE",
                    "candidate_anchor": det.anchor, "candidate_start_ms": timestamp_ms,
                    "motion_distance": 0.0, "motion_confirmed": False,
                    "first_detection": {
                        "timestamp_ms": timestamp_ms,
                        "track_id": det.track_id,
                        "vehicle_type": det.vehicle_type,
                        "confidence": det.confidence,
                        "box": list(det.box),
                    },
                }
                self.open[det.track_id] = event
            elif event["state"] == "CANDIDATE" and timestamp_ms - event["candidate_start_ms"] > self.motion_window_ms:
                # A track may be parked for a long time and depart later. Keep
                # only a rolling candidate window so the resulting event starts
                # shortly before actual movement, not when the parked car was
                # first detected.
                event.update({
                    "start_ms": timestamp_ms, "end_ms": timestamp_ms, "hits": 0,
                    "confidence_sum": 0.0, "confidence_max": 0.0,
                    "candidate_anchor": det.anchor, "candidate_start_ms": timestamp_ms,
                    "motion_distance": 0.0, "last_side": None,
                    "pending_crossing_ms": None,
                    "first_detection": {
                        "timestamp_ms": timestamp_ms, "track_id": det.track_id,
                        "vehicle_type": det.vehicle_type, "confidence": det.confidence,
                        "box": list(det.box),
                    },
                })
            event["hits"] += 1
            event["end_ms"] = timestamp_ms
            event["confidence_sum"] += det.confidence
            event["confidence_max"] = max(event["confidence_max"], det.confidence)
            dx = (det.anchor[0] - event["candidate_anchor"][0]) / self.width
            dy = (det.anchor[1] - event["candidate_anchor"][1]) / self.height
            event["motion_distance"] = max(event["motion_distance"], math.hypot(dx, dy))
            if (event["hits"] >= self.candidate_hits and
                    event["motion_distance"] >= self.min_motion_distance):
                event["state"] = "ACTIVE"
                event["motion_confirmed"] = True
                if event["pending_crossing_ms"] is not None:
                    event["crossed"] = True
                    event["crossing_ms"] = event["pending_crossing_ms"]
            if self.line:
                side = side_of_line(det.anchor, self.line, self.width, self.height)
                last = event["last_side"]
                if last is not None and side * last < 0 and not event["crossed"]:
                    if event["motion_confirmed"]:
                        event["crossed"] = True
                        event["crossing_ms"] = timestamp_ms
                    else:
                        event["pending_crossing_ms"] = timestamp_ms
                if abs(side) > 1e-6:
                    event["last_side"] = side
        for track_id, event in list(self.open.items()):
            if track_id in visible:
                continue
            event["state"] = "LEAVING" if event["motion_confirmed"] else "CANDIDATE"
            if timestamp_ms - event["end_ms"] >= self.grace_ms:
                self._close(track_id)

    def _close(self, track_id: int) -> None:
        event = self.open.pop(track_id)
        if not event["motion_confirmed"]:
            return
        event["state"] = "CLOSED"
        event["confidence_mean"] = event["confidence_sum"] / event["hits"]
        del event["confidence_sum"]
        del event["last_side"]
        del event["candidate_anchor"]
        del event["candidate_start_ms"]
        del event["pending_crossing_ms"]
        self.finished.append(event)

    def flush(self) -> list[dict]:
        for track_id in list(self.open):
            self._close(track_id)
        return sorted(self.finished, key=lambda event: (event["start_ms"], event["track_id"]))


def plan_segments(events: list[dict], duration_ms: int, pre_ms: int, post_ms: int, merge_gap_ms: int) -> list[dict]:
    spans = sorted((max(0, e["start_ms"] - pre_ms), min(duration_ms, e["end_ms"] + post_ms), e["event_id"]) for e in events)
    segments: list[dict] = []
    for start, end, event_id in spans:
        if segments and start <= segments[-1]["end_ms"] + merge_gap_ms:
            segments[-1]["end_ms"] = max(segments[-1]["end_ms"], end)
            segments[-1]["event_ids"].append(event_id)
        else:
            segments.append({"start_ms": start, "end_ms": end, "event_ids": [event_id]})
    for index, segment in enumerate(segments, start=1):
        segment["clip_id"] = f"CLIP-{index:06d}"
    return segments
