// Trang "Hồ sơ sinh viên": thông tin, tổng kết học tập, học kỳ hiện tại kèm nguy cơ AI, cảnh báo gần đây.
// Quản trị sửa thông tin, đổi trạng thái, khóa tài khoản, đặt lại mật khẩu. Giảng viên chỉ xem.
const studentId = Number(new URLSearchParams(location.search).get("id"));
const SP_LEVEL = { high: ["bad", "Cao"], medium: ["warn", "Trung bình"], low: ["ok", "Thấp"] };
const SP_STATUS_CHIP = { studying: "ok", reserved: "warn", dropped: "bad", graduated: "info" };
let profile = null;

const f2 = (v) => (v == null ? "–" : Number(v).toFixed(2));
const dmy = (iso) => (iso ? iso.split("-").reverse().join("/") : "–");

function spAiCell(ai) {
  if (!ai) return '<span class="muted">Chưa dự báo</span>';
  const [cls, label] = SP_LEVEL[ai.level];
  const why = [...ai.rule_flags.map((r) => `Luật: ${r}`), ...ai.factors.map((f) => `${f.label}: ${f.value} (thường gặp ${f.typical})`)].join("\n");
  return `<span title="${escapeHtml(why || "Không có yếu tố nổi bật")}"><b>${Math.round(ai.proba * 100)}%</b> <span class="chip ${cls}">${label}</span>
    ${ai.source === "ai" ? '<span class="chip ai"><i class="fas fa-wand-magic-sparkles"></i> AI phát hiện sớm</span>' : ""}</span>
    ${ai.rule_flags.length ? `<div class="muted">${escapeHtml(ai.rule_flags.join(", "))}</div>` : ""}`;
}

function warnCell(w) {
  if (!w) return "–";
  return w.is_warned ? `<span class="chip bad" title="${escapeHtml(w.reasons.join("; "))}">Có</span>` : '<span class="chip ok">Không</span>';
}

