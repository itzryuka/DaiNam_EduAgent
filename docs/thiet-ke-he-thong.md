# Thiết kế hệ thống EduAgent

> Phiên bản 2 (11/2026). Thay thế phần thiết kế trong bản prototype đầu tiên.
> Các mục đánh dấu **[cần xác nhận]** phải hỏi thầy hướng dẫn hoặc phòng đào tạo trước khi chốt.

## 1. Mục tiêu và phạm vi

EduAgent là **hệ thống quản lý sinh viên có AI giám sát**. Cốt lõi là một mô hình học máy được huấn luyện để
**dự báo sớm sinh viên có nguy cơ trượt môn**, để giảng viên can thiệp khi vẫn còn kịp.

| Trong phạm vi | Ngoài phạm vi |
|---|---|
| Dự báo nguy cơ **trượt từng môn** trong học kỳ (bài toán chính) | Dự báo tốt nghiệp đúng hạn (đã loại) |
| Dự báo nguy cơ **cảnh báo học tập** cuối kỳ (tổng hợp từ các môn) | Thay thế cổng thông tin đào tạo của trường |
| Quản lý lớp, điểm, điểm danh ở mức đủ để thu dữ liệu và hiển thị cảnh báo | Thanh toán học phí, đăng ký học phần |

## 2. Kiến trúc

```
[Trình duyệt: HTML/CSS/JS, bố cục kiểu OmniStock, menu theo vai trò]
        │ fetch() + JWT
        ▼
[Backend FastAPI] ──► [MySQL]
        │
        ├──► [Mô hình ML: dự báo trượt môn]     (scikit-learn, file .joblib)
        ├──► [AI Agent: chạy định kỳ / khi có điểm mới] (APScheduler)
        └──► [LLM viết báo cáo - TÙY CHỌN]        (Claude API, tắt được)
```

- Giữ **HTML + Python (FastAPI)**: nhóm đã quen, đủ cho yêu cầu, thời gian dành cho phần AI.
- **Đăng nhập JWT, phân quyền theo vai trò**: mọi API kiểm tra người gọi là ai và được xem dữ liệu nào.
- **LLM là tùy chọn**: hệ thống phải chạy đầy đủ khi tắt LLM (báo cáo dùng mẫu câu soạn sẵn). Kinh phí đề tài
  1.000.000 VNĐ nên không được phụ thuộc vào dịch vụ trả phí.

## 3. Phân quyền

Một tài khoản giảng viên có thể kiêm **cố vấn học tập (CVHT)** của một lớp hành chính.

| Quản lý hệ thống | Giảng viên | Sinh viên |
|---|---|---|
| Tài khoản, phân quyền, khóa/mở tài khoản | Danh sách lớp học phần mình dạy | Điểm từng môn, TBC học kỳ và tích lũy |
| Danh mục: khoa, ngành, môn học (kèm trọng số điểm), học kỳ, lớp hành chính, lớp học phần | **Nhập điểm thành phần** (CC, KT1, KT2, thi), nhập từ Excel | Biểu đồ kết quả qua các kỳ |
| Phân công giảng viên dạy, phân công CVHT | Điểm danh từng buổi | Tình trạng điểm danh từng môn |
| Cấu hình ngưỡng cảnh báo, lịch chạy Agent | Xem cảnh báo, báo cáo của Agent | Lời nhắc và gợi ý cải thiện (không hiện xác suất) |
| Train lại, chọn mô hình (trang So sánh mô hình) | **Ghi nhận biện pháp can thiệp** | "Điểm thi tối thiểu cần đạt để qua môn" |
| Nhật ký hệ thống (ai sửa điểm, lúc nào), sao lưu | CVHT: toàn bộ sinh viên lớp hành chính | |

## 4. Dữ liệu học tập của Trường Đại học Đại Nam

Theo bảng điểm trên cổng thông tin sinh viên (ttsinhvien.dainam.edu.vn), mỗi học phần có:

