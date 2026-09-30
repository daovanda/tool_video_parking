from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from typing import Callable

import cv2

from .config import RunConfig
from .events import Detection, EventEngine, plan_segments
from .motion_gate import MotionGate


SCHEMA_VERSION = "0.10.0"
COCO_VEHICLE_CLASSES = {1: "bicycle", 2: "car", 3: "motorcycle"}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def video_info(path: str | Path) -> dict:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Không mở được video: {path}")
    info = {
        "fps": float(capture.get(cv2.CAP_PROP_FPS)),
        "frame_count": int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),
        "width": int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    }
    capture.release()
    if info["fps"] <= 0 or info["frame_count"] <= 0 or info["width"] <= 0 or info["height"] <= 0:
        raise RuntimeError("Metadata video không hợp lệ hoặc file rỗng")
    info["duration_ms"] = round(info["frame_count"] * 1000 / info["fps"])
    return info


class YoloByteTrack:
    """Ultralytics adapter. The engine consumes plain Detection objects."""

    def __init__(self, model_name: str, image_size: int, confidence: float):
        config_dir = Path(__file__).resolve().parents[2] / ".cache" / "ultralytics"
        config_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("YOLO_CONFIG_DIR", str(config_dir))
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("Cần cài ultralytics: pip install -r requirements.txt") from exc
        model_path = Path(model_name)
        if not model_path.is_absolute() and not model_path.is_file():
            repo_model = Path(__file__).resolve().parents[2] / model_path
            if repo_model.is_file():
                model_name = str(repo_model)
        self.model = YOLO(model_name)
        self.image_size = image_size
        self.confidence = confidence

    def infer(self, frame) -> list[Detection]:
        try:
            results = self.model.track(
                frame,
                persist=True,
                tracker="bytetrack.yaml",
                classes=list(COCO_VEHICLE_CLASSES),
                conf=self.confidence,
                imgsz=self.image_size,
                verbose=False,
            )
        except ModuleNotFoundError as exc:
            if exc.name == "lap":
                raise RuntimeError("ByteTrack cần dependency lap; chạy pip install -r requirements.txt") from exc
            raise
        boxes = results[0].boxes
        if boxes is None or boxes.id is None:
            return []
        ids = boxes.id.int().cpu().tolist()
        classes = boxes.cls.int().cpu().tolist()
        scores = boxes.conf.cpu().tolist()
        coordinates = boxes.xyxy.cpu().tolist()
        detections = []
        for track_id, cls, score, box in zip(ids, classes, scores, coordinates):
            if cls not in COCO_VEHICLE_CLASSES:
                continue
            detections.append(Detection(
                track_id=int(track_id), vehicle_type=COCO_VEHICLE_CLASSES[cls],
                confidence=float(score), box=tuple(float(x) for x in box)))
        return detections


def _ffmpeg_executable() -> str | None:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, OSError, RuntimeError):
        return shutil.which("ffmpeg")


def _run_ffmpeg(command: list[str], cancel: Callable[[], bool] | None, label: str) -> None:
    if cancel and cancel():
        raise RuntimeError(f"Đã hủy {label}")
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE, text=True)
    while True:
        try:
            _, stderr = process.communicate(timeout=0.25)
            break
        except subprocess.TimeoutExpired:
            if cancel and cancel():
                process.kill()
                process.communicate()
                raise RuntimeError(f"Đã hủy {label}")
    if process.returncode:
        raise RuntimeError(f"FFmpeg {label} thất bại: {stderr[-1000:]}")


def _clip_frame_bounds(start_ms: int, end_ms: int, info: dict) -> tuple[int, int]:
    fps = info["fps"]
    start_frame = max(0, int(start_ms * fps / 1000))
    end_frame = min(info["frame_count"], int(end_ms * fps / 1000 + 0.999999))
    if end_frame <= start_frame and start_frame < info["frame_count"]:
        end_frame = start_frame + 1
    return start_frame, end_frame


