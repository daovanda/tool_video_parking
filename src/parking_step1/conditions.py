"""Optional CV + VLM condition suggestions, separate from human ground truth."""

from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import re
import time
from typing import Callable

import cv2
import numpy as np

# Must be set at module import time, before PaddleX or Transformers can cache
# TensorFlow availability. Qwen runs through PyTorch only.
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")

from .evaluation import load_jsonl, save_jsonl
from .plate import clipped_box
from .video_frames import SequentialFrameReader


CONDITION_SCHEMA_VERSION = "0.3.0"
CONDITION_TYPES = ("capture_blur", "plate_obstruction", "lighting_issue")
PROMPT = (
    "Inspect this contact sheet of up to three frames from ONE parking vehicle event. "
    "Each row shows the scene, the vehicle, and the detected plate; a black plate tile means no plate was detected. "
    "First decide whether the license plate characters can be read reliably from at least one plate tile. "
    "If readable, return plate_readable=true and conditions=[] even when minor blur, reflection, darkness, "
    "dirt, or partial covering exists. A condition is an ISSUE only when it causes the plate to be unreadable. "
    "If unreadable, choose only visible root causes: capture_blur means camera focus or motion blur prevents "
    "reading; plate_obstruction means a physical object covers the plate and prevents reading; "
    "lighting_issue means darkness, backlight, glare, or overexposure prevents reading. "
    "Do not output fine-grained details. Do not infer obstruction merely because text is unreadable. "
    "Return ONLY JSON: {\"plate_readable\": true_or_false, \"conditions\": []}. "
    "conditions may contain only capture_blur, plate_obstruction, lighting_issue."
)


def parse_vlm_response(text: str) -> dict:
    """Accept only the fixed taxonomy; discard prose and invented labels."""
    match = re.search(r"\{", text)
    if not match:
        raise ValueError(f"VLM không trả JSON: {text[:200]}")
    data, _ = json.JSONDecoder().raw_decode(text[match.start():])
    if not isinstance(data, dict):
        raise ValueError("VLM JSON phải là object")
    readable = data.get("plate_readable")
    conditions = data.get("conditions", [])
    if not isinstance(readable, bool) or not isinstance(conditions, list):
        raise ValueError("VLM phải trả plate_readable boolean và conditions list")
    roots = [name for name in CONDITION_TYPES if name in conditions]
    if not readable and not roots:
        raise ValueError("VLM đánh giá không đọc được nhưng không nêu nguyên nhân")
    return {"plate_readable": readable, "conditions": [] if readable else roots}


def cv_measure(frame: np.ndarray, plate_box: list | None, vehicle_box: list | None) -> dict:
    """Transparent image measurements; thresholds are pilot heuristics."""
    height, width = frame.shape[:2]
    target_box = plate_box or vehicle_box
    if target_box:
        x1, y1, x2, y2 = clipped_box(target_box, width, height)
        crop = frame[y1:y2, x1:x2]
    else:
        crop = frame
    if crop.size == 0:
        crop = frame
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    scene_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    median = float(np.median(gray))
    scene_median = float(np.median(scene_gray))
    dark_fraction = float(np.mean(scene_gray < 45))
    bright_fraction = float(np.mean(gray > 245))
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    conditions = []
    if scene_median < 65 and dark_fraction > .55:
        conditions.append("lighting_issue")
    if bright_fraction > .22:
        conditions.append("lighting_issue")
    if plate_box and bright_fraction > .12 and median > 120:
        conditions.append("lighting_issue")
    if gray.shape[1] >= 60 and gray.shape[0] >= 20 and sharpness < 45:
        conditions.append("capture_blur")
    return {"median_luma": round(median, 2), "scene_median_luma": round(scene_median, 2),
            "scene_dark_fraction": round(dark_fraction, 4),
            "bright_fraction": round(bright_fraction, 4), "laplacian_variance": round(sharpness, 2),
            "suggested_conditions": sorted(set(conditions)), "region": "plate" if plate_box else
            "vehicle" if vehicle_box else "scene"}


def _tile(frame: np.ndarray | None, width: int = 320, height: int = 180) -> np.ndarray:
    result = np.zeros((height, width, 3), dtype=np.uint8)
    if frame is None or frame.size == 0:
        return result
    scale = min(width / frame.shape[1], height / frame.shape[0])
    resized = cv2.resize(frame, (max(1, round(frame.shape[1] * scale)),
                                 max(1, round(frame.shape[0] * scale))))
    top = (height - resized.shape[0]) // 2
    left = (width - resized.shape[1]) // 2
    result[top:top + resized.shape[0], left:left + resized.shape[1]] = resized
    return result