| Cột | Ý nghĩa | Có lúc nào |
|---|---|---|
| CC | Điểm chuyên cần (thang 10) | Trong kỳ |
| KT1, KT2 (một số môn có KT3, KT12) | Điểm kiểm tra thường xuyên | Trong kỳ |
| Điểm thi | Điểm thi kết thúc học phần | Cuối kỳ |
| TBCHP | Điểm tổng kết học phần (thang 10) | Cuối kỳ |
| Điểm số / Điểm chữ | Quy đổi thang 4 / chữ: A+ (4.0), A (3.7), B+ (3.5), …, C (2.0), … | Cuối kỳ |

- **Trọng số** suy ra từ bảng điểm: đa số môn **CC 10% - KT1 15% - KT2 15% - Thi 60%**; một số môn
  (ví dụ Kỹ năng mềm) dùng trọng số khác (khoảng 50% quá trình). **[cần xác nhận]**
  → Hệ thống lưu trọng số **theo từng môn học**, không viết cứng.
- **Đạt** khi điểm chữ từ D trở lên, tức **TBCHP ≥ 4,0**; **trượt** khi TBCHP < 4,0 (điểm F).
  Có điểm liệt cho bài thi không? **[cần xác nhận]**
- Mã học phần có quy luật: `DNU` (môn chung toàn trường), `ENG` (tiếng Anh), `FIT` (khoa CNTT).

## 5. Bài toán AI

### 5.1. Bài toán chính: dự báo trượt môn

- **Đơn vị dự báo:** một sinh viên trong một lớp học phần.
- **Nhãn:** `fail = 1` nếu TBCHP < 4,0.
- **Thời điểm dự báo:** theo các mốc giảng viên nhập điểm, không theo tuần:

| Mốc | Thông tin đã có | Vai trò |
|---|---|---|
| M0 - Đầu kỳ | Kết quả các kỳ trước, số tín chỉ đăng ký, nhóm môn, số lần đã học môn này | Cảnh báo sớm nhất, kém chính xác nhất |
| M1 - Sau CC + KT1 | Thêm khoảng 25% điểm học phần | Mốc can thiệp chính |
| M2 - Sau KT2 | Đủ 40% điểm quá trình | Còn kịp ôn thi |

  KT1, KT2 thường diễn ra vào tuần nào? **[cần xác nhận]**

- **Đặc trưng dự kiến:** điểm quá trình đến mốc (đã nhân trọng số, chuẩn hóa 0–1), điểm chuyên cần,
  tỷ lệ bài kiểm tra đã có điểm, TBC tích lũy trước kỳ, số môn từng trượt, số lần đã học môn này,
  tỷ lệ trượt lịch sử của môn / nhóm môn (độ khó), số tín chỉ đăng ký trong kỳ.
- **Điểm thi tối thiểu cần đạt:** ở mốc M2 tính được ngay
  `điểm thi tối thiểu = (4,0 − điểm quá trình đã nhân trọng số) / trọng số thi`.
  Ví dụ quá trình trung bình 5 → 0,4 × 5 = 2,0 → cần thi ≥ (4,0 − 2,0) / 0,6 ≈ 3,4.
  Con số này dễ hiểu với sinh viên hơn xác suất; mô hình ML ước lượng khả năng đạt được mức đó.

### 5.2. Bài toán phụ: nguy cơ cảnh báo học tập

Tổng hợp xác suất trượt các môn trong kỳ → ước lượng TBC học kỳ và số tín chỉ không đạt → so với điều kiện
cảnh báo học tập của quy chế đào tạo (Thông tư 08/2021/TT-BGDĐT và quy chế của trường). **[cần xác nhận
các ngưỡng theo quy chế Đại Nam]**

### 5.3. Đánh giá mô hình

1. **So với quy tắc đơn giản (baseline)**, ví dụ "CC < 5 hoặc trung bình KT < 4 thì cảnh báo".
   Mô hình phải tốt hơn baseline mới có lý do dùng AI. So **công bằng**: chỉnh ngưỡng của mô hình (trên kỳ
   validation) để có cùng Precision với quy tắc rồi so số sinh viên trượt bắt được; và ngược lại, cùng
   Recall rồi so số cảnh báo nhầm.
2. **Theo từng mốc** M0, M1, M2: Recall, Precision, F1, PR-AUC (PR-AUC phù hợp khi lớp "trượt" là thiểu số).
3. **Giải thích từng dự báo** bằng SHAP: chỉ ra đặc trưng nào khiến sinh viên bị cảnh báo.
4. **Chia theo thời gian**: học từ các kỳ trước, chọn mô hình / bộ đặc trưng / ngưỡng trên kỳ validation,
   kỳ test (mới nhất) chỉ dùng để báo cáo.

