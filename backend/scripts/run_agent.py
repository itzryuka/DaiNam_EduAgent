"""Chạy AI Agent từ dòng lệnh (không cần mở web).

    python backend/scripts/run_agent.py              # chạy cho thời điểm hiện tại
    python backend/scripts/run_agent.py --bootstrap  # lần đầu: chạy lại tại đầu kỳ rồi chạy cho hôm nay (start.py dùng)
    python backend/scripts/run_agent.py --reset      # xóa kết quả Agent cũ (dự báo, cảnh báo, lần chạy) rồi bootstrap
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import text  # noqa: E402

from app.agent import bootstrap, run_agent, wait_for_emails  # noqa: E402
from app.database_v2 import SessionV2, migrate_v2  # noqa: E402


def show(run) -> None:
    s = run.stats or {}
    print(f"[{run.trigger_type}] tại {run.as_of:%d/%m/%Y %H:%M}: {run.message} ({s.get('duration_s', '?')} giây)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    migrate_v2()
    with SessionV2() as db:
        if args.reset:
            for table in ("alerts", "predictions", "agent_runs"):
                db.execute(text(f"DELETE FROM {table}"))
            db.commit()
            print("Đã xóa kết quả Agent cũ.")
        if args.bootstrap or args.reset:
            runs = bootstrap(db)
            if not runs:
                print("Agent đã có kết quả cho học kỳ hiện tại, bỏ qua.")
            for run in runs:
                show(run)
        else:
            show(run_agent(db, "manual"))
    wait_for_emails()


if __name__ == "__main__":
    main()