def contact_sheet(samples: list[dict]) -> np.ndarray:
    rows = []
    for sample in samples:
        frame = sample["frame"]
        h, w = frame.shape[:2]
        tiles = [_tile(frame)]
        for key in ("vehicle_box", "plate_box"):
            box = sample.get(key)
            if box:
                x1, y1, x2, y2 = clipped_box(box, w, h, .05)
                tiles.append(_tile(frame[y1:y2, x1:x2]))
            else:
                tiles.append(_tile(None))
        rows.append(np.concatenate(tiles, axis=1))
    return np.concatenate(rows, axis=0)


class QwenConditionVLM:
    def __init__(self, model_path: str):
        import torch
        from transformers import AutoProcessor, Qwen3VLForConditionalGeneration
        candidate = Path(model_path)
        if not candidate.is_absolute():
            candidate = Path(__file__).resolve().parents[2] / candidate
        if not (candidate / "model.safetensors").is_file():
            raise FileNotFoundError(f"Chưa có weights VLM tại {candidate}; cần tải Qwen3-VL-2B-Instruct")
        model_path = str(candidate)
        self.torch = torch
        self.processor = AutoProcessor.from_pretrained(model_path)
        self.model = Qwen3VLForConditionalGeneration.from_pretrained(
            model_path, dtype=torch.float32 if not torch.cuda.is_available() else "auto",
            device_map="auto")

    def analyze(self, image_bgr: np.ndarray) -> dict:
        from PIL import Image
        image = Image.fromarray(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB))
        messages = [{"role": "user", "content": [{"type": "image", "image": image},
                                                   {"type": "text", "text": PROMPT}]}]
        inputs = self.processor.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=True,
            return_dict=True, return_tensors="pt").to(self.model.device)
        with self.torch.inference_mode():
            output = self.model.generate(**inputs, max_new_tokens=160, do_sample=False)
        generated = output[0][inputs["input_ids"].shape[-1]:]
        return parse_vlm_response(self.processor.decode(generated, skip_special_tokens=True))


def _event_samples(event: dict, plate_record: dict, detections: list[dict],
                   capture: SequentialFrameReader, width: int, height: int,
                   max_frames: int) -> list[dict]:
    observations = sorted(plate_record.get("selected_observations", []),
                          key=lambda item: item["quality"]["score"], reverse=True)
    by_frame: dict[int, dict] = {}
    for item in observations:
        by_frame.setdefault(int(item["frame_index"]), item)
    if not by_frame:
        for record in detections:
            ts = int(record["timestamp_ms"])
            if not event["start_ms"] <= ts <= event["end_ms"]:
                continue
            vehicle = next((d for d in record["detections"]
                            if d["track_id"] == event["track_id"]), None)
            if vehicle:
                by_frame[int(record["frame_index"])] = {
                    "frame_index": record["frame_index"], "timestamp_ms": ts,
                    "vehicle_box": vehicle["box"], "plate_box": None}
    chosen = list(by_frame.values())[:max_frames] if observations else []
    if not chosen and by_frame:
        values = list(by_frame.values())
        positions = np.linspace(0, len(values)-1, min(max_frames, len(values)), dtype=int)
        chosen = [values[int(pos)] for pos in positions]
    result = []
    for item in sorted(chosen, key=lambda value: value["timestamp_ms"]):
        ok, frame = capture.read(int(item["frame_index"]))
        if not ok:
            continue
        result.append({"frame": frame, "frame_index": int(item["frame_index"]),
                       "timestamp_ms": int(item["timestamp_ms"]),
                       "vehicle_box": item.get("vehicle_box"),
                       "plate_box": item.get("plate_box")})
    return result


def _strong_ocr_evidence(plate_record: dict) -> bool:
    """Two independent high-confidence reads of the same text imply readability."""
    texts = Counter(item.get("ocr_text_normalized") for item in
                    plate_record.get("selected_observations", [])
                    if item.get("ocr_text_normalized") and
                    float(item.get("ocr_confidence") or 0) >= .85)
    return bool(texts and texts.most_common(1)[0][1] >= 2)


