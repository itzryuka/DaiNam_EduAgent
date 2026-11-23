# Kế hoạch thực hiện đề tài

> **Cập nhật 11/2026:** thiết kế và lộ trình mới nằm ở [thiet-ke-he-thong.md](thiet-ke-he-thong.md)
> (hệ thống 3 vai trò, bài toán chính là dự báo trượt môn, huấn luyện trên dữ liệu công khai OULAD).
> File này giữ lại phần bối cảnh và hiện trạng bản prototype.

**Đề tài:** Xây dựng hệ thống cảnh báo sớm sinh viên có nguy cơ học tập yếu
**Thời gian:** 6 tháng, năm học 2026–2027

## 1. Mục tiêu

Dự đoán **ngay trong học kỳ** (từ dữ liệu giữa kỳ) những sinh viên có nguy cơ học yếu, để Cố vấn học tập can thiệp trước khi có điểm thi cuối kỳ.

Sản phẩm cần nộp:
1. Bộ dữ liệu đã tiền xử lý
2. Mô hình học máy đã train (so sánh Logistic Regression, Decision Tree, Random Forest, SVM)
3. Website gồm các chức năng: quản lý sinh viên, dự báo nguy cơ, gửi email cảnh báo tự động, thống kê trực quan
4. Báo cáo tổng kết 4 chương

## 2. Công nghệ

| Phần | Công nghệ |
|---|---|
| Học máy | Python, pandas, scikit-learn, Jupyter |
| Backend | FastAPI (Python), SQLAlchemy |
| Giao diện | HTML/CSS/JS thuần (bố cục kiểu OmniStock), Font Awesome, Chart.js |
| CSDL | MySQL (XAMPP) |
| Email | SMTP Gmail (App Password), APScheduler |
| Quản lý mã nguồn | Git + GitHub |

Lý do chọn Python cho backend: mô hình train bằng scikit-learn được backend nạp trực tiếp (`joblib.load`), không phải chuyển đổi định dạng hay dựng thêm service.

## 3. Các vấn đề cần chốt với thầy hướng dẫn

- [ ] **Nguồn dữ liệu thật:** xin Khoa dữ liệu điểm, chuyên cần các khóa trước. Bắt buộc **ẩn danh hóa** (bỏ họ tên, mã SV thật) theo Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân.
- [ ] **Định nghĩa "học yếu"** (nhãn của mô hình). Hiện tạm dùng: GPA học kỳ < 2.0 (thang 4). Phương án khác: bị cảnh báo học vụ.
- [ ] **Các đặc trưng lấy được giữa kỳ:** chuyên cần, điểm giữa kỳ, GPA tích lũy, số môn nợ, tín chỉ đăng ký, nộp bài tập, LMS. Cần xác nhận trường có những dữ liệu nào.
- [ ] **Thước đo đánh giá:** đề cương ghi Accuracy > 80%, nhưng dữ liệu mất cân bằng (học yếu chỉ khoảng 10–20%) nên Accuracy dễ gây hiểu lầm. Đề xuất bổ sung **Recall** và **F1-score** làm thước đo chính.
- [ ] **Thời điểm cảnh báo:** chạy dự báo sau tuần thứ mấy của học kỳ? Gửi email cho ai? (đã làm: sinh viên + CVHT, giảng viên bộ môn tùy chọn)

## 4. Lưu ý kỹ thuật quan trọng

1. **Data leakage:** chỉ dùng thông tin có trước khi thi cuối kỳ. Không đưa điểm thi cuối kỳ hay GPA học kỳ hiện tại vào đầu vào mô hình.
2. **Mất cân bằng lớp:** dùng `class_weight="balanced"` (đã làm trong `ml/train.py`), có thể thử thêm SMOTE (thư viện imbalanced-learn).
3. **Giải thích được kết quả:** CVHT cần biết lý do sinh viên bị cảnh báo. Dùng feature importance hoặc SHAP để chỉ ra đặc trưng ảnh hưởng nhiều nhất.
4. **Bảo mật:** mật khẩu người dùng lưu dạng băm (bcrypt). Mật khẩu MySQL và email để trong `backend/.env`, không commit.

## 5. Lộ trình

