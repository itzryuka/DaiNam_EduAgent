// Trang "Quản lý sinh viên" (CSDL v2): danh sách, lọc theo lớp / trạng thái / nguy cơ; quản trị thêm sinh viên,
// import từ Excel. Giảng viên chỉ thấy sinh viên lớp mình làm CVHT. Bấm một dòng để mở hồ sơ sinh viên.
const MS_PAGE = 50;
const SHEETJS_URL = "https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js";
const RISK_LEVEL = { high: ["bad", "Cao"], medium: ["warn", "TB"], low: ["ok", "Thấp"] };
const STATUS_CHIP = { studying: "ok", reserved: "warn", dropped: "bad", graduated: "info" };
let msOffset = 0;
let msOptions = null;
let importRows = null;

const fmtDate = (iso) => (iso ? iso.split("-").reverse().join("/") : "");

function riskCell(r) {
  if (!r || !r.worst) return '<span class="muted">–</span>';
  const [cls, label] = RISK_LEVEL[r.worst.level];
  const ai = r.ai ? ` <span class="chip ai" title="AI phát hiện sớm: chưa vi phạm luật"><i class="fas fa-wand-magic-sparkles"></i> ${r.ai}</span>` : "";
  return `<span class="chip ${cls}">${label}</span> <b>${Math.round(r.worst.proba * 100)}%</b>
    <span class="muted">${escapeHtml(r.worst.course)}</span>${ai}
    ${r.flagged ? `<div class="muted">${r.flagged} môn cần chú ý</div>` : ""}`;
}

function rowHtml(s) {
  const email = s.email
    ? `${s.email_verified ? '<i class="fas fa-circle-check" style="color: var(--ok)" title="Đã liên kết, nhận email cảnh báo"></i> ' : ""}${escapeHtml(s.email)}`
    : '<span class="muted">–</span>';
  const account = s.has_account && !s.account_active ? ' <span class="chip bad"><i class="fas fa-lock"></i> Khóa TK</span>' : "";
  return `<tr class="clickable" data-id="${s.id}">
    <td><a href="student.html?id=${s.id}"><b>${escapeHtml(s.student_code)}</b></a></td>
    <td class="nowrap">${escapeHtml(s.full_name)}</td>
    <td class="nowrap">${escapeHtml(s.class_code)}</td>
    <td class="nowrap">${fmtDate(s.date_of_birth)}</td>
    <td class="num${s.gpa4 != null && s.gpa4 < 2 ? " score-fail" : ""}">${s.gpa4 == null ? "–" : s.gpa4.toFixed(2)}</td>
    <td class="num">${s.credits}</td>
    <td class="num${s.owed ? " score-fail" : ""}">${s.owed || ""}</td>
    <td>${riskCell(s.risk)}</td>
    <td class="email-col">${email}</td>
    <td><span class="chip ${STATUS_CHIP[s.status]}">${escapeHtml(s.status_label)}</span>${account}</td>
  </tr>`;
}

async function loadStudents() {
  const params = new URLSearchParams({ limit: MS_PAGE, offset: msOffset });
  const q = document.getElementById("search").value.trim();
  if (q) params.set("q", q);
  for (const [id, key] of [["class-select", "class_id"], ["status-select", "status"], ["risk-select", "risk"]]) {
    const v = document.getElementById(id).value;
    if (v) params.set(key, v);
  }
  // Địa chỉ trang chỉ giữ bộ lọc (bỏ limit, offset mặc định) để gửi link / tải lại vẫn đúng
  const shown = new URLSearchParams(params);
  shown.delete("limit");
  if (!msOffset) shown.delete("offset");
  history.replaceState(null, "", shown.size ? `?${shown}` : location.pathname);
  try {
    const data = await apiGet(`/manage/students?${params}`);
    document.getElementById("count-label").textContent = `${data.total} sinh viên`;
    document.getElementById("status-counts").innerHTML = Object.entries(data.counts)
      .map(([k, n]) => `<span class="chip ${STATUS_CHIP[k]}">${escapeHtml(msOptions.statuses[k])} ${n}</span>`).join("");
    const rows = document.getElementById("rows");
    rows.innerHTML = data.items.map(rowHtml).join("") ||
      '<tr class="empty-row"><td colspan="10">Không có sinh viên phù hợp.</td></tr>';
    rows.classList.remove("fade-in");
    void rows.offsetWidth; // chạy lại hiệu ứng hiện dần mỗi lần lọc
    rows.classList.add("fade-in");
    const end = Math.min(msOffset + MS_PAGE, data.total);
    document.getElementById("page-label").textContent = data.total ? `Hiển thị ${msOffset + 1}–${end} / ${data.total}` : "";
    document.getElementById("prev").disabled = msOffset === 0;
    document.getElementById("next").disabled = end >= data.total;
  } catch (error) {
    showError(document.getElementById("message"), error);
  }
}

