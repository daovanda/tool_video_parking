from __future__ import annotations

from pathlib import Path
from typing import Literal
import json
import os
import re
import shutil
from urllib.parse import unquote

import cv2
from fastapi import Body, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from parking_step1.config import CameraConfig, RunConfig
from parking_step1.evaluation import load_jsonl, save_jsonl
from parking_step1.pipeline import video_info

from .jobs import RunJobs
from .export_excel import _best_frame, make_review_workbook
from .media import browser_compatible_mp4
from .metrics import evaluate_review
from .storage import WebStorage, utc_now


ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get("PARKING_WEB_DATA", ROOT / "web_data"))
storage = WebStorage(DATA_ROOT)
jobs = RunJobs(storage)

app = FastAPI(title="Parking Video Local API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CameraPayload(BaseModel):
    camera_id: str = "CAM01"
    lane_id: str = "ENTRY_01"
    direction: Literal["ENTRY", "EXIT"] = "ENTRY"
    roi: list[list[float]] = Field(default_factory=list)
    crossing_line: list[list[float]] = Field(default_factory=list)


class RunPayload(BaseModel):
    video_id: str
    camera: CameraPayload
    model: str = "yolo26s.pt"
    image_size: int = 960
    sample_fps: float = 10
    motion_gate_enabled: bool = False
    motion_gate_width: int = Field(default=320, ge=16)
    motion_gate_min_area_fraction: float = Field(default=.002, gt=0, le=1)
    motion_gate_warmup_seconds: float = Field(default=1.0, ge=0)
    motion_gate_hold_seconds: float = Field(default=1.5, ge=0)
    motion_gate_probe_seconds: float = Field(default=.5, gt=0)
    confidence: float = .12
    candidate_hits: int = 2
    min_motion_distance: float = .015
    motion_window_seconds: float = 1.5
    line_gate_margin: float = .12
    grace_seconds: float = 1.5
    pre_seconds: float = 1.5
    post_seconds: float = 2
    merge_gap_seconds: float = .5
    make_clips: bool = True
    plate_ocr_enabled: bool = False
    plate_model: str = "yolov8n-oiv7.pt"
    plate_class_name: str = "Vehicle registration plate"
    plate_confidence: float = .15
    plate_top_k: int = 5
    plate_min_gap_ms: int = 300
    ocr_model: str = "latin_PP-OCRv5_mobile_rec"
    condition_analysis_enabled: bool = False
    condition_vlm_model: str = "models/Qwen3-VL-2B-Instruct"
    condition_max_frames: int = 3


class RunAdvancedSettings(BaseModel):
    model: str = Field(default="yolo26s.pt", min_length=1)
    image_size: int = Field(default=960, ge=1)
    grace_seconds: float = Field(default=1.5, ge=0)
    pre_seconds: float = Field(default=1.5, ge=0)
    post_seconds: float = Field(default=2, ge=0)
    merge_gap_seconds: float = Field(default=.5, ge=0)
    plate_model: str = Field(default="yolov8n-oiv7.pt", min_length=1)
    plate_class_name: str = Field(default="Vehicle registration plate", min_length=1)
    plate_confidence: float = Field(default=.15, ge=0, le=1)
    plate_top_k: int = Field(default=5, ge=1)
    plate_min_gap_ms: int = Field(default=300, ge=0)
    ocr_model: str = Field(default="latin_PP-OCRv5_mobile_rec", min_length=1)
    condition_vlm_model: str = Field(default="models/Qwen3-VL-2B-Instruct", min_length=1)
    condition_max_frames: int = Field(default=3, ge=1, le=5)


class EvaluationSettings(BaseModel):
    min_temporal_iou: float = Field(default=.30, gt=0, le=1)
    boundary_tolerance_ms: int = Field(default=500, ge=0)
    coverage_threshold: float = Field(default=.95, gt=0, le=1)


class SettingsPayload(BaseModel):
    schema_version: Literal["0.1.0"] = "0.1.0"
    run_defaults: RunAdvancedSettings = Field(default_factory=RunAdvancedSettings)
    evaluation: EvaluationSettings = Field(default_factory=EvaluationSettings)


class AnnotationPayload(BaseModel):
    event_id: str
    source_event_id: str | None = None
    is_valid_event: bool = True
    vehicle_type: Literal["car", "motorcycle", "bicycle"]
    crossed: bool
    plate_text: str | None = None
    plate_readable: bool | None = None
    condition_status: Literal["good", "unreadable", "not_applicable"]
    conditions: list[Literal["capture_blur", "plate_obstruction", "lighting_issue"]] = Field(default_factory=list)
    start_ms: int
    end_ms: int


def _video(video_id: str) -> dict:
    value = storage.get_video(video_id)
    if not value:
        raise HTTPException(404, "Không tìm thấy video")
    return value


def _run(run_id: str) -> dict:
    value = storage.get_run(run_id)
    if not value:
        raise HTTPException(404, "Không tìm thấy run")
    return value


def _config(payload: RunPayload, output_dir: Path) -> RunConfig:
    video = _video(payload.video_id)
    config = RunConfig(
        camera=CameraConfig(**payload.camera.model_dump()), source=video["stored_path"],
        output_dir=str(output_dir), model=payload.model, image_size=payload.image_size,
        sample_fps=payload.sample_fps, confidence=payload.confidence,
        motion_gate_enabled=payload.motion_gate_enabled,
        motion_gate_width=payload.motion_gate_width,
        motion_gate_min_area_fraction=payload.motion_gate_min_area_fraction,
        motion_gate_warmup_seconds=payload.motion_gate_warmup_seconds,
        motion_gate_hold_seconds=payload.motion_gate_hold_seconds,
        motion_gate_probe_seconds=payload.motion_gate_probe_seconds,
        candidate_hits=payload.candidate_hits, min_motion_distance=payload.min_motion_distance,
        motion_window_seconds=payload.motion_window_seconds,
        line_gate_margin=payload.line_gate_margin, grace_seconds=payload.grace_seconds,
        pre_seconds=payload.pre_seconds, post_seconds=payload.post_seconds,
        merge_gap_seconds=payload.merge_gap_seconds, make_clips=payload.make_clips,
        plate_ocr_enabled=payload.plate_ocr_enabled, plate_model=payload.plate_model,
        plate_class_name=payload.plate_class_name, plate_confidence=payload.plate_confidence,
        plate_top_k=payload.plate_top_k, plate_min_gap_ms=payload.plate_min_gap_ms,
        ocr_model=payload.ocr_model, condition_analysis_enabled=payload.condition_analysis_enabled,
        condition_vlm_model=payload.condition_vlm_model,
        condition_max_frames=payload.condition_max_frames,
    )
    config.validate()
    return config


def _safe_media(run: dict, relative: str) -> Path:
    if not run.get("run_dir"):
        raise HTTPException(409, "Run chưa có artifact")
    root = Path(run["run_dir"]).resolve()
    path = (root / relative).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "Không tìm thấy media")
    return path


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/settings")
def get_settings():
    return SettingsPayload.model_validate(storage.get_settings() or {}).model_dump()


