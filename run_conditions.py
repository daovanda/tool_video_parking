"""Generate CV + VLM condition suggestions for an existing Step 1 run."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from parking_step1.config import RunConfig
from parking_step1.conditions import run_condition_analysis


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Condition suggestions for an existing run")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--vlm-model", default="models/Qwen3-VL-2B-Instruct")
    parser.add_argument("--max-frames", type=int, default=3)
    args = parser.parse_args()
    run = json.loads((args.run_dir / "run.json").read_text(encoding="utf-8"))
    config = RunConfig.from_dict(run["config"])
    config.condition_vlm_model = args.vlm_model
    config.condition_max_frames = args.max_frames
    config.validate()
    records = run_condition_analysis(args.run_dir, config,
                                     progress=lambda n, m: print(f"{n}% {m}", flush=True))
    print(f"Đã ghi {len(records)} event vào {args.run_dir / 'condition_suggestions.jsonl'}")


if __name__ == "__main__":
    main()