## 6. AI Agent

Agent bao quanh mô hình ML, chạy định kỳ (hằng tuần) và mỗi khi giảng viên nhập điểm mới:

| Tầng | Việc làm |
|---|---|
| ① Quan sát | Phát hiện dữ liệu mới (đầu điểm, buổi điểm danh), xác định lớp học phần đang ở mốc nào |
| ② Luật quy chế | Các trường hợp chắc chắn: vắng quá ngưỡng cấm thi **[cần xác nhận ngưỡng]**, điểm quá trình quá thấp |
| ③ Mô hình ML | Xác suất trượt + lý do (SHAP) cho từng sinh viên × môn |
| ④ Báo cáo | Gửi đúng người: giảng viên bộ môn (theo lớp học phần), CVHT (toàn diện theo sinh viên), sinh viên (lời nhắc + điểm thi tối thiểu). Mẫu câu soạn sẵn; LLM viết tự nhiên hơn nếu bật |
| ⑤ Theo dõi | Giảng viên xác nhận và ghi nhận can thiệp; Agent theo dõi các mốc sau xem sinh viên có cải thiện không |

Nguyên tắc:
- Agent **chỉ đề xuất**, không tự động xử lý kỷ luật hay thay đổi điểm.
- Khi gửi dữ liệu cho LLM bên ngoài: **chỉ gửi mã ẩn danh và số liệu**, không gửi họ tên
  (Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân).
- Mở rộng (nếu còn thời gian): giảng viên hỏi Agent bằng câu hỏi tự nhiên ("Lớp tôi có ai đáng lo?"),
  LLM gọi các API chỉ-đọc của hệ thống để trả lời.

### 6.1. Bản cài đặt (11/2026)

| Thành phần | File |
|---|---|
| Đặc trưng M0/M1/M2 từ CSDL v2 (dùng chung lúc train và lúc Agent chạy) | `ml/adapters/dainam.py` |
| Train mô hình Agent, chọn ngưỡng, kiểm chứng trên kỳ cũ | `ml/train_dainam.py` → `ml/models/dainam/` |
| 5 tầng của Agent | `backend/app/agent.py` |
| Chạy từ dòng lệnh / lần đầu | `backend/scripts/run_agent.py` (start.bat tự gọi) |
| API: chạy, nhật ký, danh sách, kiểm chứng, cảnh báo | `backend/app/routers/agent.py` |
| Trang AI Agent, Cảnh báo của tôi; cột "Nguy cơ trượt (AI)" ở trang giảng viên, CVHT | `frontend/agent.html`, `alerts.html`, `teaching.html`, `advising.html` |

- **Mốc của Đại Nam**: M0 = đầu kỳ (chỉ có lịch sử), M1 = lúc nhập xong KT1, M2 = lúc nhập xong KT2. Mỗi mốc một mô hình.
- **Đặc trưng**: các cột của lược đồ chung (để so được với OULAD) cộng đặc trưng chỉ Đại Nam có: TBC tích lũy,
  số môn đang nợ, **điểm kiểm tra và tỷ lệ đi học ở các môn khác cùng kỳ** (tín hiệu xuyên môn mà luật xét từng
  môn không thấy).
- **Ngưỡng**: chọn trên kỳ validation sao cho AI không báo nhầm nhiều hơn luật (cùng precision); mức "cao" khi
  precision trên validation từ 75% trở lên.
- **Lý do cảnh báo**: thay lần lượt từng đặc trưng bằng giá trị thường gặp (trung vị), đặc trưng nào làm xác suất
  giảm nhiều nhất là lý do chính (occlusion, dùng được cho mọi mô hình, không cần thư viện SHAP).
- **Nguồn phát hiện** của mỗi lượt học: `both` (luật và AI), `ai` (**AI phát hiện sớm**: chưa vi phạm luật nào),
  `rule` (luật bắt nhưng AI xếp thấp, thường là báo nhầm), `none`.