function renderProfile(data) {
  profile = data;
  const s = data.student;
  document.getElementById("profile").hidden = false;
  document.getElementById("p-avatar").textContent = initials(s.full_name);
  document.getElementById("p-name").textContent = s.full_name;
  document.title = `${s.student_code} ${s.full_name} · EduAgent`;
  document.getElementById("p-meta").innerHTML = `<b>${escapeHtml(s.student_code)}</b> · Lớp ${escapeHtml(s.class_code)} (khóa ${s.cohort})
    <span class="chip ${SP_STATUS_CHIP[s.status]}">${escapeHtml(s.status_label)}</span>
    ${s.has_account && !s.account_active ? '<span class="chip bad"><i class="fas fa-lock"></i> Tài khoản đang khóa</span>' : ""}`;
  const fact = (label, value) => `<div class="kv"><span>${label}</span><b>${value}</b></div>`;
  document.getElementById("p-facts").innerHTML = [
    fact("Giới tính", s.gender === "M" ? "Nam" : s.gender === "F" ? "Nữ" : "–"),
    fact("Ngày sinh", dmy(s.date_of_birth)),
    fact("Cố vấn học tập", escapeHtml(s.advisor ?? "–")),
    fact("Email", s.email ? `${escapeHtml(s.email)} ${s.email_verified ? '<span class="chip ok">Nhận cảnh báo</span>' : '<span class="chip warn">Chưa liên kết</span>'}` : "–"),
    fact("Tài khoản", s.username ? escapeHtml(s.username) : "Chưa có"),
    fact("Đăng nhập gần nhất", s.last_login_at ? escapeHtml(s.last_login_at.replace("T", " ")) : "Chưa đăng nhập"),
  ].join("");

  const actions = document.getElementById("p-actions");
  actions.hidden = !data.can_edit;
  const lock = document.getElementById("btn-lock");
  lock.hidden = !s.has_account;
  lock.innerHTML = s.account_active ? '<i class="fas fa-lock"></i> Khóa tài khoản' : '<i class="fas fa-lock-open"></i> Mở khóa tài khoản';
  lock.className = `btn btn-sm ${s.account_active ? "btn-danger-light" : "btn-ok-light"}`;
  document.getElementById("btn-reset").hidden = !s.has_account;

  const r = data.results;
  const c = r.cumulative;
  const card = (label, value, cls = "") => `<div class="summary-card ${cls}"><div class="summary-value">${value}</div><div class="summary-label">${label}</div></div>`;
  document.getElementById("p-summary").innerHTML = [
    card("ĐTB tích lũy hệ 10", f2(c.gpa10)), card("ĐTB tích lũy hệ 4", f2(c.gpa4)),
    card("Xếp loại học lực", escapeHtml(c.rank ?? "–")), card("Tín chỉ tích lũy", c.credits_passed),
    card("Tín chỉ nợ", c.credits_owed, c.credits_owed ? "bad" : ""), card("Học kỳ đã hoàn thành", c.semesters_done),
  ].join("");
  document.getElementById("p-warning").innerHTML = c.warning?.is_warned
    ? `<div class="alert-error"><i class="fas fa-triangle-exclamation"></i><span>Học kỳ gần nhất thuộc diện <b>cảnh báo học tập</b>: ${c.warning.reasons.map(escapeHtml).join("; ")}.
       ${c.failed_not_retaken.length ? `Đang nợ: ${c.failed_not_retaken.map(escapeHtml).join(", ")}.` : ""}</span></div>` : "";

  renderCurrent(r.semesters.find((x) => x.is_current));
  const done = r.semesters.filter((x) => x.summary);
  document.getElementById("history").hidden = !done.length;
  document.getElementById("history-rows").innerHTML = [...done].reverse().map((sem) => {
    const x = sem.summary;
    const details = sem.courses.map((co) => `${co.course_code} ${co.course_name}: ${co.final_score ?? "–"} (${co.letter_grade ?? "–"})`).join("\n");
    return `<tr>
      <td>${escapeHtml(sem.name)}</td><td class="num">${f2(x.gpa10)}</td><td class="num">${f2(x.gpa4)}</td>
      <td class="num">${f2(x.cum_gpa10)}</td><td class="num"><b>${f2(x.cum_gpa4)}</b></td>
      <td class="num">${x.credits_registered}</td><td class="num">${x.credits_passed}</td><td class="num">${x.cum_credits}</td>
      <td>${escapeHtml(x.rank ?? "–")}</td><td>${warnCell(x.warning)}</td>
      <td><span class="muted" title="${escapeHtml(details)}"><i class="fas fa-list"></i> ${sem.courses.length} môn</span></td>
    </tr>`;
  }).join("");

  document.getElementById("alerts-panel").hidden = !data.alerts.length;
  document.getElementById("p-alerts").innerHTML = data.alerts.map((a) => `<li class="alert-item">
      <div class="alert-icon ${a.level}"><i class="fas ${a.level === "danger" ? "fa-circle-exclamation" : "fa-triangle-exclamation"}"></i></div>
      <div><h4>${escapeHtml(a.title)}</h4><p>${escapeHtml(a.message)}</p>
      <div class="alert-meta">${escapeHtml(a.created_at.replace("T", " "))}</div></div></li>`).join("");
  document.querySelector("main").classList.add("fade-in");
}

function renderCurrent(sem) {
  const panel = document.getElementById("current");
  panel.hidden = !sem;
  if (!sem) return;
  document.getElementById("current-title").textContent = sem.name;
  const flagged = sem.courses.filter((x) => x.ai && x.ai.source !== "none").length;
  document.getElementById("current-meta").textContent = `${sem.courses.length} môn · ${flagged} môn cần chú ý`;
  const codes = ["CC", "KT1", "KT2", "KT3", "THI"].filter((code) => sem.courses.some((x) => x.components.some((k) => k.code === code)));
  document.getElementById("current-head").innerHTML = `<tr><th>Môn học</th><th class="num">TC</th>
    ${codes.map((code) => `<th class="num">${code === "THI" ? "Thi" : code}</th>`).join("")}
    <th class="num">Vắng</th><th class="num">Thi tối thiểu</th><th>Nguy cơ trượt (AI)</th></tr>`;
  document.getElementById("current-rows").innerHTML = sem.courses.map((x) => {
    const has = new Set(x.components.map((k) => k.code));
    const absences = x.absent + x.excused;
    const min = x.exam_unreachable ? '<span class="chip bad">&gt; 10</span>' : x.min_exam_score == null ? "" : formatScore(x.min_exam_score);
    const rowCls = x.ai?.level === "high" ? "row-alert" : x.ai?.source === "ai" ? "row-ai" : x.ai && x.ai.source !== "none" ? "row-warn" : "";
    return `<tr class="${rowCls}">
      <td><b>${escapeHtml(x.course_code)}</b> ${escapeHtml(x.course_name)}${x.attempt_no > 1 ? ` <span class="chip info">Học lại lần ${x.attempt_no}</span>` : ""}</td>
      <td class="num">${x.credits}</td>
      ${codes.map((code) => `<td class="num">${has.has(code) ? formatScore(x.scores[code]) : '<span class="muted">—</span>'}</td>`).join("")}
      <td class="num" title="Có phép ${x.excused}, không phép ${x.absent}, muộn ${x.late}">${absences}/${x.recorded}</td>
      <td class="num">${min}</td>
      <td>${spAiCell(x.ai)}</td>
    </tr>`;
  }).join("");
}

