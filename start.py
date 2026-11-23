"""Khởi động toàn bộ EduAgent bằng một lệnh và báo tình trạng từng phần.

Cách dùng: nhấp đúp start.bat (Windows), hoặc
    .venv\\Scripts\\python.exe start.py            kiểm tra, sửa những gì thiếu, chạy web
    .venv\\Scripts\\python.exe start.py --check    chỉ kiểm tra và báo tình trạng, không chạy web
    .venv\\Scripts\\python.exe start.py --train    train lại mô hình OULAD và mô hình Agent trước khi chạy (vài phút)

Các bước:
  1. Thư viện Python      thiếu thì cài từ requirements.txt
  2. File backend/.env    chưa có thì chép từ .env.example
  3. MySQL                chưa chạy thì tự bật MySQL của XAMPP
  4. CSDL eduagent_v2     chưa có thì import database/schema_v2.sql; chưa có dữ liệu thì sinh dữ liệu demo
  5. Mô hình              mô hình thử nghiệm (dữ liệu giả lập) thiếu thì train; báo tình trạng dữ liệu và mô hình OULAD
  6. AI Agent             mô hình Agent thiếu thì train; Agent chưa chạy kỳ này thì chạy lần đầu
  7. Backend + giao diện  chạy uvicorn ở cổng 8000, mở trình duyệt. Nhấn Ctrl+C để dừng.
"""

import argparse
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
ML = ROOT / "ml"
PY = sys.executable

REQUIRED_MODULES = ["fastapi", "uvicorn", "sqlalchemy", "pymysql", "pydantic_settings", "jwt", "sklearn", "pandas",
                    "joblib"]
XAMPP_CANDIDATES = [r"C:\xampp", r"D:\xampp", r"D:\Program\XAMPP", r"C:\Program Files\xampp", r"E:\xampp"]

# Bật màu ANSI trên cửa sổ dòng lệnh Windows
os.system("")
GREEN, YELLOW, RED, BOLD, DIM, RESET = "\033[92m", "\033[93m", "\033[91m", "\033[1m", "\033[2m", "\033[0m"

status: list[tuple[str, str, str]] = []  # (mức, tên, chi tiết)


def report(level: str, name: str, detail: str = "") -> None:
    icon = {"ok": f"{GREEN}[ OK ]", "fix": f"{YELLOW}[SỬA ]", "warn": f"{YELLOW}[ !! ]",
            "err": f"{RED}[LỖI ]"}[level]
    print(f"{icon}{RESET} {name:<22} {DIM}{detail}{RESET}")
    status.append((level, name, detail))


