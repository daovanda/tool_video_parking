"""Enrich an existing Step 1 run with plate detection and OCR."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from parking_step1.config import RunConfig
from parking_step1.plate import run_plate_enrichment


def main() -> None:
    parser = argparse.ArgumentParser(description="Plate detection + OCR for an existing run")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--plate-model")
    parser.add_argument("--ocr-model")
    args = parser.parse_args()
    run = json.loads((args.run_dir / "run.json").read_text(encoding="utf-8"))
    config = RunConfig.from_dict(run["config"])
    if args.plate_model:
        config.plate_model = args.plate_model
    if args.ocr_model:
        config.ocr_model = args.ocr_model
    records = run_plate_enrichment(args.run_dir, config, progress=lambda n, m: print(f"{n}% {m}"))
    print(f"Đã ghi {len(records)} event vào {args.run_dir / 'plate_observations.jsonl'}")


if __name__ == "__main__":
    main()
