from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import json


def _point_on_segment(point: list[float], start: list[float], end: list[float], eps: float = 1e-9) -> bool:
    cross = ((point[0] - start[0]) * (end[1] - start[1]) -
             (point[1] - start[1]) * (end[0] - start[0]))
    if abs(cross) > eps:
        return False
    return (min(start[0], end[0]) - eps <= point[0] <= max(start[0], end[0]) + eps and
            min(start[1], end[1]) - eps <= point[1] <= max(start[1], end[1]) + eps)


def _point_in_polygon(point: list[float], polygon: list[list[float]]) -> bool:
    """Boundary-inclusive point-in-polygon test in normalized coordinates."""
    inside = False
    previous = polygon[-1]
    for current in polygon:
        if _point_on_segment(point, previous, current):
            return True
        if ((current[1] > point[1]) != (previous[1] > point[1])):
            intersection_x = ((previous[0] - current[0]) * (point[1] - current[1]) /
                              (previous[1] - current[1]) + current[0])
            if point[0] < intersection_x:
                inside = not inside
        previous = current
    return inside


def _segments_intersect(a: list[float], b: list[float], c: list[float], d: list[float],
                        eps: float = 1e-9) -> bool:
    def orientation(p: list[float], q: list[float], r: list[float]) -> float:
        return ((q[0] - p[0]) * (r[1] - p[1]) -
                (q[1] - p[1]) * (r[0] - p[0]))

    o1, o2 = orientation(a, b, c), orientation(a, b, d)
    o3, o4 = orientation(c, d, a), orientation(c, d, b)
    if ((o1 > eps and o2 < -eps) or (o1 < -eps and o2 > eps)) and \
            ((o3 > eps and o4 < -eps) or (o3 < -eps and o4 > eps)):
        return True
    return ((abs(o1) <= eps and _point_on_segment(c, a, b, eps)) or
            (abs(o2) <= eps and _point_on_segment(d, a, b, eps)) or
            (abs(o3) <= eps and _point_on_segment(a, c, d, eps)) or
            (abs(o4) <= eps and _point_on_segment(b, c, d, eps)))


def line_intersects_roi(line: list[list[float]], roi: list[list[float]]) -> bool:
    """Return True when a line endpoint is inside ROI or it crosses its boundary."""
    if _point_in_polygon(line[0], roi) or _point_in_polygon(line[1], roi):
        return True
    return any(_segments_intersect(line[0], line[1], roi[index - 1], roi[index])
               for index in range(len(roi)))


@dataclass
class CameraConfig:
    camera_id: str
    lane_id: str
    direction: str
    roi: list[list[float]] = field(default_factory=list)
    crossing_line: list[list[float]] = field(default_factory=list)

    def validate(self) -> None:
        if not self.camera_id.strip() or not self.lane_id.strip():
            raise ValueError("camera_id và lane_id không được trống")
        if self.direction not in {"ENTRY", "EXIT"}:
            raise ValueError("direction phải là ENTRY hoặc EXIT")
        if self.roi and (len(self.roi) < 3 or any(len(p) != 2 or any(x < 0 or x > 1 for x in p) for p in self.roi)):
            raise ValueError("ROI cần ít nhất 3 điểm chuẩn hóa trong [0,1]")
        if self.crossing_line and (len(self.crossing_line) != 2 or any(len(p) != 2 or any(x < 0 or x > 1 for x in p) for p in self.crossing_line)):
            raise ValueError("crossing_line cần đúng 2 điểm chuẩn hóa trong [0,1]")
        if len(self.crossing_line) == 2 and self.crossing_line[0] == self.crossing_line[1]:
            raise ValueError("crossing_line cần hai điểm khác nhau")
        if self.roi and self.crossing_line and not line_intersects_roi(self.crossing_line, self.roi):
            raise ValueError(
                "Crossing line nằm hoàn toàn ngoài ROI. Hãy vẽ line cắt qua hoặc nằm bên trong ROI; "
                "corridor chạm ROI không được xem là hợp lệ."
            )


@dataclass
class RunConfig:
    camera: CameraConfig
    source: str
    output_dir: str
    model: str = "yolo26s.pt"
    image_size: int = 960
    sample_fps: float = 10.0
    confidence: float = 0.12
    candidate_hits: int = 2
    min_motion_distance: float = 0.015
    motion_window_seconds: float = 1.5
    line_gate_margin: float = 0.12
    grace_seconds: float = 1.5
    pre_seconds: float = 1.5
    post_seconds: float = 2.0
    merge_gap_seconds: float = 0.5
    make_clips: bool = True
    plate_ocr_enabled: bool = False
    plate_model: str = "yolov8n-oiv7.pt"
    plate_class_name: str = "Vehicle registration plate"
    plate_confidence: float = 0.15
    plate_top_k: int = 5
    plate_min_gap_ms: int = 300
    ocr_model: str = "latin_PP-OCRv5_mobile_rec"
    condition_analysis_enabled: bool = False
    condition_vlm_model: str = "models/Qwen3-VL-2B-Instruct"
    condition_max_frames: int = 3
    capture_start_utc: str | None = None

    def validate(self) -> None:
        self.camera.validate()
        if not Path(self.source).is_file():
            raise ValueError(f"Không tìm thấy video: {self.source}")
        if not self.output_dir.strip():
            raise ValueError("Cần chọn thư mục đầu ra")
        if self.image_size <= 0 or self.sample_fps <= 0 or not 0 <= self.confidence <= 1:
            raise ValueError("image_size, sample_fps hoặc confidence không hợp lệ")
        if not 0 <= self.line_gate_margin <= 1:
            raise ValueError("line_gate_margin phải nằm trong [0,1]")
        if not 0 <= self.min_motion_distance <= 1 or self.motion_window_seconds <= 0:
            raise ValueError("min_motion_distance phải trong [0,1] và motion_window_seconds phải dương")
        if self.candidate_hits < 1 or min(self.grace_seconds, self.pre_seconds, self.post_seconds, self.merge_gap_seconds) < 0:
            raise ValueError("candidate_hits và các khoảng thời gian phải không âm")
        if not self.plate_model.strip() or not self.plate_class_name.strip() or not self.ocr_model.strip():
            raise ValueError("Cần tên model phát hiện biển số, class biển số và model OCR")
        if not 0 <= self.plate_confidence <= 1 or self.plate_top_k < 1 or self.plate_min_gap_ms < 0:
            raise ValueError("Cấu hình plate confidence/top-K/khoảng cách frame không hợp lệ")
        if not self.condition_vlm_model.strip() or not 1 <= self.condition_max_frames <= 5:
            raise ValueError("Cấu hình model VLM hoặc số frame điều kiện không hợp lệ")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> "RunConfig":
        value = dict(value)
        value["camera"] = CameraConfig(**value["camera"])
        return cls(**value)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "RunConfig":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
