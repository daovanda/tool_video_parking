from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import uvicorn


if __name__ == "__main__":
    uvicorn.run("parking_web.api:app", host="127.0.0.1", port=8000, reload=False, app_dir=str(ROOT / "src"))