Đã thay bằng lộ trình hai mạch song song (AI và hệ thống) ở
[thiet-ke-he-thong.md, mục 9](thiet-ke-he-thong.md#9-lộ-trình-hai-mạch-song-song).

## 6. Hiện trạng (đã có trong repo)

- [x] Script sinh dữ liệu giả lập: `ml/scripts/generate_synthetic_data.py`
- [x] Script train + so sánh 4 mô hình: `ml/train.py`
- [x] Notebook khám phá dữ liệu: `ml/notebooks/01_kham_pha_du_lieu.ipynb`
- [x] Thiết kế CSDL prototype: `database/schema.sql` (đã thay bằng `schema_v2.sql`, gỡ ở giai đoạn 5)
- [x] Backend FastAPI: danh sách sinh viên, dự báo, thống kê
- [x] Giao diện: Tổng quan (dashboard), Sinh viên, Dự báo thử
- [x] Trang So sánh mô hình: chỉ số 4 mô hình, ma trận nhầm lẫn, đặc trưng quan trọng, lịch sử các lần train
- [x] Bố cục quản trị: thanh bên (menu nhóm), thanh điều hướng (tìm kiếm, thông báo, tài khoản, đăng xuất)
- [x] Tìm sinh viên theo mã/họ tên, thêm sinh viên bằng popup
- [x] Giao diện trang đăng nhập (chưa kiểm tra tài khoản)
- [x] Mô hình dự báo trượt môn theo mốc M0/M1/M2 trên OULAD, so công bằng với quy tắc (`ml/train_checkpoints.py`)
- [x] Logo và màu nhận diện Trường Đại học Đại Nam
- [x] Chạy toàn bộ hệ thống bằng một file: `start.bat`
- [x] CSDL v2 theo cấu trúc Đại Nam + dữ liệu demo: `database/schema_v2.sql`, `database/seed_demo_v2.py`
- [x] Đăng nhập JWT, phân quyền 3 vai trò, menu theo vai trò (CSDL v2)
- [x] Trang sinh viên: Kết quả học tập, Điểm danh. Trang giảng viên: Lớp học phần, Lớp chủ nhiệm. Trang admin: Tài khoản
- [x] Giảng viên nhập điểm, điểm danh trên web (kèm nhật ký sửa điểm): trang Lớp học phần, các tab Nhập điểm, Điểm danh, Nhật ký sửa điểm
- [x] Adapter Đại Nam: tính đặc trưng M0/M1/M2 từ CSDL v2 (`ml/adapters/dainam.py`), train mô hình Agent (`ml/train_dainam.py`)
- [x] AI Agent 5 tầng (quan sát, luật, mô hình, báo cáo, theo dõi), trang AI Agent, cảnh báo trong hệ thống, lời nhắc sinh viên
- [x] Kết quả OULAD (mô hình chính) trên trang So sánh mô hình
- [x] Agent chạy tự động theo lịch / khi có điểm, điểm danh mới (`backend/app/scheduler.py`)
- [x] Gửi email cảnh báo cho sinh viên và CVHT sau mỗi lần Agent chạy; mỗi tài khoản liên kết email (mã xác nhận); lịch sử gửi email
- [x] Kết quả học tập: tổng kết từng học kỳ và toàn khóa (ĐTB hệ 10 / hệ 4, tín chỉ, xếp loại, cảnh báo học tập)
- [x] Chuyển Tổng quan sang CSDL v2: nguy cơ theo lớp và theo môn, ĐTB và cảnh báo học tập qua các học kỳ, xếp loại học lực, tỷ lệ vắng theo tuần, 10 sinh viên nguy cơ cao nhất (`/api/dashboard`)
- [x] Quản lý sinh viên trên CSDL v2: thêm, sửa, đổi trạng thái, khóa tài khoản, đặt lại mật khẩu, import Excel (chạy thử trước khi ghi), hồ sơ sinh viên
- [x] Gỡ bản prototype (CSDL `eduagent`, trang Sinh viên / Dự báo thử cũ): hệ thống chỉ còn dùng CSDL v2;
  code cũ nén trong `archive/prototype.zip`
- [ ] Trang Môn học, Học kỳ, Nhật ký hệ thống (đang hiện "Sắp có" trên menu)
- [x] Giải thích lý do cảnh báo (occlusion: đặc trưng nào đẩy nguy cơ lên nhiều nhất)
- [ ] Dữ liệu thật
