// Trang "Tài khoản & phân quyền" (quản trị): danh sách tài khoản, lọc theo vai trò / email, khóa / mở khóa, gán email.
const PAGE_SIZE = 50;
const ROLE_CHIP = { admin: "bad", lecturer: "info", student: "" };
const ROLE_NAME = { admin: "Quản trị", lecturer: "Giảng viên", student: "Sinh viên" };
let offset = 0;

// Email do nhà trường cấp có thể được quản trị gán thay (coi như đã xác nhận)
function emailCell(u) {
  const status = u.email_verified
    ? `<span class="chip ok" title="Đã xác nhận, nhận được email cảnh báo"><i class="fas fa-check"></i></span> ${escapeHtml(u.email)}`
    : `<span class="chip warn">Chưa liên kết</span>${u.email ? ` <span class="muted" title="Email trong hồ sơ, chưa xác nhận">${escapeHtml(u.email)}</span>` : ""}`;
  return `<div class="email-cell">${status}
    <button class="btn btn-light btn-sm" data-email-id="${u.id}" data-email="${escapeHtml(u.email ?? "")}" title="Gán email"><i class="fas fa-pen"></i></button></div>`;
}

function rowHtml(u) {
  const isMe = u.id === CURRENT_USER.id;
  const action = isMe
    ? '<span class="muted">Tài khoản của bạn</span>'
    : u.is_active
      ? `<button class="btn btn-danger-light btn-sm" data-id="${u.id}" data-active="false"><i class="fas fa-lock"></i> Khóa</button>`
      : `<button class="btn btn-ok-light btn-sm" data-id="${u.id}" data-active="true"><i class="fas fa-lock-open"></i> Mở khóa</button>`;
  return `<tr>
    <td><b>${escapeHtml(u.username)}</b></td>
    <td>${escapeHtml(u.full_name)}</td>
    <td><span class="chip ${ROLE_CHIP[u.role]}">${escapeHtml(u.role_label)}</span></td>
    <td>${escapeHtml(u.detail ?? "")}</td>
    <td>${emailCell(u)}</td>
    <td>${u.last_login_at ? escapeHtml(u.last_login_at.replace("T", " ")) : '<span class="muted">Chưa đăng nhập</span>'}</td>
    <td>${u.is_active ? '<span class="chip ok">Đang hoạt động</span>' : '<span class="chip bad">Đã khóa</span>'}</td>
    <td class="num">${action}</td>
  </tr>`;
}

async function load() {
  const params = new URLSearchParams({ limit: PAGE_SIZE, offset });
  const role = document.getElementById("role-select").value;
  const q = document.getElementById("search").value.trim();
  if (role) params.set("role", role);
  if (q) params.set("q", q);
  const email = document.getElementById("email-select").value;
  if (email) params.set("email", email);
  try {
    const data = await apiGet(`/admin/users?${params}`);
    document.getElementById("count-label").textContent = `${data.total} tài khoản`;
    document.getElementById("role-counts").innerHTML = Object.entries(data.counts)
      .map(([r, n]) => `<span class="chip ${ROLE_CHIP[r]}">${ROLE_NAME[r]} ${n}</span>`).join("") +
      (data.unlinked ? ` <span class="chip warn">${data.unlinked} chưa liên kết email</span>` : "");
    document.getElementById("rows").innerHTML = data.items.map(rowHtml).join("") ||
      '<tr class="empty-row"><td colspan="8">Không tìm thấy tài khoản.</td></tr>';
    const end = Math.min(offset + PAGE_SIZE, data.total);
    document.getElementById("page-label").textContent = data.total ? `Hiển thị ${offset + 1}–${end} / ${data.total}` : "";
    document.getElementById("prev").disabled = offset === 0;
    document.getElementById("next").disabled = end >= data.total;
  } catch (error) {
    showError(document.getElementById("message"), error);
  }
}

document.getElementById("rows").addEventListener("click", async (event) => {
  const emailButton = event.target.closest("button[data-email-id]");
  if (emailButton) {
    const name = emailButton.closest("tr").children[1].textContent;
    const email = prompt(`Email nhà trường cấp cho ${name} (để trống = gỡ liên kết).\nEmail quản trị gán được coi là đã xác nhận.`,
      emailButton.dataset.email);
    if (email === null) return;
    try {
      const updated = await apiPatch(`/admin/users/${emailButton.dataset.emailId}`, { email: email.trim() });
      emailButton.closest("tr").outerHTML = rowHtml(updated);
      showSuccess(document.getElementById("message"), updated.email_verified
        ? `Đã gán email ${updated.email} cho ${updated.username}.` : `Đã gỡ liên kết email của ${updated.username}.`);
    } catch (error) {
      showError(document.getElementById("message"), error);
    }
    return;
  }
  const button = event.target.closest("button[data-id]");
  if (!button) return;
  const active = button.dataset.active === "true";
  const name = button.closest("tr").children[1].textContent;
  if (!active && !confirm(`Khóa tài khoản của ${name}? Người này sẽ không đăng nhập được cho tới khi được mở khóa.`)) return;
  button.disabled = true;
  try {
    const updated = await apiPatch(`/admin/users/${button.dataset.id}`, { is_active: active });
    button.closest("tr").outerHTML = rowHtml(updated);
    showSuccess(document.getElementById("message"), `${active ? "Đã mở khóa" : "Đã khóa"} tài khoản ${updated.username}.`);
  } catch (error) {
    button.disabled = false;
    showError(document.getElementById("message"), error);
  }
});

document.getElementById("role-select").addEventListener("change", () => { offset = 0; load(); });
document.getElementById("email-select").addEventListener("change", () => { offset = 0; load(); });
const initialEmail = new URLSearchParams(location.search).get("email");
if (initialEmail) document.getElementById("email-select").value = initialEmail;
document.getElementById("search-form").addEventListener("submit", (e) => { e.preventDefault(); offset = 0; load(); });
document.getElementById("search").addEventListener("search", () => { offset = 0; load(); });
document.getElementById("prev").addEventListener("click", () => { offset = Math.max(0, offset - PAGE_SIZE); load(); });
document.getElementById("next").addEventListener("click", () => { offset += PAGE_SIZE; load(); });
load();