@app.put("/api/settings")
def save_settings(payload: SettingsPayload):
    return storage.save_settings(payload.model_dump())


@app.get("/api/dashboard")
def dashboard():
    return {**storage.dashboard(), "recent_runs": storage.list_runs()[:6],
            "recent_videos": storage.list_videos()[:6]}


@app.get("/api/videos")
def videos():
    return storage.list_videos()


@app.post("/api/videos", status_code=201)
def upload_video(data: bytes = Body(..., media_type="application/octet-stream"),
                 x_filename: str = Header(..., alias="X-Filename")):
    filename = Path(unquote(x_filename)).name
    if not filename or Path(filename).suffix.lower() not in {".mp4", ".avi", ".mov", ".mkv"}:
        raise HTTPException(400, "Chỉ hỗ trợ mp4, avi, mov hoặc mkv")
    if not data:
        raise HTTPException(400, "Video rỗng")
    temp_id = re.sub(r"[^A-Za-z0-9_.-]", "_", filename)
    target_dir = storage.uploads / f"tmp-{os.urandom(6).hex()}"
    target_dir.mkdir(parents=True)
    target = target_dir / temp_id
    target.write_bytes(data)
    try:
        metadata = video_info(target)
        record = storage.create_video(filename, target, len(data), metadata)
        final_dir = storage.uploads / record["id"]
        final_dir.mkdir()
        final_path = final_dir / temp_id
        target.replace(final_path)
        target_dir.rmdir()
        with storage.connect() as db:
            db.execute("UPDATE videos SET stored_path=? WHERE id=?", (str(final_path), record["id"]))
        return storage.get_video(record["id"])
    except Exception as exc:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise HTTPException(400, f"Video không hợp lệ: {exc}") from exc