def step(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")


def run(args: list, **kwargs) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONWARNINGS": "ignore::UserWarning"}
    return subprocess.run([str(a) for a in args], cwd=ROOT, env=env, **kwargs)


def port_open(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def wait_until(check, seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if check():
            return True
        time.sleep(0.5)
    return False


# ---------------------------------------------------------------- 1. Thư viện
def check_packages() -> bool:
    step("1. Thư viện Python")
    missing = [m for m in REQUIRED_MODULES if importlib.util.find_spec(m) is None]
    if missing:
        report("fix", "Thư viện", f"thiếu {', '.join(missing)} -> đang cài...")
        result = run([PY, "-m", "pip", "install", "-q", "-r", ML / "requirements.txt", "-r",
                      BACKEND / "requirements.txt"])
        if result.returncode != 0:
            report("err", "Thư viện", "cài thất bại, xem lỗi pip ở trên")
            return False
    report("ok", "Thư viện", f"Python {sys.version.split()[0]}")
    return True


# ---------------------------------------------------------------- 2. .env
def load_settings():
    step("2. Cấu hình")
    env_file, example = BACKEND / ".env", BACKEND / ".env.example"
    if not env_file.exists():
        shutil.copy(example, env_file)
        report("fix", "backend/.env", "chưa có -> đã chép từ .env.example")
    ensure_jwt_secret(env_file)
    sys.path.insert(0, str(BACKEND))
    from app.config import settings  # noqa: E402  (đọc .env sau khi chắc chắn file đã có)
    report("ok", "backend/.env", f"MySQL {settings.db_user}@{settings.db_host}:{settings.db_port}/{settings.db_name_v2}")
    return settings


def ensure_jwt_secret(env_file: Path) -> None:
    """Khóa ký token đăng nhập: mỗi máy tự sinh một chuỗi ngẫu nhiên, lưu trong backend/.env (không lên Git)."""
    import re
    import secrets

    text = env_file.read_text(encoding="utf-8")
    match = re.search(r"^JWT_SECRET=(.*)$", text, flags=re.MULTILINE)
    if match and match.group(1).strip():
        report("ok", "Khóa đăng nhập", "JWT_SECRET đã có")
        return
    line = f"JWT_SECRET={secrets.token_urlsafe(48)}"
    text = text.replace(match.group(0), line) if match else text.rstrip("\n") + f"\n\n{line}\n"
    env_file.write_text(text, encoding="utf-8")
    report("fix", "Khóa đăng nhập", "chưa có JWT_SECRET -> đã tạo ngẫu nhiên trong backend/.env")


# ---------------------------------------------------------------- 3. MySQL
def find_xampp(settings) -> Path | None:
    candidates = [settings.xampp_dir] if settings.xampp_dir else XAMPP_CANDIDATES
    for c in candidates:
        if c and (Path(c) / "mysql" / "bin" / "mysqld.exe").exists():
            return Path(c)
    return None


def ensure_mysql(settings) -> Path | None:
    step("3. MySQL")
    xampp = find_xampp(settings)
    if port_open(settings.db_host, settings.db_port):
        report("ok", "MySQL", f"đang chạy ở cổng {settings.db_port}")
        return xampp
    if xampp is None:
        report("err", "MySQL", "chưa chạy và không tìm thấy XAMPP. Bật MySQL trong XAMPP Control Panel, "
                               "hoặc ghi XAMPP_DIR trong backend/.env")
        return None

    report("fix", "MySQL", f"chưa chạy -> đang bật MySQL của XAMPP ({xampp})...")
    bin_dir = xampp / "mysql" / "bin"
    # Giống mysql_start.bat của XAMPP, nhưng chạy nền để không chiếm cửa sổ này
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    subprocess.Popen(
        [str(bin_dir / "mysqld.exe"), f"--defaults-file={bin_dir / 'my.ini'}", "--standalone"],
        cwd=xampp, creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if wait_until(lambda: port_open(settings.db_host, settings.db_port), 30):
        report("ok", "MySQL", "đã bật (vẫn chạy nền sau khi đóng cửa sổ này; tắt bằng XAMPP Control Panel)")
    else:
        report("err", "MySQL", f"bật không thành công sau 30 giây. Xem log: {xampp / 'mysql' / 'data' / 'mysql_error.log'}")
    return xampp


# ---------------------------------------------------------------- 4. CSDL
def connect(settings, database: str | None = None):
    import pymysql
    return pymysql.connect(host=settings.db_host, port=settings.db_port, user=settings.db_user,
                           password=settings.db_password, database=database, charset="utf8mb4")


def import_schema(settings, xampp: Path | None, filename: str = "schema_v2.sql") -> bool:
    """Import một file SQL bằng trình mysql.exe của XAMPP (xử lý đúng chú thích, dấu ; trong chuỗi...)."""
    client = shutil.which("mysql") or (xampp and xampp / "mysql" / "bin" / "mysql.exe")
    if not client or not Path(client).exists():
        report("err", "CSDL", f"không tìm thấy mysql.exe để import. Import database/{filename} bằng phpMyAdmin")
        return False
    args = [client, "-h", settings.db_host, "-P", settings.db_port, "-u", settings.db_user,
            "--default-character-set=utf8mb4"]
    env_pwd = {"MYSQL_PWD": settings.db_password} if settings.db_password else {}
    with open(ROOT / "database" / filename, "rb") as sql:
        result = subprocess.run([str(a) for a in args], stdin=sql, capture_output=True,
                                env={**os.environ, **env_pwd})
    if result.returncode != 0:
        report("err", "CSDL", f"import {filename} lỗi: " + result.stderr.decode("utf-8", "replace").strip()[:200])
        return False
    return True


def database_exists(settings, name: str) -> bool:
    with connect(settings) as conn, conn.cursor() as cur:
        cur.execute("SHOW DATABASES LIKE %s", (name,))
        return cur.fetchone() is not None


def ensure_database(settings, xampp: Path | None) -> bool:
    """CSDL eduagent_v2 theo cấu trúc Đại Nam: lớp học phần, đầu điểm, điểm danh từng buổi, AI Agent."""
    step("4. Cơ sở dữ liệu")
    name = settings.db_name_v2
    try:
        exists = database_exists(settings, name)
    except Exception as exc:
        report("err", "CSDL", f"không đăng nhập được MySQL: {exc}")
        return False
    if not exists:
        report("fix", "CSDL v2", f"chưa có '{name}' -> đang import database/schema_v2.sql...")
        if not import_schema(settings, xampp, "schema_v2.sql"):
            return False
    with connect(settings, name) as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM users")
        has_data = cur.fetchone()[0] > 0
    if not has_data:
        report("fix", "CSDL v2", "chưa có dữ liệu -> đang sinh dữ liệu demo (khoảng 10 giây)...")
        result = run([PY, ROOT / "database" / "seed_demo_v2.py"], capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0:
            report("err", "CSDL v2", (result.stderr or result.stdout).strip().splitlines()[-1][:200])
            return False
    with connect(settings, name) as conn, conn.cursor() as cur:
        cur.execute("""SELECT (SELECT COUNT(*) FROM students), (SELECT COUNT(*) FROM lecturers),
                              (SELECT COUNT(*) FROM enrollments),
                              (SELECT name FROM semesters WHERE is_current = 1 LIMIT 1)""")
        n_students, n_lecturers, n_enrollments, current = cur.fetchone()
    report("ok", "CSDL (Đại Nam)", f"'{name}': {n_students} SV, {n_lecturers} GV, {n_enrollments} lượt học; "
                                   f"kỳ hiện tại: {current}")
    return True


# ---------------------------------------------------------------- 5. Mô hình
def ensure_models(train_oulad: bool) -> None:
    step("5. Mô hình AI")
    # Thử nghiệm 4 mô hình trên dữ liệu giả lập (ml/train.py): hiện ở trang So sánh mô hình
    synthetic = ML / "data" / "synthetic" / "students_synthetic.csv"
    metrics_file = ML / "models" / "metrics.json"
    if not metrics_file.exists():
        report("fix", "Mô hình thử nghiệm", "chưa có -> đang sinh dữ liệu giả lập và train (khoảng 1 phút)...")
        if not synthetic.exists():
            run([PY, ML / "scripts" / "generate_synthetic_data.py"], capture_output=True)
        run([PY, ML / "train.py", "--note", "tạo bởi start.py"], capture_output=True)
    if metrics_file.exists():
        metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
        report("ok", "Mô hình thử nghiệm", f"{metrics.get('best_model', '?')} (dữ liệu giả lập, trang So sánh mô hình)")
    else:
        report("warn", "Mô hình thử nghiệm", "train thất bại. Chạy tay: python ml/train.py")

    oulad_raw = ML / "data" / "public" / "oulad" / "studentInfo.csv"
    oulad_features = ML / "data" / "processed" / "oulad_M1.csv"
    results = ML / "models" / "oulad" / "results.json"
    if not oulad_raw.exists():
        report("warn", "Dữ liệu OULAD", "chưa tải (~450 MB). Chạy: python ml/scripts/download_oulad.py")
        return
    report("ok", "Dữ liệu OULAD", "đã tải")

    if train_oulad or not oulad_features.exists():
        report("fix", "Đặc trưng OULAD", "đang tạo (khoảng 30 giây)...")
        run([PY, ML / "adapters" / "oulad.py"], capture_output=True)
    if train_oulad or not results.exists():
        report("fix", "Mô hình OULAD", "đang train M0/M1/M2 (vài phút)...")
        run([PY, ML / "train_checkpoints.py", "--note", "tạo bởi start.py"])

    if results.exists():
        r = json.loads(results.read_text(encoding="utf-8"))
        parts = []
        for cp, c in r["checkpoints"].items():
            fs = c["feature_sets"][c["deploy_feature_set"]]
            parts.append(f"{cp} PR-AUC {fs['models'][fs['best_model']]['test']['pr_auc']:.2f}")
        report("ok", "Mô hình OULAD", f"{', '.join(parts)} (train lúc {r['trained_at'][:16].replace('T', ' ')})")
    else:
        report("err", "Mô hình OULAD", "train thất bại. Chạy tay: python ml/train_checkpoints.py")


# ---------------------------------------------------------------- 6. AI Agent
def ensure_agent(retrain: bool, db_ok: bool, settings) -> None:
    step("6. AI Agent")
    if not db_ok:
        report("warn", "AI Agent", "bỏ qua vì chưa có CSDL")
        return
    model_dir = ML / "models" / "dainam"
    if retrain or not all((model_dir / f"model_{cp}.joblib").exists() for cp in ("M0", "M1", "M2")):
        report("fix", "Mô hình Agent", "chưa có -> đang train trên các học kỳ đã kết thúc của CSDL v2 (khoảng 30 giây)...")
        result = run([PY, ML / "train_dainam.py"], capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0:
            report("err", "Mô hình Agent", (result.stderr or result.stdout).strip().splitlines()[-1][:200])
            return
    b = json.loads((model_dir / "results.json").read_text(encoding="utf-8"))["checkpoints"]["M1"]["backtest"]
    report("ok", "Mô hình Agent", f"kiểm chứng kỳ {b['semester']} tại M1: AI bắt {b['ai']['caught']} / báo nhầm "
                                  f"{b['ai']['false_alarms']}, luật bắt {b['rule']['caught']} / báo nhầm "
                                  f"{b['rule']['false_alarms']}")

    result = run([PY, BACKEND / "scripts" / "run_agent.py", "--bootstrap"], capture_output=True, text=True,
                 encoding="utf-8")
    if result.returncode != 0:
        report("err", "AI Agent", (result.stderr or result.stdout).strip().splitlines()[-1][:200])
        return
    if "bỏ qua" not in result.stdout:
        report("fix", "AI Agent", "chưa chạy kỳ này -> đã chạy lần đầu (đầu kỳ và hôm nay)")
    with connect(settings, settings.db_name_v2) as conn, conn.cursor() as cur:
        cur.execute("SELECT as_of, message FROM agent_runs WHERE status = 'success' ORDER BY as_of DESC LIMIT 1")
        as_of, message = cur.fetchone()
    report("ok", "AI Agent", f"lần chạy gần nhất (dữ liệu tới {as_of:%d/%m %H:%M}): {message}")


# ---------------------------------------------------------------- 7. Backend
def health(port: int) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def start_backend(port: int, open_browser: bool, reload: bool) -> None:
    step("7. Backend + giao diện")
    url = f"http://127.0.0.1:{port}"
    proc = None
    if port_open("127.0.0.1", port):
        # Backend chạy sẵn có thể đang tự nạp lại sau khi sửa code: chờ một lúc trước khi kết luận cổng bị chiếm.
        if not wait_until(lambda: health(port) is not None, 20):
            report("err", "Backend", f"cổng {port} đang bị chương trình khác dùng. Thử: start.bat --port 8001")
            summary()
            return
        report("ok", "Backend", f"đã chạy sẵn ở {url} (dùng lại)")
    else:
        args = [PY, "-m", "uvicorn", "app.main:app", "--app-dir", BACKEND, "--port", port]
        if reload:
            args += ["--reload", "--reload-dir", BACKEND]
        proc = subprocess.Popen([str(a) for a in args], cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        if not wait_until(lambda: health(port) is not None, 40):
            report("err", "Backend", "không khởi động được, xem lỗi uvicorn ở trên")
            proc.terminate()
            summary()
            return
        report("ok", "Backend", f"đang chạy ở {url}")

    h = health(port) or {}
    model = h.get("model", {})
    report("ok" if h.get("database") == "ok" else "err", "API /api/health",
           f"CSDL: {h.get('database')}, mô hình: {model.get('name', model.get('error', '?'))}")
    summary(url)
    if open_browser:
        # Mở thẳng trang đăng nhập (đã đăng nhập thì trang này tự chuyển về trang chính của vai trò).
        # Tham số v= là địa chỉ mới mỗi lần, nên trình duyệt không lấy trang cũ trong bộ nhớ đệm.
        webbrowser.open(f"{url}/login.html?v={int(time.time())}")
    if proc:
        print(f"{DIM}Nhật ký backend hiện bên dưới. Nhấn Ctrl+C để dừng.{RESET}\n")
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            print("\nĐã dừng backend. (MySQL vẫn chạy, tắt bằng XAMPP Control Panel nếu muốn.)")


def summary(url: str | None = None) -> None:
    errors = [s for s in status if s[0] == "err"]
    warns = [s for s in status if s[0] == "warn"]
    print(f"\n{BOLD}{'=' * 64}{RESET}")
    if errors:
        print(f"{RED}{BOLD}Có {len(errors)} lỗi cần xử lý:{RESET}")
        for _, name, detail in errors:
            print(f"  - {name}: {detail}")
    else:
        print(f"{GREEN}{BOLD}Mọi thành phần đều sẵn sàng.{RESET}"
              + (f" {YELLOW}({len(warns)} lưu ý){RESET}" if warns else ""))
    if url:
        print(f"  Giao diện       {url}")
        print(f"  Thử API         {url}/docs")
        print(f"  So sánh mô hình {url}/models.html")
    print(f"{BOLD}{'=' * 64}{RESET}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        # line_buffering: in ngay từng dòng, kể cả khi đầu ra bị chuyển hướng
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="chỉ kiểm tra tình trạng, không chạy backend")
    parser.add_argument("--train", action="store_true", help="train lại mô hình OULAD và mô hình Agent")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="không tự mở trình duyệt")
    parser.add_argument("--no-reload", action="store_true", help="không tự nạp lại khi sửa code backend")
    args = parser.parse_args()

    print(f"{BOLD}EduAgent - Hệ thống cảnh báo sớm học tập{RESET}  {DIM}{ROOT}{RESET}")
    if not check_packages():
        return summary()
    settings = load_settings()
    xampp = ensure_mysql(settings)
    db_ok = port_open(settings.db_host, settings.db_port) and ensure_database(settings, xampp)
    ensure_models(args.train)
    ensure_agent(args.train, db_ok, settings)

    if args.check:
        return summary()
    start_backend(args.port, not args.no_browser, not args.no_reload)


if __name__ == "__main__":
    main()