- **Báo cáo**: chỉ tạo cảnh báo khi lượt học mới cần chú ý, mức tăng lên, hoặc sang mốc mới. Đầu kỳ chỉ báo CVHT
  (giảng viên, sinh viên chỉ nhận khi nguy cơ cao). Sinh viên nhận lời nhắc, không thấy xác suất, và chỉ được nêu
  những điều tự cải thiện được (đi học, làm bài kiểm tra).
- Lần đầu chạy (start.bat), Agent chạy lại tại ngày đầu kỳ rồi chạy cho hôm nay, để tầng ⑤ có mốc so sánh.

**Kiểm chứng trên dữ liệu demo** (train 2024-2025.1 và .2, validation 2025-2026.1, chạy lại kỳ 2025-2026.2 có
193/953 lượt trượt thật):

| Mốc | Luật: bắt / báo nhầm | AI: bắt / báo nhầm | AI bắt, luật bỏ sót | Luật + AI bắt | Trước kỳ thi |
|---|---|---|---|---|---|
| M0 | 160 / 158 | 167 / 165 | 16 | 176 | – |
| M1 | 121 / 89 | **136 / 59** | **33** | 154 | khoảng 10 tuần |
| M2 | 144 / 78 | 167 / 95 | 27 | 171 | khoảng 5,6 tuần |

> Dữ liệu demo do `database/seed_demo_v2.py` sinh ra, nên bảng này chỉ chứng minh Agent chạy đúng quy trình.
> Bằng chứng về độ chính xác là kết quả trên OULAD (mục 7). Khi có dữ liệu thật của Đại Nam: nạp vào CSDL v2 rồi
> chạy lại `python ml/train_dainam.py`, không phải sửa code.

**Tự chạy và gửi email** (đã làm):

- `backend/app/scheduler.py`: luồng nền kiểm tra mỗi phút. Đến lịch `agent_schedule` mà tuần này chưa chạy thì chạy;
  mỗi `agent_poll_minutes` phút so `MAX(grades.updated_at)`, `MAX(attendance.recorded_at)` với lần chạy trước, có dữ liệu
  mới thì chạy (`trigger_type = grade_update`). Khóa một lần chạy tại một thời điểm. Không dùng APScheduler để bớt một
  thư viện phải cài.
- Người nhận: mỗi lượt học cần chú ý luôn báo cho **sinh viên** và **CVHT**; giảng viên bộ môn nhận khi đã có điểm
  (M1, M2) hoặc nguy cơ cao ở M0.
- `backend/app/notifier.py`: sau lần chạy (trừ chạy lại quá khứ), gom cảnh báo mới theo người nhận, mỗi người **một
  email** (sinh viên: các môn và việc nên làm, không có xác suất; CVHT: danh sách sinh viên kèm lý do). Chỉ gửi tới
  email đã xác nhận. Kết quả ghi `email_logs` và `agent_runs.stats.email`.
- `backend/app/mailer.py`: SMTP khi có `SMTP_HOST`, ngược lại lưu `.eml` vào `backend/outbox` (chế độ thử);
  `MAIL_REDIRECT_TO` chuyển mọi thư về một hộp thư khi thử nghiệm.

Chưa làm: ghi nhận can thiệp (bảng `interventions`).

## 7. Chiến lược dữ liệu

Chưa có dữ liệu thật → huấn luyện và xây quy trình trên **dữ liệu công khai**, khi có dữ liệu Đại Nam thì
**chạy lại cùng quy trình** để train mô hình mới. Mô hình train trên dữ liệu nước ngoài **không dùng thẳng**
cho sinh viên Đại Nam (khác cột dữ liệu, khác bối cảnh); thứ mang sang được là quy trình, lược đồ đặc trưng,
kinh nghiệm chọn thuật toán.

| Nguồn | Vai trò | Ghi chú |
|---|---|---|
| **OULAD** (Open University, Anh) | **Bộ chính** | 32.593 sinh viên, 22 lượt mở môn; điểm từng bài kiểm tra kèm ngày và trọng số, hoạt động học trực tuyến theo ngày, kết quả cuối môn. CC BY 4.0. Tải: `python ml/scripts/download_oulad.py` |
| **UCI Student Performance** (Bồ Đào Nha) | Bộ phụ, thử nghiệm chéo | Có G1, G2 (điểm quá trình), số buổi vắng, G3 (điểm cuối) |
| Dữ liệu giả lập | **Chỉ để demo** hệ thống | Họ tên tiếng Việt, lớp, điểm danh từng buổi theo cấu trúc điểm Đại Nam |
| **Dữ liệu Đại Nam** (xin qua Khoa, đã ẩn danh) | Mục tiêu cuối | Mã SV ẩn danh, mã học phần, học kỳ, số tín chỉ, CC, KT1, KT2, (KT3), điểm thi, TBCHP |

