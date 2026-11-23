// Trang "Tài khoản của tôi": liên kết email nhận cảnh báo (gửi mã -> nhập mã), gửi thư thử, đổi mật khẩu.
const emailMessage = document.getElementById("email-message");
const emailForm = document.getElementById("email-form");
const codeForm = document.getElementById("code-form");
let account = null;

const EMAIL_WHY = {
  student: "Khi hệ thống cảnh báo sớm thấy bạn cần chú ý ở môn nào, lời nhắc sẽ được gửi tới email này (đồng thời cố vấn học tập của lớp cũng nhận được).",
  lecturer: "Bạn sẽ nhận email tổng hợp khi AI Agent phát hiện sinh viên lớp chủ nhiệm (hoặc lớp học phần bạn dạy) cần chú ý.",
  admin: "Email dùng để nhận thư thử và thông báo hệ thống.",
};

function showStep(step) {
  emailForm.hidden = step !== "email";
  codeForm.hidden = step !== "code";
  document.getElementById("email-actions").hidden = step !== "linked";
}

function renderAccount(data) {
  account = data;
  const u = data.user;
  updateAuthUser(u);
  document.getElementById("email-why").textContent = EMAIL_WHY[u.role];
  document.getElementById("email-chip").innerHTML = data.email_verified
    ? '<span class="chip ok"><i class="fas fa-check"></i> Đã liên kết</span>'
    : '<span class="chip warn">Chưa liên kết</span>';
  const current = document.getElementById("email-current");
  current.hidden = !data.email_verified;
  current.innerHTML = data.email_verified
    ? `<i class="fas fa-envelope-circle-check"></i><div><b>${escapeHtml(data.email)}</b>
        <span class="muted">Xác nhận lúc ${escapeHtml(data.email_verified_at.replace("T", " "))}</span></div>`
    : "";
  document.getElementById("email-label").textContent = data.email_verified ? "Email mới" : "Địa chỉ email";
  if (!data.email_verified && data.email && !document.getElementById("email-input").value) {
    document.getElementById("email-input").value = data.email; // email có sẵn trong hồ sơ, chưa xác nhận
  }
  if (data.pending) {
    document.getElementById("code-to").textContent = data.pending.email;
    document.getElementById("code-note").textContent = `Mã hết hạn lúc ${data.pending.expires_at.split("T")[1]}.`;
    showStep("code");
  } else {
    showStep(data.email_verified ? "linked" : "email");
  }

  const role = escapeHtml(u.role_label);
  const extra = u.student_code
    ? `<div class="kv"><span>Mã sinh viên</span><b>${escapeHtml(u.student_code)}</b></div>`
    : u.advised_classes?.length
      ? `<div class="kv"><span>Lớp chủ nhiệm</span><b>${escapeHtml(u.advised_classes.join(", "))}</b></div>`
      : "";
  document.getElementById("profile").innerHTML = `
    <div class="kv"><span>Tên đăng nhập</span><b>${escapeHtml(u.username)}</b></div>
    <div class="kv"><span>Họ tên</span><b>${escapeHtml(u.full_name)}</b></div>
    <div class="kv"><span>Vai trò</span><b>${role}</b></div>${extra}`;
}

async function loadAccount() {
  try {
    renderAccount(await apiGet("/account"));
  } catch (error) {
    showError(document.getElementById("error"), error);
  }
}

emailForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const email = document.getElementById("email-input").value.trim();
  const button = document.getElementById("email-send");
  button.disabled = true;
  try {
    const res = await apiPost("/account/email/request", { email });
    document.getElementById("code-to").textContent = res.sent_to;
    document.getElementById("code-note").innerHTML = res.dev_code
      ? `<i class="fas fa-flask"></i> Chế độ thử: máy chủ chưa cấu hình SMTP nên không có thư thật nào được gửi đi
         (thư được lưu trong backend/outbox). Mã xác nhận là <b>${escapeHtml(res.dev_code)}</b>.`
      : `Kiểm tra hộp thư (cả mục Thư rác). Mã có hiệu lực ${res.expires_minutes} phút.`;
    emailMessage.innerHTML = "";
    showStep("code");
    document.getElementById("code-input").value = "";
    document.getElementById("code-input").focus();
  } catch (error) {
    showError(emailMessage, error);
  } finally {
    button.disabled = false;
  }
});

codeForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const user = await apiPost("/account/email/verify", { code: document.getElementById("code-input").value.trim() });
    updateAuthUser(user);
    document.getElementById("email-banner")?.remove();
    showSuccess(emailMessage, `Đã liên kết email ${user.email}. Từ nay cảnh báo sẽ được gửi tới địa chỉ này.`);
    await loadAccount();
  } catch (error) {
    showError(emailMessage, error);
  }
});

document.getElementById("code-cancel").addEventListener("click", () => {
  emailMessage.innerHTML = "";
  showStep("email");
});
document.getElementById("email-change").addEventListener("click", () => {
  emailMessage.innerHTML = "";
  document.getElementById("email-input").value = "";
  showStep("email");
  document.getElementById("email-input").focus();
});
document.getElementById("email-test").addEventListener("click", async (event) => {
  event.target.disabled = true;
  try {
    const res = await apiPost("/account/email/test");
    showSuccess(emailMessage, res.status === "sent"
      ? `Đã gửi thư thử tới ${res.to}.`
      : "Chế độ thử: thư đã được lưu trong thư mục backend/outbox (chưa cấu hình SMTP).");
  } catch (error) {
    showError(emailMessage, error);
  } finally {
    event.target.disabled = false;
  }
});

document.getElementById("pwd-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = document.getElementById("pwd-message");
  const newPassword = document.getElementById("pwd-new").value;
  if (newPassword !== document.getElementById("pwd-confirm").value) {
    showError(message, new Error("Hai lần nhập mật khẩu mới không khớp"));
    return;
  }
  try {
    await apiPost("/auth/change-password", { old_password: document.getElementById("pwd-old").value, new_password: newPassword });
    event.target.reset();
    showSuccess(message, "Đã đổi mật khẩu.");
  } catch (error) {
    showError(message, error);
  }
});

loadAccount();
