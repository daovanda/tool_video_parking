"""Command line entry point for the offline Step 1 runner.

The GUI is useful for drawing a region and reviewing results.  This module is
the reproducible counterpart for batch runs and CI smoke tests.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .batch import BatchConfig, run_batch
from .config import CameraConfig, RunConfig
from .pipeline import run_pipeline


def _points(value: str, expected: int | None = None) -> list[list[float]]:
    """Parse ``x,y;x,y`` normalized points used by ROI and crossing line."""
    if not value:
        return []
    points: list[list[float]] = []
    for raw_point in value.split(";"):
        parts = raw_point.split(",")
        if len(parts) != 2:
            raise argparse.ArgumentTypeError("Điểm phải có dạng x,y;x,y")
        try:
            points.append([float(parts[0]), float(parts[1])])
        except ValueError as exc:
            raise argparse.ArgumentTypeError("Tọa độ phải là số") from exc
    if expected is not None and len(points) != expected:
        raise argparse.ArgumentTypeError(f"Cần đúng {expected} điểm")
    return points


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parking Video Tool - Step 1")
    config_group = parser.add_mutually_exclusive_group()
    config_group.add_argument("--config", help="Đọc RunConfig từ JSON thay cho các tham số rời")
    config_group.add_argument("--batch-config", help="Đọc danh sách nhiều RunConfig từ JSON")
    parser.add_argument("--source", help="Video raw đầu vào")
    parser.add_argument("--output", help="Thư mục lưu run")
    parser.add_argument("--camera-id", default="camera-1")
    parser.add_argument("--lane-id", default="lane-1")
    parser.add_argument("--direction", choices=("ENTRY", "EXIT"), default="ENTRY")
    parser.add_argument("--model", default="yolo26s.pt")
    parser.add_argument("--imgsz", type=int, default=960, help="Kích thước cạnh ảnh đưa vào detector")
    parser.add_argument("--sample-fps", type=float, default=10.0)
    parser.add_argument("--conf", type=float, default=0.12)
    parser.add_argument("--candidate-hits", type=int, default=2)
    parser.add_argument("--min-motion-distance", type=float, default=0.015,
                        help="Dịch chuyển anchor tối thiểu, chuẩn hóa theo kích thước frame")
    parser.add_argument("--motion-window-seconds", type=float, default=1.5,
                        help="Cửa sổ thời gian xác nhận xe đang di chuyển")
    parser.add_argument("--line-gate-margin", type=float, default=0.12,
                        help="Bán kính corridor mở event quanh line; có ROI thì lấy phần giao")
    parser.add_argument("--grace-seconds", type=float, default=1.5)
    parser.add_argument("--pre-seconds", type=float, default=1.5)
    parser.add_argument("--post-seconds", type=float, default=2.0)
    parser.add_argument("--merge-gap-seconds", type=float, default=0.5)
    parser.add_argument("--roi", type=_points, default=[], help="ROI chuẩn hóa: x,y;x,y;x,y")
    parser.add_argument("--crossing-line", type=lambda v: _points(v, 2), default=[],
                        help="Đường cắt chuẩn hóa: x,y;x,y")
    parser.add_argument("--no-clips", action="store_true",
                        help="Chỉ ghi manifest segment ảo; không xuất từng MP4 và clip_final.mp4")
    parser.add_argument("--plate-ocr", action="store_true", help="Phát hiện và OCR biển số sau bước 1")
    parser.add_argument("--plate-model", default="yolov8n-oiv7.pt")
    parser.add_argument("--ocr-model", default="latin_PP-OCRv5_mobile_rec")
    parser.add_argument("--conditions", action="store_true", help="Gợi ý điều kiện bằng CV + Qwen3-VL")
    parser.add_argument("--vlm-model", default="models/Qwen3-VL-2B-Instruct")
    parser.add_argument("--condition-max-frames", type=int, default=3)
    parser.add_argument("--print-json", action="store_true", help="In run.json ra stdout")
    return parser


def _config_from_args(args: argparse.Namespace) -> RunConfig:
    if args.config:
        return RunConfig.load(args.config)
    if not args.source or not args.output:
        raise SystemExit("Cần --source và --output, hoặc dùng --config")
    return RunConfig(
        camera=CameraConfig(args.camera_id, args.lane_id, args.direction, args.roi, args.crossing_line),
        source=args.source,
        output_dir=args.output,
        model=args.model,
        image_size=args.imgsz,
        sample_fps=args.sample_fps,
        confidence=args.conf,
        candidate_hits=args.candidate_hits,
        min_motion_distance=args.min_motion_distance,
        motion_window_seconds=args.motion_window_seconds,
        line_gate_margin=args.line_gate_margin,
        grace_seconds=args.grace_seconds,
        pre_seconds=args.pre_seconds,
        post_seconds=args.post_seconds,
        merge_gap_seconds=args.merge_gap_seconds,
        make_clips=not args.no_clips,
        plate_ocr_enabled=args.plate_ocr, plate_model=args.plate_model, ocr_model=args.ocr_model,
        condition_analysis_enabled=args.conditions, condition_vlm_model=args.vlm_model,
        condition_max_frames=args.condition_max_frames,
    )


def main(argv: list[str] | None = None) -> int:
    # Windows consoles may default to cp1252, while labels and errors are
    # Vietnamese.  UTF-8 keeps CLI help and progress readable in every shell.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    if args.batch_config:
        batch = BatchConfig.load(args.batch_config)

        def batch_progress(percent: int, message: str) -> None:
            print(f"[{percent:3d}%] {message}", flush=True)

        result = run_batch(batch, progress=batch_progress)
        print(json.dumps({key: result[key] for key in ("run_count", "event_count", "clip_count")},
                         ensure_ascii=False, indent=2))
        return 0
    config = _config_from_args(args)

    def progress(percent: int, message: str) -> None:
        print(f"[{percent:3d}%] {message}", flush=True)

    result = run_pipeline(config, progress=progress)
    summary = {
        "run_dir": result["run_dir"],
        "event_count": result["run"]["event_count"],
        "clip_count": result["run"]["clip_count"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.print_json:
        print(Path(result["run_dir"], "run.json").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
