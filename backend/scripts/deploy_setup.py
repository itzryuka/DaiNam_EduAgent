"""Chuẩn bị CSDL và mô hình khi chạy trên máy chủ (Render + TiDB Cloud), không cần XAMPP hay mysql.exe.

    python backend/scripts/deploy_setup.py

Render gọi script này ở bước Build (xem render.yaml, docs/deploy-render.md). Chạy lại nhiều lần vẫn an toàn,
mỗi bước chỉ làm khi còn thiếu, nên dữ liệu đã nhập trên web (điểm, điểm danh, lần chạy Agent) được giữ nguyên:
  1. Tạo CSDL DB_NAME_V2 và các bảng từ database/schema_v2.sql
  2. Sinh dữ liệu demo nếu CSDL chưa có tài khoản nào (database/seed_demo_v2.py)
  3. Train mô hình Agent 3 mốc (ml/train_dainam.py) và mô hình thử nghiệm của trang So sánh mô hình (ml/train.py)
  4. Chạy Agent lần đầu cho học kỳ hiện tại nếu chưa chạy (backend/scripts/run_agent.py --bootstrap)
"""

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pymysql  # noqa: E402

from app.config import settings  # noqa: E402

PY = sys.executable


def log(msg: str) -> None:
    print(f"[deploy_setup] {msg}", flush=True)


def run(*args) -> None:
    started = time.time()
    subprocess.run([PY, *map(str, args)], cwd=ROOT, check=True)
    log(f"  xong sau {time.time() - started:.0f} giây")


def split_sql(sql: str) -> list[str]:
    """Tách file SQL thành từng câu: bỏ chú thích '--' và '/* */', tách ở dấu ; nằm ngoài chuỗi."""
    out, buf, quote, i = [], [], None, 0
    while i < len(sql):
        ch = sql[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and i + 1 < len(sql):
                buf.append(sql[i + 1])
                i += 1
            elif ch == quote:
                quote = None
        elif ch in "'\"`":
            quote = ch
            buf.append(ch)
        elif sql.startswith("--", i):
            end = sql.find("\n", i)
            i = len(sql) if end < 0 else end
            continue
        elif sql.startswith("/*", i):
            end = sql.find("*/", i)
            i = len(sql) if end < 0 else end + 2
            continue
        elif ch == ";":
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    out.append("".join(buf).strip())
    return [s for s in out if s]


def ensure_schema() -> None:
    name = settings.db_name_v2
    with pymysql.connect(**settings.pymysql_kwargs()) as conn, conn.cursor() as cur:
        cur.execute("SELECT VERSION()")
        version = cur.fetchone()[0]
        tidb = "tidb" in version.lower()
        log(f"Kết nối {settings.db_host}:{settings.db_port} được ({'TiDB' if tidb else 'MySQL/MariaDB'} {version})")
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        cur.execute(f"USE `{name}`")
        cur.execute("SHOW TABLES LIKE 'users'")
        if cur.fetchone():
            log(f"1. CSDL '{name}' đã có bảng, bỏ qua")
            return
        log(f"1. Tạo bảng trong '{name}' từ database/schema_v2.sql")
        n = 0
        for stmt in split_sql((ROOT / "database" / "schema_v2.sql").read_text(encoding="utf-8")):
            head = stmt.upper()
            if head.startswith(("CREATE DATABASE", "USE ")):
                continue  # đã tạo / chọn CSDL theo DB_NAME_V2 ở trên
            if tidb and head.startswith("CREATE TABLE"):
                # TiDB cấp id tự tăng theo từng lô, không theo thứ tự; =1 để id tăng dần như MySQL
                # (Agent và các trang lấy "lần chạy mới nhất" theo id lớn nhất)
                stmt += " AUTO_ID_CACHE=1"
            cur.execute(stmt)
            n += 1
        conn.commit()
        log(f"  đã chạy {n} câu lệnh")


def ensure_data() -> None:
    from app.database_v2 import migrate_v2
    migrate_v2()
    with pymysql.connect(**settings.pymysql_kwargs(settings.db_name_v2)) as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM users")
        if cur.fetchone()[0]:
            log("2. Đã có dữ liệu, giữ nguyên (đổi mã sinh viên demo dạng cũ SVkkxxxx nếu còn)")
            run(ROOT / "database" / "migrate_student_codes.py", "--apply")
            return
    log("2. CSDL trống -> sinh dữ liệu demo")
    run(ROOT / "database" / "seed_demo_v2.py")


def ensure_models() -> None:
    from app.agent import models_ready
    if models_ready():
        log("3. Đã có mô hình Agent, bỏ qua")
    else:
        log("3. Train mô hình Agent 3 mốc trên các học kỳ đã kết thúc")
        run(ROOT / "ml" / "train_dainam.py")
    metrics = settings.models_dir / "metrics.json"
    if metrics.exists():
        return
    log("   Train mô hình thử nghiệm cho trang So sánh mô hình (dữ liệu giả lập)")
    data = ROOT / "ml" / "data" / "synthetic" / "students_synthetic.csv"
    try:
        if not data.exists():
            run(ROOT / "ml" / "scripts" / "generate_synthetic_data.py", "--out", data)
        run(ROOT / "ml" / "train.py", "--data", data, "--out-dir", settings.models_dir, "--note", "deploy")
    except subprocess.CalledProcessError:
        log("   Lỗi, bỏ qua: trang So sánh mô hình sẽ báo chưa có kết quả, các phần khác vẫn chạy")


def main() -> None:
    started = time.time()
    ensure_schema()
    ensure_data()
    ensure_models()
    log("4. Chạy Agent lần đầu cho học kỳ hiện tại (bỏ qua nếu đã chạy)")
    run(ROOT / "backend" / "scripts" / "run_agent.py", "--bootstrap")
    log(f"Hoàn tất sau {time.time() - started:.0f} giây")


if __name__ == "__main__":
    main()