### Lược đồ đặc trưng chung

| Đặc trưng chung | Đại Nam | OULAD | UCI Student Performance |
|---|---|---|---|
| Điểm quá trình đến mốc (0–1) | CC, KT1, KT2 theo trọng số | Điểm TMA/CMA có hạn nộp trước mốc, theo trọng số | G1 (và G2 ở mốc sau) / 20 |
| Mức tham gia học tập | CC (sau này: điểm danh từng buổi) | Tổng lượt click học trực tuyến đến mốc, xếp hạng trong môn | Số buổi vắng (đảo chiều) |
| Tỷ lệ bài đã nộp | Số đầu điểm KT đã có / số đầu điểm đến mốc | Số bài đã nộp / số bài đến hạn | Không có |
| Số lần đã học môn này | Từ lịch sử điểm | `num_of_prev_attempts` | `failures` (số môn từng trượt) |
| Khối lượng học | Số tín chỉ đăng ký trong kỳ | `studied_credits` | Không có |
| *Xu hướng điểm* (bộ extended) | KT2 − KT1 | Điểm bài nộp gần nhất − bài đầu | G2 − G1 |
| *Tham gia gần đây* (bộ extended) | Điểm danh 2 tuần gần nhất | Lượt click 14 ngày gần nhất, xếp hạng | Không có |
| *Số ngày không hoạt động* (bộ extended) | Số buổi vắng liên tiếp gần nhất | Ngày cắt − ngày click cuối (tối đa 60) | Không có |
| *Tỷ lệ nộp muộn* (bộ extended) | Cần hệ thống ghi hạn nộp | Bài nộp sau hạn / bài đã nộp | Không có |
| **Nhãn trượt** | TBCHP < 4,0 | `final_result = Fail` | G3 < 10 |

Sinh viên **rút khỏi môn** (`Withdrawn` trong OULAD) xử lý riêng: loại khỏi tập chính và báo cáo như một thí
nghiệm phụ. **[nhóm thống nhất]**

### Ghi chú khi đọc OULAD (đã kiểm tra trên bản tải về 11/2026)

- 7 bảng CSV, nối với nhau qua `code_module`, `code_presentation`, `id_student`, `id_assessment`, `id_site`.
  `studentVle.csv` nặng khoảng 450 MB: đọc theo cột cần dùng hoặc theo từng phần.
- 32.593 lượt đăng ký học, 22 lượt mở môn. `final_result`: Pass 37,9% · Withdrawn 31,2% · Fail 21,6% ·
  Distinction 9,3%. Bỏ Withdrawn còn 22.437 lượt, **tỷ lệ trượt 31,4%** (Distinction tính là đạt).
- Bài kiểm tra: 106 TMA (do giảng viên chấm), 76 CMA (máy chấm), 24 Exam. Trọng số các bài không phải Exam
  thường cộng lại 100; có lượt mở môn trọng số bằng 0 → không dùng trọng số làm mẫu số mà không kiểm tra.
- **Giá trị thiếu ghi bằng dấu `?`**, phải đọc với `pd.read_csv(..., na_values="?")`. Thiếu: 11 ngày thi
  (dùng `module_presentation_length` thay thế), 173 điểm, 1.111 `imd_band`.
- Cột `date` tính bằng **số ngày kể từ khi môn bắt đầu** → dùng để cắt dữ liệu theo mốc M0/M1/M2 mà không
  rò rỉ thông tin tương lai.

### Câu hỏi nghiên cứu

1. Thuật toán nào dự báo trượt môn tốt nhất, và tốt hơn quy tắc đơn giản bao nhiêu? (OULAD)
2. Dự báo sớm đến mốc nào vẫn đủ tin cậy để can thiệp? (OULAD, nhờ có mốc thời gian của bài kiểm tra)
3. Mô hình học ở bối cảnh này dùng ở bối cảnh khác được không? (train OULAD, thử UCI qua lược đồ chung) →
   lập luận cho việc phải train lại trên dữ liệu Đại Nam.