@app.delete("/api/videos/{video_id}")
def delete_video(video_id: str):
    try:
        value = storage.delete_video(video_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not value:
        raise HTTPException(404, "Không tìm thấy video")
    parent = Path(value["stored_path"]).parent
    if parent.parent == storage.uploads:
        shutil.rmtree(parent, ignore_errors=True)
    return {"deleted": video_id}


@app.get("/api/videos/{video_id}/media")
def video_media(video_id: str):
    return FileResponse(_video(video_id)["stored_path"])


@app.get("/api/videos/{video_id}/frame")
def video_frame(video_id: str, timestamp_ms: int = Query(0, ge=0)):
    video = _video(video_id)
    capture = cv2.VideoCapture(video["stored_path"])
    capture.set(cv2.CAP_PROP_POS_MSEC, timestamp_ms)
    ok, frame = capture.read()
    capture.release()
    if not ok:
        raise HTTPException(422, "Không đọc được frame tại timestamp này")
    encoded, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not encoded:
        raise HTTPException(500, "Không mã hóa được frame")
    return Response(buffer.tobytes(), media_type="image/jpeg")


@app.post("/api/configs/validate")
def validate_config(payload: RunPayload):
    try:
        _config(payload, storage.runs / "validation")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"valid": True}


@app.get("/api/runs")
def runs():
    return storage.list_runs()


@app.post("/api/runs", status_code=202)
def create_run(payload: RunPayload):
    try:
        config = _config(payload, storage.runs)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    record = storage.create_run(payload.video_id, payload.model_dump())
    jobs.submit(record["id"], config)
    return record


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str):
    return _run(run_id)


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str):
    run = _run(run_id)
    if run["status"] not in {"COMPLETED", "FAILED", "CANCELLED"}:
        raise HTTPException(409, "Run đang chờ hoặc đang xử lý, chưa thể xóa")
    if run.get("run_dir"):
        artifact_root = Path(run["run_dir"])
        runs_root = storage.runs.resolve()
        if artifact_root.is_symlink() or artifact_root.resolve().parent != runs_root:
            raise HTTPException(409, "Thư mục artifact nằm ngoài kho run; không thể xóa an toàn")
        if artifact_root.exists():
            try:
                shutil.rmtree(artifact_root)
            except OSError as exc:
                raise HTTPException(500, f"Không xóa được artifact của run: {exc}") from exc
    try:
        storage.delete_run(run_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"deleted": run_id}


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    run = _run(run_id)
    if run["status"] not in {"QUEUED", "RUNNING"}:
        raise HTTPException(409, "Run không còn chạy")
    if not jobs.cancel(run_id):
        raise HTTPException(409, "Run không còn chạy")
    return {"status": "cancelling"}


def _jsonl_optional(path: Path) -> list[dict]:
    return load_jsonl(path) if path.is_file() else []