// ------------------------------------------------------------------ hộp thoại dùng chung
function openModal(id) {
  const modal = document.getElementById(id);
  modal.classList.add("open");
  return modal;
}
document.querySelectorAll(".modal-backdrop").forEach((modal) => {
  modal.querySelectorAll("[data-modal-close]").forEach((b) => b.addEventListener("click", () => modal.classList.remove("open")));
  modal.addEventListener("click", (e) => e.target === modal && modal.classList.remove("open"));
});

function passwordBox(username, password, note) {
  return `<div class="alert-success credential-box"><i class="fas fa-key"></i><div>
    ${note}<br>Tên đăng nhập <b>${escapeHtml(username)}</b> · Mật khẩu tạm <code>${escapeHtml(password)}</code>
    <div class="muted">Mật khẩu chỉ hiện một lần. Gửi riêng cho sinh viên và nhắc đổi mật khẩu ở trang Tài khoản của tôi.</div>
  </div></div>`;
}

// ------------------------------------------------------------------ thêm sinh viên
document.getElementById("btn-add").addEventListener("click", () => {
  document.getElementById("add-form").reset();
  document.getElementById("add-message").innerHTML = "";
  document.getElementById("add-fields").hidden = false;
  document.getElementById("add-done").hidden = true;
  document.getElementById("add-submit").hidden = false;
  openModal("add-modal");
  document.getElementById("f-code").focus();
});

document.getElementById("add-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const value = (id) => document.getElementById(id).value.trim();
  try {
    const res = await apiPost("/manage/students", {
      student_code: value("f-code"), full_name: value("f-name"), class_id: Number(value("f-class")),
      gender: value("f-gender") || null, date_of_birth: value("f-dob") || null, email: value("f-email") || null,
    });
    document.getElementById("add-fields").hidden = true;
    document.getElementById("add-submit").hidden = true;
    const done = document.getElementById("add-done");
    done.hidden = false;
    done.innerHTML = passwordBox(res.username, res.temp_password,
      `Đã thêm <b>${escapeHtml(res.student.full_name)}</b> vào lớp ${escapeHtml(res.student.class_code)}.`) +
      `<p><a href="student.html?id=${res.student.id}">Mở hồ sơ sinh viên</a></p>`;
    document.getElementById("add-message").innerHTML = "";
    loadStudents();
  } catch (error) {
    showError(document.getElementById("add-message"), error);
  }
});

// ------------------------------------------------------------------ import Excel
let sheetjs = null;
function loadSheetJs() {
  sheetjs ??= new Promise((resolve, reject) => {
    if (window.XLSX) return resolve(window.XLSX);
    const script = document.createElement("script");
    script.src = SHEETJS_URL;
    script.onload = () => resolve(window.XLSX);
    script.onerror = () => { sheetjs = null; reject(new Error("Không tải được thư viện đọc Excel (cần mạng Internet).")); };
    document.head.append(script);
  });
  return sheetjs;
}

const ACTION_CHIP = {
  create: '<span class="chip ok">Thêm mới</span>', update: '<span class="chip info">Cập nhật</span>',
  unchanged: '<span class="chip">Không đổi</span>', error: '<span class="chip bad">Lỗi</span>',
};