4. Kết quả trên dữ liệu sinh viên Đại Nam (khi có dữ liệu).

### Kết quả thí nghiệm lần 1 trên OULAD (16/11/2026)

Chạy: `python ml/adapters/oulad.py` rồi `python ml/train_checkpoints.py`. Chia theo thời gian: train các kỳ
2013B, 2013J (+ 2014B sau khi chọn mô hình), chọn mô hình trên 2014B, **test trên 2014J** (7.434 lượt, 26,6%
trượt). Mô hình được chọn theo PR-AUC trên kỳ validation. Chi tiết: `ml/models/oulad/results.json`.

| Mốc | Ngày cắt TB | Mô hình chọn | Recall | Precision | F1 | PR-AUC | Baseline: Recall / Precision / F1 |
|---|---|---|---|---|---|---|---|
| M0 - Đầu kỳ | 0 | Logistic Regression | 0,64 | 0,37 | 0,47 | 0,42 | 0,50 / 0,41 / 0,45 |
| M1 - ~40% bài kiểm tra | 110 | Random Forest | 0,77 | 0,56 | 0,65 | 0,76 | 0,65 / 0,62 / 0,63 |
| M2 - Trước khi thi | 208 | Random Forest | 0,81 | 0,71 | 0,75 | 0,86 | 0,69 / 0,80 / 0,74 |

Nhận xét:
- **Càng về sau càng chính xác**: PR-AUC tăng từ 0,42 (M0) lên 0,76 (M1) và 0,86 (M2). M1 đã đủ tốt để can thiệp.
- **So với quy tắc đơn giản**: mô hình bắt được nhiều sinh viên trượt hơn (Recall +12 điểm % ở M1 và M2)
  nhưng báo nhầm nhiều hơn (Precision thấp hơn); F1 chỉ nhỉnh hơn 1–2 điểm %. Chưa đủ để kết luận AI vượt trội.
- Đặc trưng quan trọng nhất: `process_score`, rồi `submission_rate`, `engagement`. `course_fail_rate`
  gần như không có tác dụng.
- M0 yếu vì OULAD không có điểm tích lũy các kỳ trước; dữ liệu Đại Nam có TBC tích lũy nên M0 có thể tốt hơn.
- 4 mô hình mạnh (Logistic Regression, Random Forest, Gradient Boosting, Decision Tree) sát nhau; SVM chậm
  nhất (17–49 giây mỗi mốc) và kém nhất.

### Kết quả thí nghiệm lần 2: đặc trưng xu hướng + so sánh công bằng (16/11/2026)

Thêm 4 đặc trưng xu hướng (bộ **extended**, xem bảng lược đồ ở trên) và so với quy tắc ở cùng điểm làm việc:
chọn ngưỡng của mô hình **trên kỳ validation** sao cho cùng Precision (hoặc cùng Recall) với quy tắc, rồi áp
lên kỳ test. Kỳ test 2014J có 1.978 sinh viên trượt.

**1. Đặc trưng xu hướng giúp ích, rõ nhất ở PR-AUC:**

| Mốc | PR-AUC core | PR-AUC extended | F1 (ngưỡng 0,5) core → extended |
|---|---|---|---|
| M1 | 0,763 | **0,781** | 0,647 → 0,664 |
| M2 | 0,861 | **0,881** | 0,754 → 0,756 |

Ở mốc M1, tầm quan trọng chỉ sau `process_score` là `recent_engagement` và `inactive_days`. Sinh viên trượt
trung bình đã **23 ngày** không hoạt động tại M1, sinh viên đạt chỉ khoảng 2 ngày.

**2. So công bằng với quy tắc (mô hình chọn: Random Forest, bộ extended):**