@app.get("/api/runs/{run_id}/result")
def run_result(run_id: str):
    run = _run(run_id)
    if run["status"] != "COMPLETED":
        raise HTTPException(409, "Run chưa hoàn thành")
    root = Path(run["run_dir"])
    manifest = json.loads((root / "run.json").read_text(encoding="utf-8"))
    clips = _jsonl_optional(root / "clips.jsonl")
    clip_by_id = {clip["clip_id"]: clip for clip in clips}
    plates = {item["event_id"]: item for item in _jsonl_optional(root / "plate_observations.jsonl")}
    conditions = {item["event_id"]: item for item in _jsonl_optional(root / "condition_suggestions.jsonl")}
    annotations = storage.annotations(run_id)
    events = []
    for event in _jsonl_optional(root / "events.jsonl"):
        plate = plates.get(event["event_id"], {})
        condition = conditions.get(event["event_id"], {})
        cv_samples = condition.get("cv_metrics") or []
        cv_clean_fraction = (sum(not sample.get("suggested_conditions") for sample in cv_samples)
                             / len(cv_samples)) if cv_samples else None
        consensus = plate.get("consensus") or {}
        suggestion = {
            "plate_text": consensus.get("text"),
            "plate_consensus_confidence": consensus.get("confidence"),
            "plate_support_count": consensus.get("support_count"),
            "plate_analyzed": bool(plate),
            "plate_readable": condition.get("plate_readable"),
            "condition_status": condition.get("condition_status"),
            "conditions": condition.get("conditions", []),
            "condition_analyzed": bool(condition),
            "vlm_readable": condition.get("vlm_readable"),
            "cv_clean_fraction": cv_clean_fraction,
        }
        events.append({**event, "clip": clip_by_id.get(event.get("clip_id")),
                       "plate_observations": plate.get("observations", []),
                       "suggestion": suggestion, "annotation": annotations.get(event["event_id"])})
    source_by_id = {event["event_id"]: event for event in events}
    gt_events = []
    for row in annotations.values():
        source = source_by_id.get(row.get("source_event_id") or row["event_id"], {})
        camera = run["config"]["camera"]
        if not row.get("is_valid_event", True):
            continue
        gt_events.append({**row,
                          "source_event_id": row.get("source_event_id", row["event_id"] if source else None),
                          "camera_id": row.get("camera_id", source.get("camera_id", camera["camera_id"])),
                          "lane_id": row.get("lane_id", source.get("lane_id", camera["lane_id"])),
                          "direction": row.get("direction", source.get("direction", camera["direction"]))})
    gt_events.sort(key=lambda row: (row["start_ms"], row["event_id"]))
    return {"run": run, "manifest": manifest, "clips": clips, "events": events,
            "gt_events": gt_events,
            "video_duration_ms": _video(run["video_id"])["duration_ms"],
            "final_clip": manifest.get("artifacts", {}).get("final_clip")}


@app.get("/api/runs/{run_id}/detections")
def detections(run_id: str, start_ms: int = Query(0, ge=0), end_ms: int = Query(2_147_483_647, ge=0)):
    run = _run(run_id)
    records = _jsonl_optional(Path(run["run_dir"]) / "detections.jsonl") if run.get("run_dir") else []
    return [item for item in records if start_ms <= item["timestamp_ms"] <= end_ms]


@app.get("/api/runs/{run_id}/events/{event_id}/best-frame")
def event_best_frame(run_id: str, event_id: str, start_ms: int = Query(ge=0),
                     end_ms: int = Query(ge=0)):
    run = _run(run_id)
    if run["status"] != "COMPLETED":
        raise HTTPException(409, "Run chưa hoàn thành")
    if end_ms < start_ms:
        raise HTTPException(422, "Khoảng event không hợp lệ")
    root = Path(run["run_dir"])
    events = {item["event_id"]: item for item in _jsonl_optional(root / "events.jsonl")}
    event = events.get(event_id)
    if event is None and not re.fullmatch(r"GT-\d{6}", event_id):
        raise HTTPException(404, "Event không thuộc run")
    plate = next((item for item in _jsonl_optional(root / "plate_observations.jsonl")
                  if item["event_id"] == event_id), None)
    records = [item for item in _jsonl_optional(root / "detections.jsonl")
               if start_ms <= item["timestamp_ms"] <= end_ms]
    timestamp_ms, _, _ = _best_frame(event, start_ms, end_ms, plate, records)
    return {"timestamp_ms": timestamp_ms}


@app.get("/api/runs/{run_id}/media/{relative:path}")
def run_media(run_id: str, relative: str, preview: bool = False):
    run = _run(run_id)
    source = _safe_media(run, relative)
    try:
        path = browser_compatible_mp4(source, Path(run["run_dir"]).resolve()) if preview else source
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return FileResponse(path)