function renderImportResult(res) {
  const s = res.summary;
  const head = res.dry_run
    ? `Kiểm tra xong: <b>${s.create}</b> thêm mới, <b>${s.update}</b> cập nhật, ${s.unchanged} không đổi` +
      (s.error ? `, <b class="score-fail">${s.error} dòng lỗi</b> (sửa file rồi chọn lại)` : ".")
    : `Đã ghi: ${s.create} sinh viên mới, ${s.update} cập nhật.`;
  const rows = res.rows.filter((r) => !res.dry_run || r.action !== "unchanged" || res.rows.length <= 50);
  document.getElementById("import-preview").innerHTML = `<p>${head}</p>
    ${res.credentials.length ? `<div class="alert-success credential-box"><i class="fas fa-key"></i><div>
        Đã tạo ${res.credentials.length} tài khoản với mật khẩu tạm.
        <button class="btn btn-primary btn-sm" type="button" id="download-credentials"><i class="fas fa-download"></i> Tải danh sách mật khẩu (.xlsx)</button>
        <div class="muted">Chỉ tải được lúc này. Gửi riêng cho từng sinh viên, không đăng công khai.</div></div></div>` : ""}
    <div class="table-scroll import-table"><table>
      <thead><tr><th class="num">Dòng</th><th>Mã SV</th><th>Họ tên</th><th>Lớp</th><th>Kết quả</th></tr></thead>
      <tbody>${rows.map((r) => `<tr${r.action === "error" ? ' class="row-alert"' : ""}>
        <td class="num">${r.row}</td><td>${escapeHtml(r.student_code)}</td><td>${escapeHtml(r.full_name)}</td>
        <td>${escapeHtml(r.class_code)}</td>
        <td>${ACTION_CHIP[r.action]} ${r.errors.map((e) => `<div class="score-fail">${escapeHtml(e)}</div>`).join("")}</td>
      </tr>`).join("")}</tbody>
    </table></div>`;
  const commit = document.getElementById("import-commit");
  commit.disabled = !res.dry_run || s.error > 0 || s.create + s.update === 0;
  if (res.credentials.length) {
    document.getElementById("download-credentials").addEventListener("click", async () => {
      const XLSX = await loadSheetJs();
      const ws = XLSX.utils.json_to_sheet(res.credentials.map((c) => ({
        "Mã SV": c.student_code, "Họ tên": c.full_name, "Lớp": c.class_code, "Tên đăng nhập": c.username,
        "Mật khẩu tạm": c.temp_password })));
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, "Tài khoản");
      XLSX.writeFile(wb, `tai-khoan-sinh-vien-${new Date().toISOString().slice(0, 10)}.xlsx`);
    });
  }
}

document.getElementById("btn-import").addEventListener("click", () => {
  importRows = null;
  document.getElementById("import-file").value = "";
  document.getElementById("import-message").innerHTML = "";
  document.getElementById("import-preview").innerHTML = "";
  document.getElementById("import-commit").disabled = true;
  openModal("import-modal");
  loadSheetJs().catch((error) => showError(document.getElementById("import-message"), error));
});

document.getElementById("import-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  const message = document.getElementById("import-message");
  document.getElementById("import-preview").innerHTML = "";
  if (!file) return;
  try {
    const XLSX = await loadSheetJs();
    const wb = XLSX.read(await file.arrayBuffer(), { cellDates: true });
    const ws = wb.Sheets[wb.SheetNames[0]];
    // raw: false + dateNF: ngày sinh dạng ô ngày của Excel cũng thành chuỗi ngày/tháng/năm
    importRows = XLSX.utils.sheet_to_json(ws, { raw: false, dateNF: "dd/mm/yyyy", defval: "" });
    if (!importRows.length) throw new Error("File không có dòng dữ liệu nào");
    message.innerHTML = `<p class="muted">Đọc được ${importRows.length} dòng từ sheet "${escapeHtml(wb.SheetNames[0])}". Đang kiểm tra...</p>`;
    renderImportResult(await apiPost("/manage/students/import", { rows: importRows, dry_run: true }));
    message.innerHTML = "";
  } catch (error) {
    importRows = null;
    showError(message, error);
  }
});

