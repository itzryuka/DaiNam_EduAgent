"""Kết nối CSDL v2 (eduagent_v2): tài khoản 3 vai trò, lớp học phần, điểm, điểm danh, AI Agent.

Chạy được trên MariaDB/MySQL (XAMPP) và TiDB Cloud (bản deploy trên Render, DB_SSL=true).
"""

import logging
from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

# pool_recycle: CSDL trên mây tự cắt kết nối để lâu không dùng, nên làm mới kết nối sau 5 phút
engine_v2 = create_engine(settings.database_url_v2, pool_pre_ping=True, pool_recycle=300,
                          connect_args=settings.connect_args)
log = logging.getLogger(__name__)
SessionV2 = sessionmaker(bind=engine_v2, autoflush=False)

# Cột thêm sau khi CSDL đã được tạo (schema_v2.sql đã có sẵn cho máy cài mới). Chạy lại nhiều lần vẫn an toàn.
MIGRATIONS = [
    "ALTER TABLE agent_runs MODIFY trigger_type ENUM('schedule', 'grade_update', 'manual', 'replay') NOT NULL",
    "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS semester_id INT NULL AFTER trigger_type",
    "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS as_of DATETIME NULL AFTER semester_id",
    "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS started_by INT NULL AFTER as_of",
    "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS stats JSON NULL AFTER n_alerts",
    "ALTER TABLE predictions ADD COLUMN IF NOT EXISTS flag_source ENUM('none', 'rule', 'ai', 'both') "
    "NOT NULL DEFAULT 'none' AFTER risk_level",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at DATETIME NULL AFTER email",
    """CREATE TABLE IF NOT EXISTS email_verifications (
      user_id INT PRIMARY KEY, email VARCHAR(100) NOT NULL, code_hash VARCHAR(64) NOT NULL,
      attempts INT NOT NULL DEFAULT 0, expires_at DATETIME NOT NULL,
      created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS email_logs (
      id BIGINT AUTO_INCREMENT PRIMARY KEY, user_id INT NULL, to_email VARCHAR(100) NOT NULL,
      kind ENUM('verify', 'alert', 'test') NOT NULL, audience ENUM('lecturer', 'advisor', 'student') NULL,
      run_id INT NULL, n_alerts INT NOT NULL DEFAULT 0, subject VARCHAR(255) NOT NULL, body TEXT NOT NULL,
      status ENUM('sent', 'outbox', 'failed') NOT NULL, error VARCHAR(500) NULL,
      created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, INDEX idx_created (created_at),
      FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
      FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE SET NULL) ENGINE=InnoDB""",
    "INSERT IGNORE INTO settings (`key`, value, description) VALUES "
    "('agent_auto', '1', '1 = Agent tự chạy theo lịch và khi có điểm / điểm danh mới'), "
    "('agent_poll_minutes', '15', 'Bao nhiêu phút kiểm tra dữ liệu mới một lần'), "
    "('alert_email_audiences', 'student,advisor', 'Ai nhận email cảnh báo: student, advisor, lecturer')",
]


def migrate_v2() -> None:
    try:
        conn = engine_v2.connect()
    except OperationalError:
        return  # chưa có CSDL / MySQL chưa bật: start.py sẽ báo
    with conn:
        # Chạy từng câu: một câu không được hỗ trợ (vd trên TiDB) không chặn các câu sau
        for sql in MIGRATIONS:
            try:
                conn.execute(text(sql))
                conn.commit()
            except DBAPIError as exc:
                conn.rollback()
                log.warning("Bỏ qua migration (%s): %s", sql.split("(")[0][:60], exc.orig)


class BaseV2(DeclarativeBase):
    pass


def get_db_v2() -> Iterator[Session]:
    db = SessionV2()
    try:
        yield db
    finally:
        db.close()