@app.post("/api/runs/{run_id}/export.xlsx")
def export_review_excel(run_id: str, payload: list[AnnotationPayload]):
    run = _run(run_id)
    if run["status"] != "COMPLETED":
        raise HTTPException(409, "Run chưa hoàn thành")
    root = Path(run["run_dir"])
    events = _jsonl_optional(root / "events.jsonl")
    known = {event["event_id"] for event in events}
    if any(row.event_id not in known and not re.fullmatch(r"GT-\d{6}", row.event_id)
           for row in payload):
        raise HTTPException(422, "Danh sách chứa event không thuộc run")
    if len({row.event_id for row in payload}) != len(payload):
        raise HTTPException(422, "Event ID bị trùng")
    video = _video(run["video_id"])
    try:
        content = make_review_workbook(
            {**run, "video_path": video["stored_path"]},
            [row.model_dump() for row in payload if row.is_valid_event], events)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{run_id}-ground-truth.xlsx"'})


@app.put("/api/runs/{run_id}/annotations")
def save_annotations(run_id: str, payload: list[AnnotationPayload]):
    run = _run(run_id)
    if run["status"] != "COMPLETED":
        raise HTTPException(409, "Chỉ có thể gán nhãn run đã hoàn thành")
    root = Path(run["run_dir"])
    source_events = {item["event_id"]: item for item in load_jsonl(root / "events.jsonl")}
    ids = [item.event_id for item in payload]
    if len(ids) != len(set(ids)):
        raise HTTPException(400, "GT ID bị trùng")
    video = _video(run["video_id"])
    records = []
    for item in payload:
        source_id = item.source_event_id or (item.event_id if item.event_id in source_events else None)
        if source_id and source_id not in source_events:
            raise HTTPException(400, f"Event nguồn không thuộc run: {source_id}")
        if not source_id and not re.fullmatch(r"GT-\d{6}", item.event_id):
            raise HTTPException(400, f"GT ID thủ công không hợp lệ: {item.event_id}")
        if not source_id and not item.is_valid_event:
            raise HTTPException(400, "GT thủ công không thể là event bị loại")
        if source_id and item.event_id != source_id:
            raise HTTPException(400, "GT gắn với event nguồn phải dùng ID event nguồn")
        if item.start_ms < 0 or item.start_ms >= item.end_ms or item.end_ms > video["duration_ms"] + 1000:
            raise HTTPException(400, f"Thời gian không hợp lệ: {item.event_id}")
        if item.is_valid_event and item.vehicle_type == "bicycle" and (item.plate_text is not None or
                                                item.plate_readable is not None or
                                                item.condition_status != "not_applicable" or item.conditions):
            raise HTTPException(400, "Xe đạp phải có biển số/điều kiện ở trạng thái not_applicable")
        if item.is_valid_event and item.vehicle_type != "bicycle" and item.condition_status == "not_applicable":
            raise HTTPException(400, "Xe có biển số cần trạng thái good hoặc unreadable")
        if item.is_valid_event and item.condition_status == "good" and item.conditions:
            raise HTTPException(400, "Trạng thái good không được có điều kiện lỗi")
        if item.is_valid_event and item.condition_status == "unreadable" and not item.conditions:
            raise HTTPException(400, "Trạng thái unreadable cần ít nhất một nguyên nhân")
        source = source_events.get(source_id, {})
        camera = run["config"]["camera"]
        record = {**item.model_dump(exclude={"source_event_id"}), "annotation_schema_version": "0.9.0",
                  "gt_event_id": f"GT-{item.event_id}" if source_id else item.event_id,
                  "source_event_id": source_id,
                  "camera_id": source.get("camera_id", camera["camera_id"]),
                  "lane_id": source.get("lane_id", camera["lane_id"]),
                  "direction": source.get("direction", camera["direction"]),
                  "annotation_source": "human", "updated_at": utc_now()}
        records.append(record)
    if run["review_status"] == "REVIEWED":
        previous = storage.annotations(run_id)
        unchanged = len(previous) == len(records) and all(
            row["event_id"] in previous and
            AnnotationPayload.model_validate(previous[row["event_id"]]).model_dump() ==
            AnnotationPayload.model_validate(row).model_dump()
            for row in records
        )
        if unchanged:
            return {"saved": 0, "annotation_count": len(records), "review_status": "REVIEWED"}
    next_review_status = "DRAFT" if run["review_status"] == "REVIEWED" else None
    storage.replace_annotations(run_id, records, review_status=next_review_status)
    save_jsonl(root / "ground_truth.jsonl", [row for row in records if row["is_valid_event"]])
    return {"saved": len(payload), "annotation_count": len(records),
            "review_status": next_review_status or run["review_status"]}


