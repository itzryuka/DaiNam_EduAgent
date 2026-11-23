// Cảnh báo AI Agent gửi tới tài khoản đang đăng nhập. Sinh viên nhận lời nhắc (không có xác suất).

const ALERT_ICONS = { danger: "fa-circle-exclamation", warning: "fa-triangle-exclamation", info: "fa-circle-info" };
const AUDIENCE_LABELS = { lecturer: "Giảng viên bộ môn", advisor: "Cố vấn học tập", student: "Lời nhắc" };

async function loadAlerts() {
  const unreadOnly = document.getElementById("unread-only").checked;
  const data = await apiGet(`/alerts/mine?limit=100&unread_only=${unreadOnly}`);
  const student = CURRENT_USER.role === "student";
  document.getElementById("alerts-title").textContent = student ? "Lời nhắc học tập" : "Cảnh báo từ AI Agent";
  document.getElementById("alerts-hint").textContent = student
    ? "Hệ thống theo dõi điểm danh và điểm kiểm tra của bạn, nhắc sớm những môn cần chú ý để kịp cải thiện trước kỳ thi."
    : `Bạn có ${data.unread} cảnh báo chưa đọc. Xem toàn bộ danh sách và lý do chi tiết ở trang AI Agent.`;
  const list = document.getElementById("alerts");
  if (!data.items.length) {
    list.innerHTML = `<li class="muted" style="padding: 20px">Không có ${unreadOnly ? "cảnh báo chưa đọc" : "cảnh báo nào"}.</li>`;
    return;
  }
  list.innerHTML = data.items.map((a) => `
    <li class="alert-item${a.read ? "" : " unread"}" data-id="${a.id}">
      <div class="alert-icon ${a.level}"><i class="fas ${ALERT_ICONS[a.level]}"></i></div>
      <div class="alert-body">
        <h4>${escapeHtml(a.title)}</h4>
        <p>${escapeHtml(a.message)}</p>
        <div class="alert-meta">${escapeHtml(AUDIENCE_LABELS[a.audience])} · ${new Date(a.created_at).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" })}</div>
      </div>
      ${a.read ? "" : '<button class="btn btn-light btn-sm mark-read" type="button">Đã đọc</button>'}
    </li>`).join("");
}

function reloadAlerts() {
  loadAlerts().catch((err) => showError(document.getElementById("error"), err));
  if (typeof loadBellCount === "function") loadBellCount();
}

document.getElementById("alerts").addEventListener("click", async (e) => {
  const btn = e.target.closest(".mark-read");
  if (!btn) return;
  await apiPost(`/alerts/${btn.closest(".alert-item").dataset.id}/read`);
  reloadAlerts();
});
document.getElementById("read-all").addEventListener("click", async () => {
  await apiPost("/alerts/read-all");
  reloadAlerts();
});
document.getElementById("unread-only").addEventListener("change", reloadAlerts);

reloadAlerts();
