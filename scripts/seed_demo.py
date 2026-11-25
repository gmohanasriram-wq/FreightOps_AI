"""Seed deterministic synthetic demo data.

Usage:
    python scripts/seed_demo.py
"""
import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from backend.app.db.session import SessionLocal
from backend.app.services.demo_seed import seed_all_demo_data


def main() -> int:
    with SessionLocal() as db:
        summary = seed_all_demo_data(db)
    print(
        "Synthetic demo data ready: "
        f"{summary['carriers']} carriers, {summary['shipments']} shipments, "
        f"scoring config v{summary['scoring_config_version']}."
    )
    print("All seeded carrier and shipment records are labeled SYNTHETIC.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