document.getElementById("import-commit").addEventListener("click", async (event) => {
  if (!importRows) return;
  event.target.disabled = true;
  try {
    renderImportResult(await apiPost("/manage/students/import", { rows: importRows, dry_run: false }));
    importRows = null;
    loadStudents();
  } catch (error) {
    showError(document.getElementById("import-message"), error);
  }
});

document.getElementById("import-template").addEventListener("click", async () => {
  try {
    const XLSX = await loadSheetJs();
    const cls = msOptions.classes[0]?.code ?? "CNTT 18-01";
    const ws = XLSX.utils.aoa_to_sheet([
      ["Mã SV", "Họ tên", "Lớp", "Giới tính", "Ngày sinh", "Email"],
      ["SV180901", "Nguyễn Văn An", cls, "Nam", "15/08/2006", "sv180901@example.edu.vn"],
      ["SV180902", "Trần Thị Bình", cls, "Nữ", "02/11/2006", ""],
    ]);
    ws["!cols"] = [{ wch: 12 }, { wch: 24 }, { wch: 14 }, { wch: 10 }, { wch: 12 }, { wch: 28 }];
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Sinh viên");
    XLSX.writeFile(wb, "mau-import-sinh-vien.xlsx");
  } catch (error) {
    showError(document.getElementById("import-message"), error);
  }
});

// ------------------------------------------------------------------ khởi tạo
async function initStudentsPage() {
  try {
    msOptions = await apiGet("/manage/options");
  } catch (error) {
    showError(document.getElementById("message"), error);
    return;
  }
  const classOptions = msOptions.classes.map((c) => `<option value="${c.id}">${escapeHtml(c.code)}</option>`).join("");
  document.getElementById("class-select").insertAdjacentHTML("beforeend", classOptions);
  document.getElementById("f-class").innerHTML = classOptions;
  document.getElementById("status-select").insertAdjacentHTML("beforeend",
    Object.entries(msOptions.statuses).map(([k, v]) => `<option value="${k}">${escapeHtml(v)}</option>`).join(""));
  document.getElementById("admin-actions").hidden = !msOptions.can_edit;
  if (!msOptions.can_edit) {
    document.body.dataset.title = "Sinh viên lớp chủ nhiệm";
    document.querySelector(".page-title-nav").textContent = "Sinh viên lớp chủ nhiệm";
  }

  // Khôi phục bộ lọc từ địa chỉ trang (vd ô tìm kiếm trên thanh điều hướng: ?q=...)
  const params = new URLSearchParams(location.search);
  document.getElementById("search").value = params.get("q") ?? "";
  document.getElementById("class-select").value = params.get("class_id") ?? "";
  document.getElementById("status-select").value = params.get("status") ?? "";
  document.getElementById("risk-select").value = params.get("risk") ?? "";
  msOffset = Number(params.get("offset")) || 0;
  loadStudents();
}

for (const id of ["class-select", "status-select", "risk-select"]) {
  document.getElementById(id).addEventListener("change", () => { msOffset = 0; loadStudents(); });
}
document.getElementById("search-form").addEventListener("submit", (e) => { e.preventDefault(); msOffset = 0; loadStudents(); });
document.getElementById("search").addEventListener("search", () => { msOffset = 0; loadStudents(); });
document.getElementById("prev").addEventListener("click", () => { msOffset = Math.max(0, msOffset - MS_PAGE); loadStudents(); });
document.getElementById("next").addEventListener("click", () => { msOffset += MS_PAGE; loadStudents(); });
document.getElementById("rows").addEventListener("click", (event) => {
  const row = event.target.closest("tr[data-id]");
  if (row && !event.target.closest("a")) location.href = `student.html?id=${row.dataset.id}`;
});
initStudentsPage();