| Mốc | Quy tắc: bắt / báo nhầm | Mô hình (ngưỡng tốt nhất): bắt / báo nhầm | Kết luận |
|---|---|---|---|
| M0 | 991 / 1.455 | 1.115 / 1.709 | **Không hơn**: bắt thêm thì báo nhầm tăng nhiều hơn |
| M1 | 1.276 / 800 | **1.349 / 651** | Hơn cả hai: bắt thêm 73 SV, bớt 149 cảnh báo nhầm (−19%) |
| M2 | 1.358 / 350 | **1.366 / 177** | Hơn cả hai: bắt bằng quy tắc, **bớt một nửa cảnh báo nhầm** |

Chỉ ghi "hơn" khi mô hình vừa bắt không ít hơn vừa báo nhầm không nhiều hơn quy tắc. Có các điểm làm việc
khác mang tính đánh đổi, ví dụ M1 bắt thêm 213 SV nhưng báo nhầm thêm 194.

Nhận xét:
- **Câu trả lời cho câu hỏi nghiên cứu 1**: từ mốc M1, mô hình hơn quy tắc đơn giản một cách thực chất. Ở
  M1 giảng viên vừa nhận ít cảnh báo hơn vừa bắt được nhiều sinh viên trượt hơn; ở M2 lợi ích chủ yếu là
  giảm cảnh báo nhầm (Precision 0,80 → 0,89).
- Bộ core (không có xu hướng) ở M2 **không** hơn quy tắc được; chính các đặc trưng xu hướng tạo ra khác biệt.
  → Khi thiết kế CSDL cho Đại Nam, cần lưu **điểm danh từng buổi có ngày** và **ngày nhập từng đầu điểm**,
  không chỉ lưu điểm tổng.
- **M0 chưa dùng được** để cảnh báo cá nhân trên OULAD. Chỉ nên dùng M0 để xếp ưu tiên theo dõi.
- **Ngưỡng bị lệch giữa các kỳ**: quy tắc có Precision 0,73 ở kỳ 2014B nhưng chỉ 0,62 ở kỳ 2014J, nên ngưỡng
  chọn ở kỳ trước không khớp hẳn ở kỳ sau. Khi chạy thật cần kiểm tra lại ngưỡng mỗi học kỳ (ghi vào nhiệm vụ
  của Agent).
- Ngưỡng đã chọn được lưu kèm mô hình (`thresholds` trong `ml/models/oulad/M1.joblib`, `M2.joblib`).

Việc tiếp theo:
1. Giải thích từng dự báo bằng SHAP (cho báo cáo gửi giảng viên).
2. Thử chéo trên UCI Student Performance qua lược đồ chung (câu hỏi nghiên cứu 3).
3. Hiển thị kết quả theo mốc lên trang "So sánh mô hình" của web.

## 8. CSDL

> **Đã có bản v2:** [database/schema_v2.sql](../database/schema_v2.sql) (CSDL `eduagent_v2`), dữ liệu demo
> [database/seed_demo_v2.py](../database/seed_demo_v2.py), mô tả chi tiết [csdl-v2.md](csdl-v2.md).

| Nhóm | Bảng |
|---|---|
| Tài khoản | `users` (vai trò: admin / lecturer / student), `audit_logs` |
| Danh mục | `departments`, `majors`, `courses` (kèm trọng số CC/KT/thi), `semesters`, `classes` (lớp hành chính, CVHT) |
| Đào tạo | `course_sections` (lớp học phần, giảng viên), `enrollments` (sinh viên đăng ký lớp học phần) |
| Điểm và điểm danh | `grade_components` (CC, KT1, KT2, thi theo enrollment), `class_sessions`, `attendance` |
| AI Agent | `predictions` (theo enrollment và mốc), `alerts`, `interventions`, `agent_runs` |

Đặc trưng cho mô hình được **tính tự động** từ điểm và điểm danh, không nhập tay như bảng `academic_records`
của bản prototype.

### Nhập liệu trên web (đã làm)

