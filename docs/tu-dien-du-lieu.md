# Từ điển dữ liệu

Các đặc trưng đầu vào của **mô hình thử nghiệm trên dữ liệu giả lập** (`ml/train.py`, trang So sánh mô hình).
Mô hình của AI Agent dùng đặc trưng tính tự động từ CSDL v2, xem `ml/adapters/dainam.py` và
[thiet-ke-he-thong.md](thiet-ke-he-thong.md) mục 6.

| Cột | Ý nghĩa | Kiểu / miền giá trị | Có được giữa kỳ? |
|---|---|---|---|
| `gpa_prev` | GPA tích lũy các học kỳ trước | 0.00 – 4.00 | Có |
| `attendance_rate` | Tỷ lệ buổi có mặt / tổng buổi đến thời điểm giữa kỳ | 0 – 1 | Có |
| `midterm_avg` | Điểm giữa kỳ trung bình các môn | 0 – 10 | Có |
| `failed_courses_prev` | Số môn từng trượt ở các kỳ trước | số nguyên ≥ 0 | Có |
| `credits_registered` | Số tín chỉ đăng ký học kỳ này | số nguyên | Có |
| `assignment_submission_rate` | Tỷ lệ bài tập đã nộp đúng hạn | 0 – 1 | Có |
| `lms_logins_per_week` | Số lần đăng nhập hệ thống học trực tuyến mỗi tuần | số nguyên ≥ 0 | Có |

Cột kết quả (chỉ dùng để tạo nhãn khi train, **không** dùng làm đầu vào):

| Cột | Ý nghĩa |
|---|---|
| `semester_gpa` | GPA cuối học kỳ (thang 4), chỉ biết sau khi kết thúc kỳ |
| `at_risk` | Nhãn: 1 nếu `semester_gpa` < 2.0, ngược lại 0 |

## Thêm đặc trưng mới

Ví dụ muốn thêm "điểm rèn luyện":
1. Thêm cột vào `ml/scripts/generate_synthetic_data.py` và vào `FEATURES` trong `ml/train.py`, train lại.
2. Với mô hình của AI Agent: thêm cách tính đặc trưng trong `ml/adapters/dainam.py` (dùng chung lúc train và lúc
   Agent chạy), rồi train lại bằng `python ml/train_dainam.py`.
