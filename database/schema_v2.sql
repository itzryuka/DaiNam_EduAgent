-- =====================================================================
-- EduAgent - CSDL phiên bản 2, theo cấu trúc đào tạo của Trường Đại học Đại Nam
-- Thiết kế: docs/thiet-ke-he-thong.md (mục 3, 4, 8). Từ điển dữ liệu: docs/csdl-v2.md
--
-- Import:  mysql -u root < database/schema_v2.sql      (hoặc phpMyAdmin > Import)
-- Dữ liệu demo:  python database/seed_demo_v2.py
--
-- Khác bản prototype (schema.sql):
--   - Ba vai trò admin / lecturer / student; giảng viên có thể kiêm cố vấn học tập (CVHT)
--   - Điểm thành phần CC, KT1, KT2, (KT3), Thi với TRỌNG SỐ THEO TỪNG MÔN, không viết cứng
--   - Lưu NGÀY nhập từng đầu điểm và điểm danh TỪNG BUỔI: mô hình cần các mốc thời gian này
--     để tính đặc trưng xu hướng (thí nghiệm OULAD lần 2 cho thấy chúng tạo ra khác biệt)
--   - Dự báo theo từng sinh viên × lớp học phần × mốc M0/M1/M2, kèm cảnh báo và can thiệp
-- Các chỗ ghi [cần xác nhận] là giả định, phải hỏi phòng đào tạo trước khi dùng thật.
-- =====================================================================

CREATE DATABASE IF NOT EXISTS eduagent_v2
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE eduagent_v2;

