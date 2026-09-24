"""Launch the PyQt6 local interface without setting PYTHONPATH manually."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from parking_step1.gui import main


if __name__ == "__main__":
    raise SystemExit(main())
