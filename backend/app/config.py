import os
import ssl
from pathlib import Path
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Cấu hình đọc từ backend/.env (xem .env.example)."""

    # extra="ignore": file .env cũ còn dòng DB_NAME (CSDL prototype đã gỡ) vẫn chạy được
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""
    # CSDL theo cấu trúc Đại Nam: tài khoản 3 vai trò, lớp học phần, điểm, điểm danh, AI Agent
    db_name_v2: str = "eduagent_v2"
    # Kết nối mã hoá: bật khi CSDL đặt trên mây (TiDB Cloud bắt buộc). Máy cài XAMPP để False.
    db_ssl: bool = False
    db_ssl_ca: str = ""  # đường dẫn chứng chỉ CA; bỏ trống thì dùng chứng chỉ có sẵn của hệ điều hành

    # Đăng nhập JWT. JWT_SECRET phải là chuỗi ngẫu nhiên dài; start.py tự tạo vào .env nếu chưa có.
    jwt_secret: str = ""
    jwt_expire_minutes: int = 480  # 8 giờ, hết hạn thì đăng nhập lại
    # Thư mục cài XAMPP, để start.py tự bật MySQL nếu chưa chạy. Bỏ trống thì tự dò các vị trí thường gặp.
    xampp_dir: str = ""

    # Gửi email cảnh báo. Bỏ trống SMTP_HOST thì thư được lưu thành file .eml trong backend/outbox (chế độ thử).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""  # Gmail: dùng Mật khẩu ứng dụng (App Password), không dùng mật khẩu đăng nhập
    smtp_ssl: bool = False  # True khi dùng cổng 465; cổng 587 dùng STARTTLS
    # Gửi qua API HTTPS của Brevo (dùng trên Render: gói miễn phí chặn cổng SMTP). Có khóa thì ưu tiên hơn SMTP.
    # MAIL_FROM phải là địa chỉ đã xác nhận trong Brevo > Senders.
    brevo_api_key: str = ""
    mail_from: str = ""  # bỏ trống thì dùng SMTP_USER
    mail_from_name: str = "EduAgent - Cảnh báo học tập"
    # Khi thử nghiệm: mọi email được chuyển tới địa chỉ này thay vì người nhận thật
    mail_redirect_to: str = ""
    app_base_url: str = os.environ.get("RENDER_EXTERNAL_URL", "http://127.0.0.1:8000")
    outbox_dir: Path = BACKEND_DIR / "outbox"

    models_dir: Path = REPO_ROOT / "ml" / "models"

    frontend_dir: Path = REPO_ROOT / "frontend"
    # Cho phép giao diện mở bằng Live Server (cổng 5500) gọi sang API
    cors_origins: list[str] = ["http://127.0.0.1:5500", "http://localhost:5500"]

    def _url(self, name: str) -> str:
        return (
            f"mysql+pymysql://{self.db_user}:{quote_plus(self.db_password)}"
            f"@{self.db_host}:{self.db_port}/{name}?charset=utf8mb4"
        )

    @property
    def database_url_v2(self) -> str:
        return self._url(self.db_name_v2)

    @property
    def connect_args(self) -> dict:
        """Tham số thêm cho PyMySQL: kết nối TLS có kiểm tra chứng chỉ khi DB_SSL=true."""
        if not self.db_ssl:
            return {}
        return {"ssl": ssl.create_default_context(cafile=self.db_ssl_ca or None)}

    def pymysql_kwargs(self, database: str | None = None) -> dict:
        """Dùng cho pymysql.connect(**...) ở các script (start.py, seed, deploy_setup)."""
        return dict(host=self.db_host, port=self.db_port, user=self.db_user, password=self.db_password,
                    database=database, charset="utf8mb4", **self.connect_args)


settings = Settings()