| Chức năng | Ai làm | Quy tắc | File |
|---|---|---|---|
| Thêm, sửa sinh viên, đổi trạng thái, khóa tài khoản, đặt lại mật khẩu | Admin | Thêm sinh viên tạo luôn tài khoản (tên đăng nhập = mã SV), mật khẩu tạm chỉ hiện một lần. Đổi email thì sinh viên phải xác nhận lại | `backend/app/routers/manage.py`, `frontend/manage-students.html`, `student.html` |
| Import danh sách sinh viên từ Excel | Admin | Đọc file ngay trên trình duyệt (SheetJS), gửi lên để **chạy thử** (thêm / cập nhật / không đổi / lỗi từng dòng), xác nhận mới ghi. Còn dòng lỗi thì không ghi gì | như trên |
| Nhập điểm thành phần | GV phụ trách lớp | Chỉ lớp học kỳ hiện tại, điểm 0–10. Có điểm thi thì tự tính TBCHP (đầu điểm thiếu tính 0) và điểm chữ theo `grade_scale` | `backend/app/routers/teaching.py`, `frontend/teaching.html` |
| Điểm danh | GV phụ trách lớp | Theo từng buổi; không điểm danh trước ngày học | như trên |
| Nhật ký sửa điểm | GV, admin xem | Mỗi lần nhập / sửa / xóa điểm ghi một dòng `audit_logs` (điểm cũ, điểm mới, người sửa) | như trên |

**Trang Tổng quan** (`backend/app/routers/dashboard.py`, `frontend/index.html`) đọc thẳng CSDL v2: nguy cơ học kỳ hiện tại
lấy từ lần chạy AI Agent gần nhất; ĐTB, xếp loại, cảnh báo học tập tính bằng cùng hàm với trang Kết quả học tập
(`semester_summaries`), nên số liệu hai trang luôn khớp. Quản trị thấy toàn trường, giảng viên thấy lớp mình dạy và lớp chủ nhiệm.

Sau khi lưu điểm hoặc điểm danh, bộ lập lịch (`backend/app/scheduler.py`) phát hiện dữ liệu mới và cho AI Agent chạy lại,
nên nguy cơ và email cảnh báo được cập nhật mà không cần ai bấm.

## 9. Lộ trình: hai mạch song song

| Tuần | Mạch AI (Quang) | Mạch hệ thống (Tuyết, Kiên) |
|---|---|---|
| 1–2 | Tải OULAD, khám phá dữ liệu, chốt lược đồ đặc trưng chung | Thiết kế CSDL mới, đăng nhập + phân quyền, menu theo vai trò |
| 3–5 | Tạo đặc trưng theo mốc M0/M1/M2, baseline, so sánh 4 mô hình | Admin: danh mục, tài khoản. Giảng viên: nhập điểm, nhập Excel, điểm danh |
| 6–7 | SHAP, đánh giá theo mốc, chốt mô hình | Sinh viên: xem điểm, điểm danh. Bộ sinh dữ liệu demo theo cấu trúc Đại Nam |
| 8–9 | Thử nghiệm chéo OULAD → UCI | Agent v1: luật + mô hình + cảnh báo trong hệ thống + email + ghi nhận can thiệp |
| 10–11 | Dữ liệu Đại Nam (nếu có): viết bước chuyển cột, train lại | Agent v2 (tùy chọn): báo cáo bằng LLM |
| 12+ | Viết báo cáo, khảo sát giảng viên/sinh viên, chuẩn bị bảo vệ | |

## 10. Câu hỏi cần hỏi thầy / phòng đào tạo

1. Trọng số điểm chuẩn có phải CC 10% - KT1 15% - KT2 15% - Thi 60%? Môn nào khác?
2. Bài thi có điểm liệt không?
3. KT1, KT2 thường làm vào tuần thứ mấy của học kỳ?
4. Ngưỡng vắng bị cấm thi, và điều kiện cảnh báo học tập theo quy chế Đại Nam?
5. Khoa có thể cung cấp bảng điểm học phần các khóa trước (đã ẩn danh) theo các cột ở mục 7 không?

## Nguồn tham khảo

- Kuzilek J., Hlosta M., Zdrahal Z. (2017). *Open University Learning Analytics dataset.* Scientific Data 4, 170171.
  [Bài báo](https://pmc.ncbi.nlm.nih.gov/articles/PMC5704676) · [Trang dữ liệu](https://analyse.kmi.open.ac.uk/open-dataset) · [UCI](https://archive.ics.uci.edu/dataset/349)
- Cortez P., Silva A. (2008). *Using Data Mining to Predict Secondary School Student Performance.* UCI Student Performance dataset.
- Thông tư 08/2021/TT-BGDĐT ban hành Quy chế đào tạo trình độ đại học.
- Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân.