-- ---------------------------------------------------------------------
-- 1. Tài khoản và nhật ký
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  username      VARCHAR(50)  NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,              -- pbkdf2_sha256$vòng$salt$hash (backend/app/security.py)
  full_name     VARCHAR(100) NOT NULL,
  email         VARCHAR(100) NULL,
  email_verified_at DATETIME NULL,                 -- NULL = chưa xác nhận, không gửi email cảnh báo
  role          ENUM('admin', 'lecturer', 'student') NOT NULL,
  is_active     TINYINT(1)   NOT NULL DEFAULT 1,
  last_login_at DATETIME     NULL,
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- Ai sửa gì, lúc nào (đặc biệt là sửa điểm)
CREATE TABLE IF NOT EXISTS audit_logs (
  id         BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id    INT          NULL,
  action     VARCHAR(50)  NOT NULL,                 -- vd: grade.update, user.lock
  entity     VARCHAR(50)  NOT NULL,                 -- vd: grades
  entity_id  BIGINT       NULL,
  old_value  JSON         NULL,
  new_value  JSON         NULL,
  ip_address VARCHAR(45)  NULL,
  created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_entity (entity, entity_id),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- Cấu hình hệ thống do quản trị chỉnh (ngưỡng cảnh báo, lịch chạy Agent...)
CREATE TABLE IF NOT EXISTS settings (
  `key`       VARCHAR(50)  PRIMARY KEY,
  value       VARCHAR(255) NOT NULL,
  description VARCHAR(255) NULL,
  updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 2. Danh mục
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS departments (
  id   INT AUTO_INCREMENT PRIMARY KEY,
  code VARCHAR(20)  NOT NULL UNIQUE,                -- vd: FIT
  name VARCHAR(100) NOT NULL                        -- vd: Khoa Công nghệ thông tin
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS majors (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  department_id INT          NOT NULL,
  code          VARCHAR(20)  NOT NULL UNIQUE,       -- mã ngành, vd: 7480201
  name          VARCHAR(100) NOT NULL,
  FOREIGN KEY (department_id) REFERENCES departments(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS lecturers (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  user_id       INT          NOT NULL UNIQUE,
  lecturer_code VARCHAR(20)  NOT NULL UNIQUE,
  department_id INT          NOT NULL,
  title         VARCHAR(20)  NULL,                  -- học vị: ThS, TS, PGS.TS
  phone         VARCHAR(20)  NULL,
  FOREIGN KEY (user_id)       REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (department_id) REFERENCES departments(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS semesters (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  code       VARCHAR(20)  NOT NULL UNIQUE,          -- vd: 2026-2027.1
  name       VARCHAR(100) NOT NULL,                 -- vd: Học kỳ 1 năm học 2026-2027
  start_date DATE         NOT NULL,
  end_date   DATE         NOT NULL,
  is_current TINYINT(1)   NOT NULL DEFAULT 0
) ENGINE=InnoDB;

-- Lớp hành chính (lớp sinh hoạt), mỗi lớp có một CVHT là giảng viên
CREATE TABLE IF NOT EXISTS classes (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  code       VARCHAR(20)  NOT NULL UNIQUE,          -- vd: CNTT 18-01
  major_id   INT          NOT NULL,
  cohort     SMALLINT     NOT NULL,                 -- khóa, vd: 18
  advisor_id INT          NULL,                     -- lecturers.id
  FOREIGN KEY (major_id)   REFERENCES majors(id),
  FOREIGN KEY (advisor_id) REFERENCES lecturers(id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS students (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  user_id       INT          NULL UNIQUE,
  student_code  VARCHAR(20)  NOT NULL UNIQUE,
  full_name     VARCHAR(100) NOT NULL,
  gender        ENUM('M', 'F') NULL,
  date_of_birth DATE         NULL,
  email         VARCHAR(100) NULL,
  class_id      INT          NOT NULL,
  status        ENUM('studying', 'reserved', 'dropped', 'graduated') NOT NULL DEFAULT 'studying',
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id)  REFERENCES users(id) ON DELETE SET NULL,
  FOREIGN KEY (class_id) REFERENCES classes(id)
) ENGINE=InnoDB;

-- Môn học. Mã có quy luật: DNU (chung toàn trường), ENG (tiếng Anh), FIT (khoa CNTT)
CREATE TABLE IF NOT EXISTS courses (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  code          VARCHAR(20)  NOT NULL UNIQUE,
  name          VARCHAR(150) NOT NULL,
  credits       TINYINT UNSIGNED NOT NULL,
  department_id INT          NULL,
  course_group  ENUM('general', 'english', 'major') NOT NULL,
  FOREIGN KEY (department_id) REFERENCES departments(id)
) ENGINE=InnoDB;

-- Đầu điểm của từng môn và trọng số. Tổng trọng số một môn phải bằng 1 (backend kiểm tra).
-- Phổ biến: CC 0.10, KT1 0.15, KT2 0.15, THI 0.60 [cần xác nhận]
CREATE TABLE IF NOT EXISTS course_components (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  course_id  INT          NOT NULL,
  code       VARCHAR(10)  NOT NULL,                 -- CC, KT1, KT2, KT3, THI
  name       VARCHAR(50)  NOT NULL,
  weight     DECIMAL(4,3) NOT NULL,
  is_exam    TINYINT(1)   NOT NULL DEFAULT 0,       -- 1 = thi kết thúc học phần
  sort_order TINYINT      NOT NULL,
  UNIQUE KEY uq_course_component (course_id, code),
  CONSTRAINT chk_weight CHECK (weight > 0 AND weight <= 1),
  FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Thang quy đổi điểm 10 -> điểm chữ -> điểm 4 [cần xác nhận theo quy chế Đại Nam]
CREATE TABLE IF NOT EXISTS grade_scale (
  letter    VARCHAR(2)   PRIMARY KEY,
  min_score DECIMAL(3,1) NOT NULL,                  -- điểm 10 tối thiểu (làm tròn 1 chữ số)
  point     DECIMAL(2,1) NOT NULL,
  passed    TINYINT(1)   NOT NULL
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 3. Đào tạo
-- ---------------------------------------------------------------------
-- Lớp học phần: một môn mở trong một học kỳ, do một giảng viên dạy
CREATE TABLE IF NOT EXISTS course_sections (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  code           VARCHAR(40)  NOT NULL UNIQUE,      -- vd: FIT1003-2026.1-01
  course_id      INT          NOT NULL,
  semester_id    INT          NOT NULL,
  lecturer_id    INT          NULL,
  room           VARCHAR(20)  NULL,
  total_sessions TINYINT UNSIGNED NOT NULL DEFAULT 15,
  INDEX idx_semester (semester_id),
  FOREIGN KEY (course_id)   REFERENCES courses(id),
  FOREIGN KEY (semester_id) REFERENCES semesters(id),
  FOREIGN KEY (lecturer_id) REFERENCES lecturers(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- Lịch dự kiến của từng đầu điểm trong lớp học phần (KT1 tuần mấy, KT2 tuần mấy...).
-- Agent dùng bảng này để biết lớp đang ở mốc M0, M1 hay M2.
CREATE TABLE IF NOT EXISTS section_assessments (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  section_id   INT  NOT NULL,
  component_id INT  NOT NULL,
  planned_date DATE NOT NULL,
  UNIQUE KEY uq_section_component (section_id, component_id),
  FOREIGN KEY (section_id)   REFERENCES course_sections(id) ON DELETE CASCADE,
  FOREIGN KEY (component_id) REFERENCES course_components(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Sinh viên học một lớp học phần. Kết quả cuối (TBCHP, điểm chữ) có sau khi thi.
CREATE TABLE IF NOT EXISTS enrollments (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  section_id   INT          NOT NULL,
  student_id   INT          NOT NULL,
  attempt_no   TINYINT UNSIGNED NOT NULL DEFAULT 1, -- lần học thứ mấy (học lại = 2, 3...)
  status       ENUM('studying', 'withdrawn', 'banned_exam', 'completed') NOT NULL DEFAULT 'studying',
  final_score  DECIMAL(3,1) NULL,                   -- TBCHP thang 10
  letter_grade VARCHAR(2)   NULL,
  grade_point  DECIMAL(2,1) NULL,                   -- thang 4
  passed       TINYINT(1)   NULL,                   -- 1 nếu TBCHP >= 4.0
  completed_at DATETIME     NULL,
  UNIQUE KEY uq_section_student (section_id, student_id),
  INDEX idx_student (student_id),
  FOREIGN KEY (section_id) REFERENCES course_sections(id) ON DELETE CASCADE,
  FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
  FOREIGN KEY (letter_grade) REFERENCES grade_scale(letter)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 4. Điểm và điểm danh
-- ---------------------------------------------------------------------
-- Một đầu điểm của một sinh viên. entered_at = lúc giảng viên nhập (mốc thời gian cho mô hình).
CREATE TABLE IF NOT EXISTS grades (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  enrollment_id INT          NOT NULL,
  component_id  INT          NOT NULL,
  score         DECIMAL(3,1) NOT NULL,              -- thang 10
  entered_by    INT          NULL,                  -- users.id
  entered_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_enrollment_component (enrollment_id, component_id),
  CONSTRAINT chk_score CHECK (score >= 0 AND score <= 10),
  FOREIGN KEY (enrollment_id) REFERENCES enrollments(id) ON DELETE CASCADE,
  FOREIGN KEY (component_id)  REFERENCES course_components(id),
  FOREIGN KEY (entered_by)    REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- Buổi học của lớp học phần
CREATE TABLE IF NOT EXISTS class_sessions (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  section_id   INT          NOT NULL,
  session_no   TINYINT UNSIGNED NOT NULL,
  session_date DATE         NOT NULL,
  topic        VARCHAR(150) NULL,
  UNIQUE KEY uq_section_session (section_id, session_no),
  FOREIGN KEY (section_id) REFERENCES course_sections(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Điểm danh từng buổi. Không có dòng = chưa điểm danh buổi đó.
CREATE TABLE IF NOT EXISTS attendance (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  session_id    INT NOT NULL,
  enrollment_id INT NOT NULL,
  status        ENUM('present', 'late', 'excused', 'absent') NOT NULL,
  recorded_by   INT NULL,
  recorded_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_session_enrollment (session_id, enrollment_id),
  INDEX idx_enrollment (enrollment_id),
  FOREIGN KEY (session_id)    REFERENCES class_sessions(id) ON DELETE CASCADE,
  FOREIGN KEY (enrollment_id) REFERENCES enrollments(id) ON DELETE CASCADE,
  FOREIGN KEY (recorded_by)   REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 5. AI Agent
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_runs (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  trigger_type  ENUM('schedule', 'grade_update', 'manual', 'replay') NOT NULL,  -- replay: chạy lại tại một ngày cũ
  semester_id   INT      NULL,
  as_of         DATETIME NULL,                    -- Agent nhìn dữ liệu tính đến thời điểm này
  started_by    INT      NULL,                    -- users.id nếu chạy tay
  started_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at   DATETIME NULL,
  status        ENUM('running', 'success', 'failed') NOT NULL DEFAULT 'running',
  n_predictions INT NOT NULL DEFAULT 0,
  n_alerts      INT NOT NULL DEFAULT 0,
  stats         JSON NULL,                        -- số liệu từng tầng ① ... ⑤, trang AI Agent hiển thị
  message       TEXT NULL
) ENGINE=InnoDB;

-- Dự báo cho một sinh viên trong một lớp học phần tại một mốc. Giữ lịch sử mọi lần chạy.
CREATE TABLE IF NOT EXISTS predictions (
  id               BIGINT AUTO_INCREMENT PRIMARY KEY,
  run_id           INT          NULL,
  enrollment_id    INT          NOT NULL,
  checkpoint       ENUM('M0', 'M1', 'M2') NOT NULL,
  model_name       VARCHAR(50)  NOT NULL,
  model_version    VARCHAR(30)  NULL,               -- vd: thời điểm train
  risk_probability DECIMAL(5,4) NOT NULL,
  risk_level       ENUM('low', 'medium', 'high') NOT NULL,
  flag_source      ENUM('none', 'rule', 'ai', 'both') NOT NULL DEFAULT 'none', -- ai = AI phát hiện, luật bỏ sót
  rule_flags       JSON         NULL,               -- luật quy chế bị vi phạm, vd ["Vắng nhiều"]
  top_factors      JSON         NULL,               -- lý do chính của mô hình, hiện cho giảng viên
  min_exam_score   DECIMAL(3,1) NULL,               -- điểm thi tối thiểu cần đạt để qua môn
  created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_enrollment_time (enrollment_id, created_at),
  FOREIGN KEY (run_id)        REFERENCES agent_runs(id) ON DELETE SET NULL,
  FOREIGN KEY (enrollment_id) REFERENCES enrollments(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Cảnh báo gửi tới đúng người: giảng viên bộ môn, CVHT, sinh viên
CREATE TABLE IF NOT EXISTS alerts (
  id                BIGINT AUTO_INCREMENT PRIMARY KEY,
  prediction_id     BIGINT       NULL,
  student_id        INT          NOT NULL,
  enrollment_id     INT          NULL,              -- NULL = cảnh báo tổng hợp theo sinh viên (CVHT)
  recipient_user_id INT          NOT NULL,
  audience          ENUM('lecturer', 'advisor', 'student') NOT NULL,
  channel           ENUM('in_app', 'email') NOT NULL DEFAULT 'in_app',
  level             ENUM('info', 'warning', 'danger') NOT NULL,
  title             VARCHAR(200) NOT NULL,
  message           TEXT         NOT NULL,
  status            ENUM('pending', 'sent', 'read', 'failed') NOT NULL DEFAULT 'pending',
  created_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  sent_at           DATETIME     NULL,
  read_at           DATETIME     NULL,
  INDEX idx_recipient (recipient_user_id, status),
  FOREIGN KEY (prediction_id)     REFERENCES predictions(id) ON DELETE SET NULL,
  FOREIGN KEY (student_id)        REFERENCES students(id) ON DELETE CASCADE,
  FOREIGN KEY (enrollment_id)     REFERENCES enrollments(id) ON DELETE CASCADE,
  FOREIGN KEY (recipient_user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Giảng viên / CVHT ghi nhận đã làm gì với sinh viên, và kết quả về sau
CREATE TABLE IF NOT EXISTS interventions (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  alert_id       BIGINT       NULL,
  student_id     INT          NOT NULL,
  enrollment_id  INT          NULL,
  created_by     INT          NOT NULL,             -- users.id của giảng viên
  action_type    ENUM('meeting', 'message', 'call', 'study_plan', 'referral', 'other') NOT NULL,
  note           TEXT         NULL,
  follow_up_date DATE         NULL,
  outcome        ENUM('pending', 'improved', 'no_change', 'worse') NOT NULL DEFAULT 'pending',
  created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (alert_id)      REFERENCES alerts(id) ON DELETE SET NULL,
  FOREIGN KEY (student_id)    REFERENCES students(id) ON DELETE CASCADE,
  FOREIGN KEY (enrollment_id) REFERENCES enrollments(id) ON DELETE SET NULL,
  FOREIGN KEY (created_by)    REFERENCES users(id)
) ENGINE=InnoDB;

-- Mã xác nhận khi liên kết email (mỗi tài khoản một mã đang chờ; chỉ lưu mã băm)
CREATE TABLE IF NOT EXISTS email_verifications (
  user_id    INT          PRIMARY KEY,
  email      VARCHAR(100) NOT NULL,
  code_hash  VARCHAR(64)  NOT NULL,
  attempts   INT          NOT NULL DEFAULT 0,
  expires_at DATETIME     NOT NULL,
  created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Mọi email hệ thống gửi đi: mã xác nhận, bản tin cảnh báo sau mỗi lần Agent chạy, thư thử
CREATE TABLE IF NOT EXISTS email_logs (
  id         BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id    INT          NULL,
  to_email   VARCHAR(100) NOT NULL,                 -- địa chỉ thật đã gửi (có thể là MAIL_REDIRECT_TO khi thử)
  kind       ENUM('verify', 'alert', 'test') NOT NULL,
  audience   ENUM('lecturer', 'advisor', 'student') NULL,
  run_id     INT          NULL,                     -- lần chạy Agent sinh ra bản tin
  n_alerts   INT          NOT NULL DEFAULT 0,
  subject    VARCHAR(255) NOT NULL,
  body       TEXT         NOT NULL,                 -- nội dung dạng chữ (mã xác nhận được che)
  status     ENUM('sent', 'outbox', 'failed') NOT NULL,  -- outbox = chưa cấu hình SMTP, lưu file .eml
  error      VARCHAR(500) NULL,
  created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_created (created_at),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
  FOREIGN KEY (run_id)  REFERENCES agent_runs(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 6. View dùng chung
-- ---------------------------------------------------------------------
-- Kết quả từng học kỳ của sinh viên (chỉ tính môn đã có điểm tổng kết)
CREATE OR REPLACE VIEW v_semester_results AS
SELECT e.student_id,
       cs.semester_id,
       SUM(c.credits)                                              AS credits_attempted,
       SUM(CASE WHEN e.passed = 1 THEN c.credits ELSE 0 END)       AS credits_passed,
       ROUND(SUM(e.grade_point * c.credits) / SUM(c.credits), 2)   AS gpa4,
       ROUND(SUM(e.final_score * c.credits) / SUM(c.credits), 2)   AS gpa10
FROM enrollments e
JOIN course_sections cs ON cs.id = e.section_id
JOIN courses c          ON c.id = cs.course_id
WHERE e.final_score IS NOT NULL
GROUP BY e.student_id, cs.semester_id;

-- Tình hình chuyên cần từng sinh viên trong từng lớp học phần (tính đến buổi đã điểm danh)
CREATE OR REPLACE VIEW v_attendance_summary AS
SELECT a.enrollment_id,
       COUNT(*)                                   AS sessions_recorded,
       SUM(a.status = 'present')                  AS n_present,
       SUM(a.status = 'late')                     AS n_late,
       SUM(a.status = 'excused')                  AS n_excused,
       SUM(a.status = 'absent')                   AS n_absent,
       ROUND(SUM(a.status IN ('absent', 'excused')) / COUNT(*), 3) AS absence_rate
FROM attendance a
GROUP BY a.enrollment_id;

-- ---------------------------------------------------------------------
-- 7. Dữ liệu danh mục mặc định
-- ---------------------------------------------------------------------
INSERT IGNORE INTO grade_scale (letter, min_score, point, passed) VALUES
  ('A+', 9.0, 4.0, 1), ('A', 8.5, 3.7, 1), ('B+', 8.0, 3.5, 1), ('B', 7.0, 3.0, 1),
  ('C+', 6.5, 2.5, 1), ('C', 5.5, 2.0, 1), ('D+', 5.0, 1.5, 1), ('D', 4.0, 1.0, 1),
  ('F', 0.0, 0.0, 0);

INSERT IGNORE INTO settings (`key`, value, description) VALUES
  ('risk_threshold_medium', '0.40', 'Xác suất trượt từ mức này là nguy cơ trung bình'),
  ('risk_threshold_high',   '0.60', 'Xác suất trượt từ mức này là nguy cơ cao'),
  ('absence_ban_ratio',     '0.20', 'Vắng quá tỷ lệ này số buổi thì bị cấm thi [cần xác nhận]'),
  ('pass_score',            '4.0',  'TBCHP tối thiểu để qua môn'),
  ('agent_schedule',        'weekly:MON:07:00', 'Lịch chạy định kỳ của AI Agent'),
  ('agent_auto',            '1',    '1 = Agent tự chạy theo lịch và khi có điểm / điểm danh mới'),
  ('agent_poll_minutes',    '15',   'Bao nhiêu phút kiểm tra dữ liệu mới một lần'),
  ('alert_email_audiences', 'student,advisor', 'Ai nhận email cảnh báo: student, advisor, lecturer'),
  ('llm_enabled',           '0',    '1 = dùng LLM viết báo cáo (tùy chọn), 0 = dùng mẫu câu soạn sẵn');