@app.post("/api/runs/{run_id}/review")
def review_run(run_id: str):
    run = _run(run_id)
    if run["status"] != "COMPLETED":
        raise HTTPException(409, "Run chưa hoàn thành")
    annotations = storage.annotations(run_id)
    source_ids = {row.get("source_event_id") for row in annotations.values()}
    if any(item["event_id"] not in source_ids for item in load_jsonl(Path(run["run_dir"]) / "events.jsonl")):
        raise HTTPException(409, "Cần cập nhật tất cả event trước khi duyệt")
    storage.update_run(run_id, review_status="REVIEWED")
    return storage.get_run(run_id)


@app.get("/api/runs/{run_id}/evaluation")
def run_evaluation(run_id: str):
    run = _run(run_id)
    if run["status"] != "COMPLETED" or run["review_status"] != "REVIEWED":
        raise HTTPException(409, "Chỉ đánh giá run đã duyệt")
    result = run_result(run_id)
    root = Path(run["run_dir"])
    runtime_path = root / "runtime.json"
    if runtime_path.is_file():
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    else:
        manifest = result["manifest"]
        seconds = manifest.get("elapsed_seconds")
        runtime = {"scope": "step1_core_only", "elapsed_seconds": seconds,
                   "schema_version": "0.2.0"} if isinstance(seconds, (int, float)) else {
            "scope": "unavailable", "elapsed_seconds": None,
            "schema_version": "0.2.0"}
    runtime["core_elapsed_seconds"] = runtime.get("core_elapsed_seconds", result["manifest"].get("elapsed_seconds"))
    runtime.setdefault("ocr_elapsed_seconds", None)
    runtime.setdefault("condition_elapsed_seconds", None)
    runtime["raw_duration_seconds"] = result["video_duration_ms"] / 1000
    total_seconds = runtime.get("elapsed_seconds") if runtime.get("scope") == "full_pipeline" else None
    runtime["total_to_raw_ratio"] = (total_seconds / runtime["raw_duration_seconds"]
                                     if isinstance(total_seconds, (int, float)) and runtime["raw_duration_seconds"] > 0
                                     else None)
    # Processing cost excludes loading weights into memory, while the original
    # elapsed fields remain wall-clock measurements for diagnostics.
    stages = (("core", "detector_load_seconds"),
              ("ocr", "model_load_seconds"),
              ("condition", "model_load_seconds"))
    loads = []
    for stage, load_key in stages:
        elapsed = runtime.get(f"{stage}_elapsed_seconds")
        profile = runtime.get(f"{stage}_profile_seconds")
        load = profile.get(load_key) if isinstance(profile, dict) else None
        processing = (round(max(0.0, elapsed - load), 3)
                      if isinstance(elapsed, (int, float)) and isinstance(load, (int, float))
                      and 0 <= load <= elapsed else None)
        runtime[f"{stage}_processing_seconds"] = processing
        if elapsed is not None:
            loads.append(load if processing is not None else None)
    runtime["total_processing_seconds"] = (
        round(max(0.0, total_seconds - sum(loads)), 3)
        if isinstance(total_seconds, (int, float)) and loads and all(load is not None for load in loads)
        else None)
    processing_total = runtime["total_processing_seconds"]
    runtime["processing_to_raw_ratio"] = (
        processing_total / runtime["raw_duration_seconds"]
        if processing_total is not None and runtime["raw_duration_seconds"] > 0 else None)
    evaluation_settings = get_settings()["evaluation"]
    return {"run": run, "runtime": runtime, "metrics": evaluate_review(
        result["gt_events"], result["events"], result["clips"], result["video_duration_ms"],
        **evaluation_settings,
        ocr_available=(root / "plate_observations.jsonl").is_file(),
        conditions_available=(root / "condition_suggestions.jsonl").is_file())}


@app.post("/api/runs/{run_id}/reopen")
def reopen_run(run_id: str):
    _run(run_id)
    storage.update_run(run_id, review_status="DRAFT")
    return storage.get_run(run_id)


FRONTEND_DIST = ROOT / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
