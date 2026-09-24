"""Per-event plate detection and OCR suggestions on immutable source frames."""

from __future__ import annotations

from collections import defaultdict
import json
import os
from pathlib import Path
import re
import time
from typing import Callable

import cv2
import numpy as np

from .video_frames import SequentialFrameReader

# PaddleX imports Hugging Face Transformers internally.  This pipeline uses
# PyTorch for Qwen and does not need TensorFlow.  Set these flags before the
# first PaddleOCR/Transformers import; setting them later in QwenConditionVLM
# is too late because Transformers caches backend availability at import time.
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")


PLATE_SCHEMA_VERSION = "0.2.0"


def normalize_plate(text: str) -> str:
    """Remove presentation separators without guessing ambiguous characters."""
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def clipped_box(box: list[float], width: int, height: int, padding: float = 0.0) -> list[int]:
    x1, y1, x2, y2 = box
    dx, dy = (x2 - x1) * padding, (y2 - y1) * padding
    return [max(0, int(x1 - dx)), max(0, int(y1 - dy)),
            min(width, int(x2 + dx + .999)), min(height, int(y2 + dy + .999))]


def frame_quality(plate_crop: np.ndarray, plate_confidence: float,
                  vehicle_area: int) -> dict:
    """Rank candidates before OCR; these are heuristics, not calibrated probabilities."""
    gray = cv2.cvtColor(plate_crop, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    sharpness_raw = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    sharpness = min(1.0, sharpness_raw / 500.0)
    plate_size = min(1.0, width / 160.0, height / 35.0)
    dark = float(np.mean(gray < 25))
    bright = float(np.mean(gray > 245))
    contrast = min(1.0, float(gray.std()) / 55.0)
    exposure = contrast * max(0.0, 1.0 - dark - bright)
    relative_area = min(1.0, width * height / max(1, vehicle_area) / .08)
    score = (.45 * plate_confidence + .20 * sharpness + .15 * plate_size
             + .10 * exposure + .10 * relative_area)
    return {"score": round(score, 6), "sharpness": round(sharpness, 6),
            "plate_size": round(plate_size, 6), "exposure_contrast": round(exposure, 6),
            "relative_area": round(relative_area, 6)}


def select_diverse(observations: list[dict], top_k: int, min_gap_ms: int) -> list[dict]:
    selected: list[dict] = []
    for item in sorted(observations, key=lambda item: item["quality"]["score"], reverse=True):
        if all(abs(item["timestamp_ms"] - other["timestamp_ms"]) >= min_gap_ms
               for other in selected):
            selected.append(item)
            if len(selected) == top_k:
                break
    return sorted(selected, key=lambda item: item["timestamp_ms"])


def consensus(observations: list[dict]) -> dict | None:
    votes: dict[str, list[dict]] = defaultdict(list)
    for item in observations:
        text = item.get("ocr_text_normalized", "")
        if text:
            votes[text].append(item)
    if not votes:
        return None
    def weight(items: list[dict]) -> float:
        return sum(float(x["quality"]["score"]) * float(x["ocr_confidence"])
                   for x in items)
    best_text, supporters = max(votes.items(), key=lambda pair: (weight(pair[1]), len(pair[1])))
    total = sum(weight(items) for items in votes.values())
    return {"text": best_text, "confidence": round(weight(supporters) / total, 6),
            "support_count": len(supporters),
            "timestamps_ms": [item["timestamp_ms"] for item in supporters]}


class YoloPlateDetector:
    def __init__(self, model_path: str, class_name: str, confidence: float):
        from ultralytics import YOLO
        self.model = YOLO(model_path)
        names = self.model.names
        self.class_ids = {int(key) for key, name in names.items() if name == class_name}
        if not self.class_ids:
            raise ValueError(f"Plate model không có class {class_name!r}; classes={names}")
        self.confidence = confidence

    def detect(self, vehicle_crop: np.ndarray) -> list[dict]:
        result = self.model.predict(vehicle_crop, conf=self.confidence, verbose=False)[0]
        if result.boxes is None:
            return []
        detections = []
        for cls, score, box in zip(result.boxes.cls.int().cpu().tolist(),
                                   result.boxes.conf.cpu().tolist(), result.boxes.xyxy.cpu().tolist()):
            if cls in self.class_ids:
                detections.append({"box": [float(value) for value in box],
                                   "confidence": float(score)})
        return detections


class PaddlePlateOCR:
    def __init__(self, model_name: str):
        try:
            from paddleocr import TextRecognition
        except ImportError as exc:
            raise RuntimeError("Cần cài paddlepaddle và paddleocr để bật Plate OCR") from exc
        self.model = TextRecognition(model_name=model_name)

    def recognize(self, plate_crop: np.ndarray) -> tuple[str, float]:
        result = self.model.predict(input=plate_crop, batch_size=1)
        if not result:
            return "", 0.0
        data = result[0].json
        if isinstance(data, str):
            data = json.loads(data)
        data = data.get("res", data)
        return str(data.get("rec_text", "")), float(data.get("rec_score", 0.0))


def run_plate_enrichment(run_dir: str | Path, config, *, detector=None, ocr=None,
                         progress: Callable[[int, str], None] | None = None,
                         cancel: Callable[[], bool] | None = None,
                         profile: dict[str, float] | None = None) -> list[dict]:
    """Read Step 1 artifacts and write one plate record per event.

    Plate coordinates in observations are in raw source-frame pixels.  The
    detector only receives a padded crop of the selected event's vehicle box.
    """
    run_dir = Path(run_dir)
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    source = Path(run["source"]["uri"])
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines() if line]
    records = [json.loads(line) for line in (run_dir / "detections.jsonl").read_text(encoding="utf-8").splitlines() if line]
    has_plate_applicable_event = any(event.get("vehicle_type") != "bicycle" for event in events)
    timings = {"model_load_seconds": 0.0, "frame_seek_decode_seconds": 0.0,
               "plate_detection_seconds": 0.0, "ocr_seconds": 0.0}
    if has_plate_applicable_event:
        phase_start = time.monotonic()
        detector = detector or YoloPlateDetector(config.plate_model, config.plate_class_name,
                                                 config.plate_confidence)
        ocr = ocr or PaddlePlateOCR(config.ocr_model)
        timings["model_load_seconds"] += time.monotonic() - phase_start
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError(f"Không mở được video raw để đọc biển số: {source}")
    width, height = int(run["source"]["width"]), int(run["source"]["height"])
    frames = SequentialFrameReader(capture)
    output: list[dict] = []
    try:
        for index, event in enumerate(events):
            if cancel and cancel():
                raise RuntimeError("Đã hủy xử lý biển số")
            if event.get("vehicle_type") == "bicycle":
                output.append({"schema_version": PLATE_SCHEMA_VERSION, "run_id": run["run_id"],
                               "event_id": event["event_id"], "clip_id": event["clip_id"],
                               "camera_id": event["camera_id"], "lane_id": event["lane_id"],
                               "direction": event["direction"], "source_uri": str(source),
                               "plate_model": None, "ocr_model": None,
                               "plate_applicability": "not_applicable",
                               "plate_presence": "absent_by_vehicle_type",
                               "skip_reason": "bicycle_has_no_required_license_plate",
                               "candidate_count": 0, "observations": [],
                               "selected_observations": [], "consensus": None})
                if progress:
                    progress(90 + round((index+1)/max(1,len(events))*10),
                             f"Plate OCR: bỏ qua bicycle {index+1}/{len(events)} event")
                continue
            candidates = []
            for record in records:
                timestamp_ms = int(record["timestamp_ms"])
                if not event["start_ms"] <= timestamp_ms <= event["end_ms"]:
                    continue
                matching = [d for d in record["detections"] if d["track_id"] == event["track_id"]]
                if not matching:
                    continue
                phase_start = time.monotonic()
                ok, frame = frames.read(int(record["frame_index"]))
                timings["frame_seek_decode_seconds"] += time.monotonic() - phase_start
                if not ok:
                    continue
                for vehicle in matching:
                    vx1, vy1, vx2, vy2 = clipped_box(vehicle["box"], width, height, .12)
                    if vx2 <= vx1 or vy2 <= vy1:
                        continue
                    vehicle_crop = frame[vy1:vy2, vx1:vx2]
                    phase_start = time.monotonic()
                    plates_found = detector.detect(vehicle_crop)
                    timings["plate_detection_seconds"] += time.monotonic() - phase_start
                    for plate in plates_found:
                        px1, py1, px2, py2 = clipped_box(plate["box"], vx2-vx1, vy2-vy1)
                        if px2 <= px1 or py2 <= py1:
                            continue
                        plate_crop = vehicle_crop[py1:py2, px1:px2]
                        if plate_crop.size == 0:
                            continue
                        candidates.append({"timestamp_ms": timestamp_ms,
                                           "frame_index": int(record["frame_index"]),
                                           "vehicle_box": vehicle["box"],
                                           "plate_box": [vx1+px1, vy1+py1, vx1+px2, vy1+py2],
                                           "plate_confidence": plate["confidence"],
                                           "quality": frame_quality(plate_crop, plate["confidence"],
                                                                    (vx2-vx1)*(vy2-vy1))})
            selected = select_diverse(candidates, config.plate_top_k, config.plate_min_gap_ms)
            for item in selected:
                phase_start = time.monotonic()
                ok, frame = frames.read(item["frame_index"])
                timings["frame_seek_decode_seconds"] += time.monotonic() - phase_start
                if not ok:
                    continue
                x1, y1, x2, y2 = clipped_box(item["plate_box"], width, height, .05)
                phase_start = time.monotonic()
                text, confidence = ocr.recognize(frame[y1:y2, x1:x2])
                timings["ocr_seconds"] += time.monotonic() - phase_start
                item["ocr_text_raw"] = text
                item["ocr_text_normalized"] = normalize_plate(text)
                item["ocr_confidence"] = confidence
            summary = consensus(selected)
            output.append({"schema_version": PLATE_SCHEMA_VERSION, "run_id": run["run_id"],
                           "event_id": event["event_id"], "clip_id": event["clip_id"],
                           "camera_id": event["camera_id"], "lane_id": event["lane_id"],
                           "direction": event["direction"], "source_uri": str(source),
                           "plate_model": config.plate_model, "ocr_model": config.ocr_model,
                           "plate_applicability": "applicable",
                           "candidate_count": len(candidates), "observations": candidates,
                           "selected_observations": selected, "consensus": summary})
            if progress:
                progress(90 + round((index+1)/max(1,len(events))*10),
                         f"Plate OCR: {index+1}/{len(events)} event")
    finally:
        capture.release()
    artifact = run_dir / "plate_observations.jsonl"
    artifact.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in output), encoding="utf-8")
    run["schema_version"] = "0.9.0"
    run.setdefault("artifacts", {})["plate_observations_uri"] = artifact.name
    run["artifacts"]["plate_event_count"] = len(output)
    (run_dir / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    if profile is not None:
        profile.update(timings)
    return output