def _valid_encoded_video(path: Path, expected_frames: int, fps: float) -> bool:
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            return False
        count = round(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        actual_fps = capture.get(cv2.CAP_PROP_FPS)
        decodable, _ = capture.read()
        return decodable and count == expected_frames and abs(actual_fps - fps) < 0.01
    finally:
        capture.release()


def _matching_clip_boundaries(source: Path, clip: Path, start_frame: int,
                              end_frame: int, source_count: int) -> bool:
    """Reject a seek that silently starts or ends on an adjacent source frame."""
    output = cv2.VideoCapture(str(clip))
    original = cv2.VideoCapture(str(source))
    try:
        boundary_frames = []
        for clip_index in (0, end_frame - start_frame - 1):
            output.set(cv2.CAP_PROP_POS_FRAMES, clip_index)
            ok, frame = output.read()
            if not ok:
                return False
            boundary_frames.append(frame)
        for target, encoded in zip((start_frame, end_frame - 1), boundary_frames):
            errors = {}
            first_index = max(0, target - 1)
            original.set(cv2.CAP_PROP_POS_FRAMES, first_index)
            for source_index in range(first_index, min(source_count, target + 2)):
                ok, frame = original.read()
                if not ok:
                    return False
                errors[source_index] = cv2.mean(cv2.absdiff(encoded, frame))[:3]
            mean_errors = {index: sum(channels) / 3 for index, channels in errors.items()}
            if mean_errors[target] > min(mean_errors.values()):
                return False
        return True
    finally:
        output.release()
        original.release()


def _encode_clip_ffmpeg(source: Path, destination: Path, start_frame: int, end_frame: int,
                        fps: float, source_count: int,
                        cancel: Callable[[], bool] | None) -> bool:
    executable = _ffmpeg_executable()
    count = end_frame - start_frame
    if not executable or count <= 0:
        return False
    # Input seeking avoids decoding a long raw video from its first frame for
    # every late segment. The half-frame offset avoids rounding past the target.
    # Validate decoded boundary frames; if a codec's timestamps seek elsewhere,
    # retry by counting source frames from the beginning.
    attempts = ("seek", "full") if start_frame else ("full",)
    for mode in attempts:
        seek = max(0.0, (start_frame - 0.5) / fps)
        command = [executable, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
        if mode == "seek":
            command += ["-ss", str(seek)]
        command += ["-i", str(source), "-vf",
                    (f"setpts=N/({fps}*TB)" if mode == "seek" else
                     f"trim=start_frame={start_frame}:end_frame={end_frame},setpts=N/({fps}*TB)"),
                    "-frames:v", str(count), "-r", str(fps), "-fps_mode", "cfr", "-an",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(destination)]
        try:
            _run_ffmpeg(command, cancel, "xuất clip")
            valid = _valid_encoded_video(destination, count, fps)
            if valid and (mode == "full" or _matching_clip_boundaries(
                    source, destination, start_frame, end_frame, source_count)):
                return True
        except (RuntimeError, OSError, cv2.error):
            if cancel and cancel():
                destination.unlink(missing_ok=True)
                raise
        destination.unlink(missing_ok=True)
    return False


def materialize_clip(source: Path, destination: Path, start_ms: int, end_ms: int, info: dict,
                     cancel: Callable[[], bool] | None = None) -> dict:
    """Frame-accurate CFR clip export. Source timestamps remain in the manifest."""
    fps = info["fps"]
    start_frame, end_frame = _clip_frame_bounds(start_ms, end_ms, info)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if _encode_clip_ffmpeg(source, destination, start_frame, end_frame, fps,
                           info["frame_count"], cancel):
        return {"path": str(destination), "decodable": True, "frame_count": end_frame-start_frame,
                "actual_start_ms": round(start_frame * 1000 / fps),
                "actual_end_ms": round(end_frame * 1000 / fps),
                "sha256": file_sha256(destination), "encoder": "ffmpeg_libx264"}
    capture = cv2.VideoCapture(str(source))
    capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    writer = cv2.VideoWriter(str(destination), cv2.VideoWriter_fourcc(*"mp4v"), fps,
                             (info["width"], info["height"]))
    if not writer.isOpened():
        capture.release()
        raise RuntimeError(f"Không tạo được clip: {destination}")
    written = 0
    try:
        for _ in range(start_frame, end_frame):
            if cancel and cancel():
                raise RuntimeError("Đã hủy xuất clip")
            ok, frame = capture.read()
            if not ok:
                break
            writer.write(frame)
            written += 1
    finally:
        writer.release()
        capture.release()
    probe = cv2.VideoCapture(str(destination))
    decodable, _ = probe.read()
    probe.release()
    return {
        "path": str(destination), "decodable": bool(decodable), "frame_count": written,
        "actual_start_ms": round(start_frame * 1000 / fps),
        "actual_end_ms": round((start_frame + written) * 1000 / fps),
        "sha256": file_sha256(destination), "encoder": "opencv_mp4v",
    }


def _concat_ffmpeg_segments(ordered: list[dict], segment_files: dict[str, Path],
                            destination: Path, fps: float,
                            cancel: Callable[[], bool] | None) -> bool:
    executable = _ffmpeg_executable()
    if not executable or any(segment["clip_id"] not in segment_files for segment in ordered):
        return False
    descriptor, list_name = tempfile.mkstemp(suffix=".txt", dir=destination.parent)
    os.close(descriptor)
    list_path = Path(list_name)
    try:
        # FFmpeg concat demuxer needs its own single-quote escaping even when
        # subprocess receives the argument list without a shell.
        entries = []
        for segment in ordered:
            path = segment_files[segment["clip_id"]].resolve().as_posix()
            entries.append("file '" + path.replace("'", "'\\''") + "'\n")
        list_path.write_text("".join(entries), encoding="utf-8")
        command = [executable, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                   "-f", "concat", "-safe", "0", "-i", str(list_path),
                   "-c", "copy", "-movflags", "+faststart", str(destination)]
        try:
            _run_ffmpeg(command, cancel, "xuất clip final")
            expected = sum(int(segment["output_frame_count"]) for segment in ordered)
            if _valid_encoded_video(destination, expected, fps):
                return True
        except (RuntimeError, OSError):
            if cancel and cancel():
                destination.unlink(missing_ok=True)
                raise
        destination.unlink(missing_ok=True)
        return False
    finally:
        list_path.unlink(missing_ok=True)


def materialize_final_clip(source: Path, destination: Path, segments: list[dict], info: dict,
                           cancel: Callable[[], bool] | None = None,
                           single_clip: Path | None = None,
                           segment_files: dict[str, Path] | None = None) -> dict:
    """Join disjoint source segments in chronological order with traceable offsets."""
    ordered = sorted(segments, key=lambda item: (item["start_ms"], item["end_ms"], item["clip_id"]))
    destination.parent.mkdir(parents=True, exist_ok=True)
    if len(ordered) == 1 and single_clip is not None:
        if cancel and cancel():
            raise RuntimeError("Đã hủy xuất clip final")
        with single_clip.open("rb") as input_stream, destination.open("wb") as output_stream:
            while chunk := input_stream.read(4 * 1024 * 1024):
                if cancel and cancel():
                    raise RuntimeError("Đã hủy xuất clip final")
                output_stream.write(chunk)
        probe = cv2.VideoCapture(str(destination))
        decodable, _ = probe.read()
        probe.release()
        segment = ordered[0]
        frame_count = int(segment["output_frame_count"])
        start_frame = max(0, int(segment["start_ms"] * info["fps"] / 1000))
        duration_ms = round(frame_count * 1000 / info["fps"])
        return {
            "uri": str(destination), "sha256": segment["clip_sha256"],
            "quality_status": "valid" if decodable and frame_count else "invalid",
            "frame_count": frame_count, "duration_ms": duration_ms,
            "clip_count": 1, "timeline_mapping": [{
                "clip_id": segment["clip_id"],
                "source_start_ms": round(start_frame * 1000 / info["fps"]),
                "source_end_ms": round((start_frame + frame_count) * 1000 / info["fps"]),
                "final_start_ms": 0, "final_end_ms": duration_ms,
                "frame_count": frame_count,
            }],
        }
    if len(ordered) > 1 and segment_files and _concat_ffmpeg_segments(
            ordered, segment_files, destination, info["fps"], cancel):
        mappings = []
        written = 0
        for segment in ordered:
            start_frame, _ = _clip_frame_bounds(segment["start_ms"], segment["end_ms"], info)
            count = int(segment["output_frame_count"])
            mappings.append({
                "clip_id": segment["clip_id"],
                "source_start_ms": round(start_frame * 1000 / info["fps"]),
                "source_end_ms": round((start_frame + count) * 1000 / info["fps"]),
                "final_start_ms": round(written * 1000 / info["fps"]),
                "final_end_ms": round((written + count) * 1000 / info["fps"]),
                "frame_count": count,
            })
            written += count
        return {"uri": str(destination), "sha256": file_sha256(destination),
                "quality_status": "valid", "frame_count": written,
                "duration_ms": round(written * 1000 / info["fps"]),
                "clip_count": len(ordered), "timeline_mapping": mappings}
    writer = cv2.VideoWriter(str(destination), cv2.VideoWriter_fourcc(*"mp4v"), info["fps"],
                             (info["width"], info["height"]))
    if not writer.isOpened():
        raise RuntimeError(f"Không tạo được clip final: {destination}")
    mappings: list[dict] = []
    written = 0
    try:
        for segment in ordered:
            start_frame = max(0, int(segment["start_ms"] * info["fps"] / 1000))
            end_frame = min(info["frame_count"], int(segment["end_ms"] * info["fps"] / 1000 + 0.999999))
            if end_frame <= start_frame and start_frame < info["frame_count"]:
                end_frame = start_frame + 1
            final_start_frame = written
            capture = cv2.VideoCapture(str(source))
            capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            try:
                for _ in range(start_frame, end_frame):
                    if cancel and cancel():
                        raise RuntimeError("Đã hủy xuất clip final")
                    ok, frame = capture.read()
                    if not ok:
                        break
                    writer.write(frame)
                    written += 1
            finally:
                capture.release()
            segment_frames = written - final_start_frame
            mappings.append({
                "clip_id": segment["clip_id"],
                "source_start_ms": round(start_frame * 1000 / info["fps"]),
                "source_end_ms": round((start_frame + segment_frames) * 1000 / info["fps"]),
                "final_start_ms": round(final_start_frame * 1000 / info["fps"]),
                "final_end_ms": round(written * 1000 / info["fps"]),
                "frame_count": segment_frames,
            })
    finally:
        writer.release()
    probe = cv2.VideoCapture(str(destination))
    decodable, _ = probe.read()
    probe.release()
    return {
        "uri": str(destination), "sha256": file_sha256(destination),
        "quality_status": "valid" if decodable and written else "invalid",
        "frame_count": written, "duration_ms": round(written * 1000 / info["fps"]),
        "clip_count": len(ordered), "timeline_mapping": mappings,
    }


def run_pipeline(config: RunConfig, progress: Callable[[int, str], None] | None = None,
                 detector=None, cancel: Callable[[], bool] | None = None,
                 on_run_created: Callable[[str, Path], None] | None = None) -> dict:
    total_start_time = time.monotonic()
    core_profile: dict[str, float] = {}
    config.validate()
    source = Path(config.source).resolve()
    info = video_info(source)
    output_root = Path(config.output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("step1-%Y%m%dT%H%M%S%fZ")
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True)
    if on_run_created:
        on_run_created(run_id, run_dir)
    if cancel and cancel():
        raise RuntimeError("Đã hủy xử lý")
    phase_start = time.monotonic()
    if detector is None:
        detector = YoloByteTrack(config.model, config.image_size, config.confidence)
    core_profile["detector_load_seconds"] = time.monotonic() - phase_start
    engine = EventEngine(config.camera.roi, config.camera.crossing_line, info["width"], info["height"],
                         config.candidate_hits, round(config.grace_seconds * 1000), config.line_gate_margin,
                         config.min_motion_distance, round(config.motion_window_seconds * 1000))
    gate = (MotionGate(info["width"], info["height"], config.camera.roi,
                       input_width=config.motion_gate_width,
                       min_area_fraction=config.motion_gate_min_area_fraction,
                       warmup_ms=round(config.motion_gate_warmup_seconds * 1000),
                       hold_ms=round(config.motion_gate_hold_seconds * 1000),
                       probe_ms=round(config.motion_gate_probe_seconds * 1000),
                       sample_fps=config.sample_fps)
            if config.motion_gate_enabled else None)
    capture = cv2.VideoCapture(str(source))
    sample_interval_ms = 1000 / config.sample_fps
    next_sample_ms = 0.0
    decoded = sampled = 0
    decode_seconds = inference_seconds = event_seconds = gate_seconds = 0.0
    detector_frames = skipped_frames = 0
    gate_error = None
    detection_records: list[dict] = []
    start_time = time.monotonic()
    try:
        while True:
            if cancel and cancel():
                raise RuntimeError("Đã hủy xử lý")
            timestamp_ms = round(decoded * 1000 / info["fps"])
            is_sampled = timestamp_ms + 0.5 >= next_sample_ms
            phase_start = time.monotonic()
            if is_sampled:
                ok, frame = capture.read()
            else:
                # Advance the decoder without materializing an unused image.
                ok = capture.grab()
            decode_seconds += time.monotonic() - phase_start
            if not ok:
                break
            decoded += 1
            if not is_sampled:
                continue
            next_sample_ms += sample_interval_ms
            should_detect = True
            if gate is not None:
                phase_start = time.monotonic()
                try:
                    should_detect = gate.should_detect(frame, timestamp_ms,
                                                       has_open_track=bool(engine.open))
                except cv2.error as exc:
                    # A broken motion filter must not silently discard vehicle events.
                    gate_error = str(exc)
                    gate = None
                gate_seconds += time.monotonic() - phase_start
            phase_start = time.monotonic()
            detections = detector.infer(frame) if should_detect else []
            inference_seconds += time.monotonic() - phase_start
            detector_frames += int(should_detect)
            skipped_frames += int(not should_detect)
            detection_records.append({
                "frame_index": decoded - 1,
                "timestamp_ms": timestamp_ms,
                "detector_skipped": not should_detect,
                "detections": [
                    {
                        "track_id": det.track_id,
                        "vehicle_type": det.vehicle_type,
                        "confidence": det.confidence,
                        "box": list(det.box),
                    }
                    for det in detections
                ],
            })
            phase_start = time.monotonic()
            engine.update(timestamp_ms, detections)
            event_seconds += time.monotonic() - phase_start
            sampled += 1
            if progress and sampled % 10 == 0:
                progress(min(90, round(decoded / info["frame_count"] * 90)),
                         f"Đã đọc {decoded}/{info['frame_count']} frame; thấy {len(engine.finished)} lượt")
    finally:
        capture.release()
    events = engine.flush()
    core_profile.update({"decode_seconds": decode_seconds,
                         "motion_gate_seconds": gate_seconds,
                         "vehicle_inference_and_tracking_seconds": inference_seconds,
                         "event_update_seconds": event_seconds})
    segments = plan_segments(events, info["duration_ms"], round(config.pre_seconds * 1000),
                             round(config.post_seconds * 1000), round(config.merge_gap_seconds * 1000))
    phase_start = time.monotonic()
    source_hash = file_sha256(source)
    core_profile["source_hash_seconds"] = time.monotonic() - phase_start
    for segment in segments:
        segment.update({
            "schema_version": SCHEMA_VERSION, "run_id": run_id,
            "camera_id": config.camera.camera_id, "lane_id": config.camera.lane_id,
            "direction": config.camera.direction, "source_uri": str(source),
            "source_sha256": source_hash, "clip_uri": None, "quality_status": "virtual",
        })
    event_to_clip = {event_id: segment["clip_id"] for segment in segments for event_id in segment["event_ids"]}
    for event in events:
        event.update({
            "schema_version": SCHEMA_VERSION, "run_id": run_id,
            "clip_id": event_to_clip[event["event_id"]],
            "camera_id": config.camera.camera_id, "lane_id": config.camera.lane_id,
            "direction": config.camera.direction, "source_uri": str(source),
            "track_artifact_uri": "detections.jsonl",
        })
    phase_start = time.monotonic()
    segment_files: dict[str, Path] = {}
    ffmpeg_segments = True
    if config.make_clips:
        for index, segment in enumerate(segments, start=1):
            destination = run_dir / "clips" / f"{segment['clip_id']}.mp4"
            result = materialize_clip(source, destination, segment["start_ms"], segment["end_ms"], info,
                                      cancel=cancel)
            segment_files[segment["clip_id"]] = destination
            ffmpeg_segments = ffmpeg_segments and result["encoder"] == "ffmpeg_libx264"
            segment["clip_uri"] = str(destination.relative_to(run_dir)).replace("\\", "/")
            segment["actual_start_ms"] = result["actual_start_ms"]
            segment["actual_end_ms"] = result["actual_end_ms"]
            segment["clip_sha256"] = result["sha256"]
            segment["output_frame_count"] = result["frame_count"]
            segment["quality_status"] = "valid" if result["decodable"] and result["frame_count"] else "invalid"
            if progress:
                progress(90 + round(index / max(1, len(segments)) * 8), f"Đã xuất {index}/{len(segments)} clip")
    core_profile["segment_export_seconds"] = time.monotonic() - phase_start
    final_clip = None
    phase_start = time.monotonic()
    if config.make_clips and segments:
        destination = run_dir / "clips" / "clip_final.mp4"
        single_clip = run_dir / segments[0]["clip_uri"] if len(segments) == 1 else None
        final_clip = materialize_final_clip(source, destination, segments, info, cancel=cancel,
                                            single_clip=single_clip,
                                            segment_files=segment_files if ffmpeg_segments else None)
        final_clip["uri"] = str(destination.relative_to(run_dir)).replace("\\", "/")
        final_clip["schema_version"] = SCHEMA_VERSION
        if progress:
            progress(99, f"Đã nối {len(segments)} clip thành clip final")
    core_profile["final_export_seconds"] = time.monotonic() - phase_start
    write_jsonl(run_dir / "detections.jsonl", detection_records)
    run = {
        "schema_version": SCHEMA_VERSION, "run_id": run_id, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "config": config.to_dict(), "source": {"uri": str(source), "sha256": source_hash, **info},
        "decoded_frames": decoded, "sampled_frames": sampled, "event_count": len(events),
        "detector_frames": detector_frames,
        "motion_gate": {"enabled": config.motion_gate_enabled,
                        "skipped_frames": skipped_frames,
                        "fallback_error": gate_error},
        "clip_count": len(segments), "elapsed_seconds": round(time.monotonic() - start_time, 3),
        "timestamp_basis": "frame_index/source_fps; constant-frame-rate assumption",
        "artifacts": {"detections_uri": "detections.jsonl", "detection_record_count": len(detection_records),
                      "final_clip": final_clip},
    }
    write_jsonl(run_dir / "events.jsonl", events)
    write_jsonl(run_dir / "clips.jsonl", segments)
    (run_dir / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    core_elapsed_seconds = round(time.monotonic() - total_start_time, 3)
    plate_observations = []
    ocr_elapsed_seconds = None
    plate_profile: dict[str, float] = {}
    if cancel and cancel():
        raise RuntimeError("Đã hủy xử lý")
    if config.plate_ocr_enabled:
        from .plate import run_plate_enrichment
        branch_start_time = time.monotonic()
        plate_observations = run_plate_enrichment(run_dir, config, progress=progress, cancel=cancel,
                                                  profile=plate_profile)
        run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        ocr_elapsed_seconds = round(time.monotonic() - branch_start_time, 3)
    condition_suggestions = []
    condition_elapsed_seconds = None
    condition_profile: dict[str, float] = {}
    if cancel and cancel():
        raise RuntimeError("Đã hủy xử lý")
    if config.condition_analysis_enabled:
        from .conditions import run_condition_analysis
        branch_start_time = time.monotonic()
        condition_suggestions = run_condition_analysis(run_dir, config, progress=progress,
                                                        cancel=cancel, profile=condition_profile)
        run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        condition_elapsed_seconds = round(time.monotonic() - branch_start_time, 3)
    if cancel and cancel():
        raise RuntimeError("Đã hủy xử lý")
    (run_dir / "runtime.json").write_text(json.dumps({
        "schema_version": "0.4.0", "scope": "full_pipeline",
        "elapsed_seconds": round(time.monotonic() - total_start_time, 3),
        "core_elapsed_seconds": core_elapsed_seconds,
        "ocr_elapsed_seconds": ocr_elapsed_seconds,
        "condition_elapsed_seconds": condition_elapsed_seconds,
        "core_profile_seconds": {key: round(value, 3) for key, value in core_profile.items()},
        "ocr_profile_seconds": {key: round(value, 3) for key, value in plate_profile.items()},
        "condition_profile_seconds": {key: round(value, 3) for key, value in condition_profile.items()},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    if progress:
        progress(100, f"Xong: {len(events)} lượt, {len(segments)} clip")
    return {"run_dir": str(run_dir), "run": run, "events": events, "clips": segments,
            "final_clip": final_clip,
            "detections_path": str(run_dir / "detections.jsonl"),
            "plate_observations": plate_observations,
            "condition_suggestions": condition_suggestions}