def fuse_conditions(samples: list[dict], vlm_result: dict,
                    plate_record: dict | None = None) -> dict:
    """Gate root-cause classification behind plate readability."""
    cv_votes = Counter(tag for item in samples for tag in item["cv"]["suggested_conditions"])
    cv_roots = {tag for tag, count in cv_votes.items() if count >= (len(samples) + 1) // 2}
    ocr_readable = _strong_ocr_evidence(plate_record or {})
    vlm_readable = bool(vlm_result.get("plate_readable", False))
    plate_visible = any(item.get("plate_box") for item in samples)
    vlm_roots = set(vlm_result.get("conditions", [])) & set(CONDITION_TYPES)
    if not plate_visible:
        vlm_roots.discard("plate_obstruction")
    candidate_roots = vlm_roots | cv_roots
    # Conservative default: without a supported root cause, do not mark an
    # event unreadable. This avoids turning uncertainty into a false issue.
    readable = ocr_readable or vlm_readable or not candidate_roots
    suppressed = sorted(vlm_roots | cv_roots) if readable else []
    roots = [] if readable else [name for name in CONDITION_TYPES if name in candidate_roots]
    sources = {root: sorted(source for source, present in
                            (("cv", root in cv_roots), ("vlm", root in vlm_roots)) if present)
               for root in roots}
    return {"plate_readable": readable, "condition_status": "good" if readable else "unreadable",
            "conditions": roots, "condition_sources": sources,
            "cv_support": dict(cv_votes), "ocr_readable": ocr_readable,
            "vlm_readable": vlm_readable, "suppressed_conditions": suppressed}


def run_condition_analysis(run_dir: str | Path, config, *, vlm=None,
                           progress: Callable[[int, str], None] | None = None,
                           cancel: Callable[[], bool] | None = None,
                           profile: dict[str, float] | None = None) -> list[dict]:
    run_dir = Path(run_dir)
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    events = load_jsonl(run_dir / "events.jsonl")
    detections = load_jsonl(run_dir / "detections.jsonl")
    plate_uri = run.get("artifacts", {}).get("plate_observations_uri")
    plates = {item["event_id"]: item for item in load_jsonl(run_dir / plate_uri)} if plate_uri else {}
    source = Path(run["source"]["uri"])
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError(f"Không mở được video raw: {source}")
    frames = SequentialFrameReader(capture)
    output = []
    timings = {"model_load_seconds": 0.0, "frame_seek_decode_seconds": 0.0,
               "cv_and_contact_sheet_seconds": 0.0, "vlm_generation_seconds": 0.0}
    try:
        has_condition_event = any(event.get("vehicle_type") != "bicycle" for event in events)
        phase_start = time.monotonic()
        vlm = (vlm or QwenConditionVLM(config.condition_vlm_model)) if has_condition_event else None
        timings["model_load_seconds"] += time.monotonic() - phase_start
        for index, event in enumerate(events):
            if cancel and cancel():
                raise RuntimeError("Đã hủy phân tích điều kiện")
            if event.get("vehicle_type") == "bicycle":
                output.append({"schema_version": CONDITION_SCHEMA_VERSION,
                               "run_id": run["run_id"], "event_id": event["event_id"],
                               "source_uri": str(source), "vlm_model": None,
                               "evidence_timestamps_ms": [], "cv_metrics": [],
                               "vlm_result": None, "plate_readable": None,
                               "condition_status": "not_applicable", "conditions": [],
                               "condition_sources": {}, "cv_support": {},
                               "ocr_readable": False, "vlm_readable": False,
                               "suppressed_conditions": [],
                               "skip_reason": "bicycle_has_no_required_license_plate"})
                if progress:
                    progress(90 + round((index + 1) / max(1, len(events)) * 10),
                             f"Điều kiện: bỏ qua bicycle {index + 1}/{len(events)} event")
                continue
            phase_start = time.monotonic()
            samples = _event_samples(event, plates.get(event["event_id"], {}), detections,
                                     frames, int(run["source"]["width"]),
                                     int(run["source"]["height"]), config.condition_max_frames)
            timings["frame_seek_decode_seconds"] += time.monotonic() - phase_start
            phase_start = time.monotonic()
            for sample in samples:
                sample["cv"] = cv_measure(sample["frame"], sample["plate_box"],
                                           sample["vehicle_box"])
            sheet = contact_sheet(samples) if samples else None
            timings["cv_and_contact_sheet_seconds"] += time.monotonic() - phase_start
            phase_start = time.monotonic()
            vlm_result = vlm.analyze(sheet) if samples else {
                "plate_readable": False, "conditions": []}
            timings["vlm_generation_seconds"] += time.monotonic() - phase_start
            fusion = fuse_conditions(samples, vlm_result, plates.get(event["event_id"], {}))
            output.append({"schema_version": CONDITION_SCHEMA_VERSION,
                           "run_id": run["run_id"], "event_id": event["event_id"],
                           "source_uri": str(source), "vlm_model": config.condition_vlm_model,
                           "evidence_timestamps_ms": [s["timestamp_ms"] for s in samples],
                           "cv_metrics": [{"timestamp_ms": s["timestamp_ms"], **s["cv"]} for s in samples],
                           "vlm_result": vlm_result, **fusion})
            if progress:
                progress(90 + round((index + 1) / max(1, len(events)) * 10),
                         f"Điều kiện CV + VLM: {index + 1}/{len(events)} event")
    finally:
        capture.release()
    artifact = run_dir / "condition_suggestions.jsonl"
    save_jsonl(artifact, output)
    run["schema_version"] = max(run.get("schema_version", "0.0.0"), "0.9.0",
                                key=lambda version: tuple(map(int, version.split("."))))
    run.setdefault("artifacts", {})["condition_suggestions_uri"] = artifact.name
    run["artifacts"]["condition_event_count"] = len(output)
    (run_dir / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    if profile is not None:
        profile.update(timings)
    return output
