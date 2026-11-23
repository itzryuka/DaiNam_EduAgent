# CSDL phiên bản 2 (`eduagent_v2`)

> File tạo bảng: [database/schema_v2.sql](../database/schema_v2.sql). Dữ liệu demo:
> [database/seed_demo_v2.py](../database/seed_demo_v2.py). Thiết kế tổng thể: [thiet-ke-he-thong.md](thiet-ke-he-thong.md).
> Đây là CSDL duy nhất của hệ thống (CSDL prototype `eduagent` đã gỡ khỏi code ở giai đoạn 5).

## Sơ đồ quan hệ

```
departments ─┬─< majors ──< classes (lớp hành chính) ──< students ──1:1── users
             │                 └── advisor_id ──> lecturers (CVHT)        │
             ├─< lecturers ──1:1── users ◄─────────────────────────────────┘ (role)
             └─< courses ──< course_components (CC, KT1, KT2, KT3, THI + trọng số)

semesters ──< course_sections (lớp học phần) >── courses, lecturers
                 ├─< section_assessments (ngày dự kiến của từng đầu điểm)
                 ├─< class_sessions (buổi học) ──< attendance (điểm danh từng buổi)
                 └─< enrollments (SV × lớp học phần) ──< grades (điểm từng đầu điểm, có ngày nhập)
                                    ├─< attendance
                                    └─< predictions (theo mốc M0/M1/M2) ──< alerts ──< interventions
agent_runs ──< predictions          grade_scale, settings, audit_logs: bảng hỗ trợ
```

## Các bảng

| Nhóm | Bảng | Ghi chú |
|---|---|---|
| Tài khoản | `users` | `role`: admin / lecturer / student. Mật khẩu băm PBKDF2 (`backend/app/security.py`). `email_verified_at`: NULL = chưa liên kết email, không nhận email cảnh báo |
| | `email_verifications` | Mã xác nhận đang chờ khi liên kết email (chỉ lưu mã băm, hết hạn 10 phút, tối đa 5 lần nhập) |
| | `audit_logs` | Ai sửa gì, lúc nào; giá trị cũ / mới dạng JSON |
| | `settings` | Ngưỡng nguy cơ, tỷ lệ vắng bị cấm thi, lịch chạy Agent, Agent tự chạy, ai nhận email cảnh báo |
| Danh mục | `departments`, `majors`, `lecturers`, `semesters` | `semesters.is_current` đánh dấu kỳ đang diễn ra |
| | `classes` | Lớp hành chính, `advisor_id` = giảng viên làm CVHT |
| | `students` | Một sinh viên thuộc một lớp hành chính |
| | `courses`, `course_components` | Trọng số **theo từng môn**; tổng trọng số một môn = 1 |
| | `grade_scale` | Quy đổi điểm 10 → chữ → điểm 4 **[cần xác nhận]** |
| Đào tạo | `course_sections` | Lớp học phần: môn × học kỳ × giảng viên |
| | `section_assessments` | Ngày dự kiến KT1, KT2... → Agent biết lớp đang ở mốc nào |
| | `enrollments` | `attempt_no` (học lại), `status` (đang học / rút / cấm thi / xong), TBCHP, điểm chữ |
| Điểm, điểm danh | `grades` | Một đầu điểm; **`entered_at`** = ngày nhập |
| | `class_sessions`, `attendance` | Điểm danh **từng buổi có ngày**: có mặt / muộn / có phép / vắng |
| AI Agent | `agent_runs`, `predictions` | Lần chạy (thời điểm dữ liệu `as_of`, số liệu 5 tầng `stats`); xác suất trượt, mức nguy cơ, nguồn phát hiện `flag_source` (luật / AI / cả hai), luật vi phạm, lý do chính |
| | `alerts`, `interventions` | Cảnh báo gửi giảng viên / CVHT / sinh viên; biện pháp can thiệp và kết quả |
| | `email_logs` | Mọi email đã gửi: mã xác nhận, bản tin cảnh báo (gắn `run_id`), thư thử; trạng thái sent / outbox / failed |

View: `v_semester_results` (tín chỉ, GPA từng kỳ của sinh viên), `v_attendance_summary` (tỷ lệ vắng
từng sinh viên × lớp học phần).

## Từ CSDL sang đặc trưng của mô hình

Đặc trưng được tính tự động từ bảng, khớp với lược đồ chung `ml/common_schema.py`:

| Đặc trưng chung | Tính từ |
|---|---|
| `prev_attempts` | `enrollments.attempt_no − 1` |
| `credit_load` | Tổng `courses.credits` sinh viên đăng ký trong kỳ |
| `course_fail_rate` | Tỷ lệ `passed = 0` của môn ở các kỳ **trước** |
| `engagement` | Tỷ lệ buổi có mặt đến mốc (`attendance`), xếp hạng trong lớp học phần |
| `process_score` | Đầu điểm không phải thi đã có đến mốc × trọng số, chuẩn hóa 0–1 (`grades`, `course_components`) |
| `submission_rate` | Số đầu điểm đã có / số đầu điểm đã đến hạn (`section_assessments`) |
| `score_trend` | KT gần nhất − KT đầu tiên |
| `recent_engagement` | Tỷ lệ có mặt 2 tuần gần nhất |
| `inactive_days` | Số ngày từ buổi có mặt gần nhất đến mốc |
| `late_rate` | Tỷ lệ buổi đi muộn (Đại Nam chưa có hạn nộp bài; dùng đi muộn thay thế) |
| Thêm, chỉ Đại Nam có | TBC tích lũy trước kỳ (`v_semester_results`), số môn từng trượt |

## Dữ liệu demo

`python database/seed_demo_v2.py --reset` sinh: 3 khóa (K17–K19), 6 lớp hành chính, 240 sinh viên, 12 giảng
viên, 27 môn, 5 học kỳ (HK1 2024-2025 → HK1 2026-2027, kỳ hiện tại chỉ có dữ liệu đến hôm nay), khoảng 4.500
lượt học, 65.000 lượt điểm danh, 15.000 đầu điểm. Tỷ lệ trượt các kỳ đã xong khoảng 14–20%, cấm thi 3–5%.

- Toàn bộ là dữ liệu giả (họ tên ghép ngẫu nhiên, mã sinh viên 10 chữ số `1871020001`, email `@example.edu.vn`, mã môn minh họa).
- Một số sinh viên được mô phỏng **sa sút giữa kỳ** (đi học ít dần, KT2 thấp hơn KT1) để thử AI Agent.
- Tài khoản: `admin`, `gv001`…`gv012`, mã sinh viên (`1771020001`…: khóa + mã ngành rút gọn + số thứ tự). Mật khẩu chung: hằng `DEMO_PASSWORD`
  trong `seed_demo_v2.py`. Chỉ dùng trên máy cá nhân.
- **Không dùng dữ liệu demo để train mô hình báo cáo trong đề tài.**