async function loadProfile() {
  if (!studentId) {
    showError(document.getElementById("error"), new Error("Thiếu mã sinh viên trên địa chỉ trang"));
    return;
  }
  try {
    renderProfile(await apiGet(`/manage/students/${studentId}`));
  } catch (error) {
    showError(document.getElementById("error"), error);
  }
}

// ------------------------------------------------------------------ thao tác của quản trị
const editModal = document.getElementById("edit-modal");
editModal.querySelectorAll("[data-modal-close]").forEach((b) => b.addEventListener("click", () => editModal.classList.remove("open")));
editModal.addEventListener("click", (e) => e.target === editModal && editModal.classList.remove("open"));

document.getElementById("btn-edit").addEventListener("click", async () => {
  const s = profile.student;
  const opts = await apiGet("/manage/options");
  document.getElementById("e-class").innerHTML = opts.classes.map((c) => `<option value="${c.id}">${escapeHtml(c.code)}</option>`).join("");
  document.getElementById("e-status").innerHTML = Object.entries(opts.statuses).map(([k, v]) => `<option value="${k}">${escapeHtml(v)}</option>`).join("");
  document.getElementById("e-name").value = s.full_name;
  document.getElementById("e-class").value = s.class_id;
  document.getElementById("e-status").value = s.status;
  document.getElementById("e-gender").value = s.gender ?? "";
  document.getElementById("e-dob").value = s.date_of_birth ?? "";
  document.getElementById("e-email").value = s.email ?? "";
  document.getElementById("edit-message").innerHTML = "";
  editModal.classList.add("open");
});

document.getElementById("edit-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const v = (id) => document.getElementById(id).value.trim();
  try {
    await apiPatch(`/manage/students/${studentId}`, {
      full_name: v("e-name"), class_id: Number(v("e-class")), status: v("e-status"),
      gender: v("e-gender"), date_of_birth: v("e-dob") || null, email: v("e-email") || null,
    });
    editModal.classList.remove("open");
    showSuccess(document.getElementById("message"), "Đã lưu thông tin sinh viên.");
    loadProfile();
  } catch (error) {
    showError(document.getElementById("edit-message"), error);
  }
});

document.getElementById("btn-lock").addEventListener("click", async () => {
  const s = profile.student;
  const active = !s.account_active;
  if (!active && !confirm(`Khóa tài khoản của ${s.full_name}? Sinh viên sẽ không đăng nhập được cho tới khi được mở khóa.`)) return;
  try {
    await apiPatch(`/manage/students/${studentId}`, { account_active: active });
    showSuccess(document.getElementById("message"), active ? "Đã mở khóa tài khoản." : "Đã khóa tài khoản.");
    loadProfile();
  } catch (error) {
    showError(document.getElementById("message"), error);
  }
});

document.getElementById("btn-reset").addEventListener("click", async () => {
  if (!confirm(`Đặt lại mật khẩu cho ${profile.student.full_name}? Mật khẩu cũ sẽ không dùng được nữa.`)) return;
  try {
    const res = await apiPost(`/manage/students/${studentId}/reset-password`);
    document.getElementById("message").innerHTML = `<div class="alert-success credential-box"><i class="fas fa-key"></i><div>
      Đã đặt lại mật khẩu. Tên đăng nhập <b>${escapeHtml(res.username)}</b> · Mật khẩu tạm <code>${escapeHtml(res.temp_password)}</code>
      <div class="muted">Mật khẩu chỉ hiện một lần. Gửi riêng cho sinh viên.</div></div></div>`;
  } catch (error) {
    showError(document.getElementById("message"), error);
  }
});

loadProfile();
