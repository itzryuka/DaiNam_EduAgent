"""Lược đồ đặc trưng chung cho bài toán dự báo trượt môn.

Mọi nguồn dữ liệu (OULAD, UCI, dữ liệu Đại Nam) đều được một "adapter" trong ml/adapters/ quy đổi về đúng
các cột dưới đây, nhờ đó dùng chung một quy trình train (ml/train_checkpoints.py).
Ý nghĩa và cách quy đổi từng nguồn: docs/thiet-ke-he-thong.md, mục 7.
"""

# Các mốc dự báo trong học kỳ
CHECKPOINTS = ["M0", "M1", "M2"]
CHECKPOINT_LABELS = {
    "M0": "Đầu kỳ",
    "M1": "Sau khoảng 40% bài kiểm tra",
    "M2": "Hết bài kiểm tra, trước khi thi",
}

# Có ngay từ đầu kỳ
BASE_FEATURES = [
    "prev_attempts",     # số lần đã học môn này trước đây
    "credit_load",       # khối lượng học trong kỳ (số tín chỉ đăng ký)
    "course_fail_rate",  # tỷ lệ trượt của môn ở các kỳ TRƯỚC (độ khó môn)
    "engagement",        # mức tham gia học tập đến mốc, xếp hạng phần trăm trong lớp (0..1)
]
# Chỉ có khi đã có điểm kiểm tra
PROCESS_FEATURES = [
    "process_score",     # điểm quá trình đến mốc, đã nhân trọng số, chuẩn hóa 0..1 (bài chưa nộp = 0)
    "submission_rate",   # tỷ lệ bài kiểm tra đã nộp / đã đến hạn
]

# Xu hướng gần đây: thứ mà quy tắc đơn giản không nắm được. Chỉ có từ M1 trở đi.
TREND_FEATURES = [
    "score_trend",        # điểm bài gần nhất trừ bài đầu tiên (0..1)       | Đại Nam: KT2 - KT1
    "recent_engagement",  # mức tham gia 14 ngày gần nhất, xếp hạng % lớp   | Đại Nam: điểm danh 2 tuần gần nhất
    "inactive_days",      # số ngày kể từ lần hoạt động cuối (tối đa 60)   | Đại Nam: số buổi vắng liên tiếp gần nhất
    "late_rate",          # tỷ lệ bài nộp muộn / bài đã nộp                | Đại Nam: cần hệ thống ghi hạn nộp
]

# "core": chỉ các đặc trưng chắc chắn có ở mọi nguồn. "extended": thêm xu hướng.
FEATURE_SETS = {
    "core": {
        "M0": BASE_FEATURES,
        "M1": BASE_FEATURES + PROCESS_FEATURES,
        "M2": BASE_FEATURES + PROCESS_FEATURES,
    },
    "extended": {
        "M0": BASE_FEATURES,
        "M1": BASE_FEATURES + PROCESS_FEATURES + TREND_FEATURES,
        "M2": BASE_FEATURES + PROCESS_FEATURES + TREND_FEATURES,
    },
}
FEATURES = FEATURE_SETS["core"]
# Adapter xuất đủ mọi cột của bộ lớn nhất
ALL_FEATURES = FEATURE_SETS["extended"]

TARGET = "fail"  # 1 = trượt môn
# Cột nhận diện, không đưa vào mô hình. term phải sắp xếp được theo thời gian để chia train/test.
META = ["source", "course", "term", "student_id"]
