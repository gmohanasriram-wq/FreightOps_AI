"""Convenience runner for FreightOps AI FastAPI backend."""
import sys
from pathlib import Path

# Ensure repository root is on sys.path
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import uvicorn
from backend.app.core.config import settings

if __name__ == "__main__":
    print(f"Starting {settings.PROJECT_NAME} on http://127.0.0.1:8000...")
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000, log_level="info")
