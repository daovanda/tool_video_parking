"""Launch the Step 1 CLI from a checkout."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from parking_step1.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
