// Trang "Lịch sử gửi email": quản trị xem mọi email + cấu hình người nhận, Agent tự chạy; giảng viên xem email của mình.
const EMAIL_PAGE = 30;
const STATUS_CHIP = {
  sent: '<span class="chip ok">Đã gửi</span>',
  outbox: '<span class="chip info" title="Chưa cấu hình SMTP: thư lưu thành file trong backend/outbox">Chế độ thử</span>',
  failed: '<span class="chip bad">Lỗi</span>',
};
const ROLE_LABEL = { admin: "Quản trị", lecturer: "Giảng viên", student: "Sinh viên" };
let emailOffset = 0;
const isAdmin = CURRENT_USER?.role === "admin";

function emailRow(e) {
  const who = e.user ? `${escapeHtml(e.user.full_name)} <span class="muted">${escapeHtml(e.user.username)}</span><br>` : "";
  const audience = e.audience_label ? ` <span class="chip">${escapeHtml(e.audience_label)}</span>` : "";
  return `<tr>
    <td style="white-space: nowrap">${escapeHtml(e.created_at.replace("T", " "))}</td>
    <td>${escapeHtml(e.kind_label)}${audience}</td>
    <td>${who}<span class="muted">${escapeHtml(e.to)}</span></td>
    <td><div class="email-subject" data-id="${e.id}" title="Bấm để xem nội dung">${escapeHtml(e.subject)}</div>
      <div class="email-body" id="body-${e.id}" hidden>${escapeHtml(e.body)}</div>
      ${e.error ? `<div class="score-fail" style="font-size: 12px">${escapeHtml(e.error)}</div>` : ""}</td>
    <td class="num">${e.n_alerts || ""}</td>
    <td>${STATUS_CHIP[e.status]}</td>
  </tr>`;
}

async function loadEmails() {
  const params = new URLSearchParams({ limit: EMAIL_PAGE, offset: emailOffset });
  for (const id of ["kind", "status"]) {
    const value = document.getElementById(id).value;
    if (value) params.set(id, value);
  }
  try {
    const data = await apiGet(`/emails?${params}`);
    document.getElementById("rows").innerHTML = data.items.map(emailRow).join("") ||
      '<tr class="empty-row"><td colspan="6">Chưa có email nào.</td></tr>';
    const end = Math.min(emailOffset + EMAIL_PAGE, data.total);
    document.getElementById("page-label").textContent = data.total ? `Hiển thị ${emailOffset + 1}–${end} / ${data.total}` : "";
    document.getElementById("prev").disabled = emailOffset === 0;
    document.getElementById("next").disabled = end >= data.total;
  } catch (error) {
    showError(document.getElementById("error"), error);
  }
}

function renderConfig(c) {
  const mode = c.mail.mode === "brevo"
    ? `<span class="chip ok">Brevo API: gửi từ ${escapeHtml(c.mail.sender)}</span>`
    : c.mail.mode === "smtp"
    ? `<span class="chip ok">SMTP: ${escapeHtml(c.mail.host)}</span>`
    : '<span class="chip warn" title="Thêm SMTP_HOST, SMTP_USER, SMTP_PASSWORD vào backend/.env (hoặc BREVO_API_KEY trên Render) để gửi thật">Chế độ thử: chưa cấu hình gửi email</span>';
  const redirect = c.mail.redirect_to ? ` <span class="chip info">Chuyển hết tới ${escapeHtml(c.mail.redirect_to)}</span>` : "";
  document.getElementById("mail-mode").innerHTML = mode + redirect;
  document.getElementById("audiences").innerHTML = Object.entries(c.audience_labels).map(([key, label]) =>
    `<label class="check-inline"><input type="checkbox" name="audience" value="${key}" ${c.audiences.includes(key) ? "checked" : ""} />
      ${escapeHtml(label)}${key === "advisor" ? " (giáo viên chủ nhiệm)" : key === "lecturer" ? " bộ môn" : ""}</label>`).join("");
  document.getElementById("linked").innerHTML = Object.entries(c.linked).map(([role, x]) =>
    `<div class="kv"><span>${ROLE_LABEL[role]}</span><b>${x.linked} / ${x.total}</b></div>`).join("");
  document.getElementById("agent-auto").checked = c.agent.auto;
  const [kind, day, hh, mm] = c.agent.schedule.split(":");
  const when = kind === "weekly" ? `${{ MON: "Thứ 2", TUE: "Thứ 3", WED: "Thứ 4", THU: "Thứ 5", FRI: "Thứ 6", SAT: "Thứ 7", SUN: "Chủ nhật" }[day] ?? day} hằng tuần, ${hh}:${mm}` : c.agent.schedule;
  document.getElementById("agent-info").innerHTML = `
    <div class="kv"><span>Theo lịch</span><b>${escapeHtml(when)}</b></div>
    <div class="kv"><span>Kiểm tra điểm / điểm danh mới</span><b>${c.agent.poll_minutes} phút / lần</b></div>
    <div class="kv"><span>Dữ liệu mới nhất</span><b>${escapeHtml((c.agent.last_data_change ?? "–").replace("T", " "))}</b></div>`;
}

async function loadConfig() {
  if (!isAdmin) return;
  document.getElementById("config").hidden = false;
  try {
    renderConfig(await apiGet("/emails/config"));
  } catch (error) {
    showError(document.getElementById("config-message"), error);
  }
}

document.getElementById("save-config").addEventListener("click", async () => {
  const message = document.getElementById("config-message");
  try {
    const c = await apiPut("/emails/config", {
      audiences: [...document.querySelectorAll('input[name="audience"]:checked')].map((x) => x.value),
      agent_auto: document.getElementById("agent-auto").checked,
    });
    renderConfig(c);
    showSuccess(message, "Đã lưu cài đặt.");
  } catch (error) {
    showError(message, error);
  }
});

document.getElementById("rows").addEventListener("click", (event) => {
  const subject = event.target.closest(".email-subject");
  if (!subject) return;
  const body = document.getElementById(`body-${subject.dataset.id}`);
  body.hidden = !body.hidden;
});
for (const id of ["kind", "status"]) {
  document.getElementById(id).addEventListener("change", () => { emailOffset = 0; loadEmails(); });
}
document.getElementById("prev").addEventListener("click", () => { emailOffset = Math.max(0, emailOffset - EMAIL_PAGE); loadEmails(); });
document.getElementById("next").addEventListener("click", () => { emailOffset += EMAIL_PAGE; loadEmails(); });
if (!isAdmin) document.getElementById("history-title").textContent = "Email hệ thống đã gửi tới bạn";

loadConfig();
loadEmails();
