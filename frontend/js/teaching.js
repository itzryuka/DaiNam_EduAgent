// Trang "Lớp học phần": giảng viên thấy lớp mình dạy (quản trị thấy tất cả) trong học kỳ hiện tại.
// Chọn một lớp, rồi chọn chế độ: Tình hình lớp (điểm, chuyên cần, nguy cơ AI), Nhập điểm, Điểm danh, Nhật ký sửa điểm.
let currentDetail = null;
let currentSectionId = null;
let currentMode = new URLSearchParams(location.search).get("mode") || "view";
const AI_LEVELS = { high: ["bad", "Cao"], medium: ["warn", "Trung bình"], low: ["ok", "Thấp"] };
const ATT_STATUS = [["present", "Có mặt"], ["late", "Muộn"], ["excused", "Có phép"], ["absent", "Vắng"]];
const MODE_HINT = {
  grades: "Chọn lớp học phần để nhập điểm.",
  attendance: "Chọn lớp học phần để điểm danh.",
};

// Cần chú ý: vi phạm luật, hoặc AI Agent dự báo nguy cơ trượt (mức trung bình trở lên)
const needsAttention = (s) => s.flags.length > 0 || (s.ai && s.ai.source !== "none");
const studentLink = (s) => `<a href="student.html?id=${s.student_id}" title="Hồ sơ sinh viên">${escapeHtml(s.student_code)}</a>`;

function aiCell(ai) {
  if (!ai) return '<span class="muted">Chưa dự báo</span>';
  const [cls, label] = AI_LEVELS[ai.level];
  const why = ai.factors.map((f) => `${f.label}: ${f.value} (thường gặp ${f.typical})`).join("\n");
  return `<span class="ai-cell" title="${escapeHtml(why || "Không có yếu tố nổi bật")}">
      <b>${Math.round(ai.proba * 100)}%</b> <span class="chip ${cls}">${label}</span>
      ${ai.source === "ai" ? '<span class="chip ai" title="Chưa vi phạm luật nào"><i class="fas fa-wand-magic-sparkles"></i> AI phát hiện sớm</span>' : ""}
    </span>
    ${ai.level !== "low" && ai.factors[0] ? `<div class="muted">${escapeHtml(ai.factors[0].label)}: ${escapeHtml(ai.factors[0].value)}</div>` : ""}`;
}

function progressChips(section) {
  return section.components_entered
    .map((c) => {
      const cls = c.entered === 0 ? "" : c.entered >= c.of ? "ok" : "warn";
      return `<span class="chip ${cls}" title="Đã nhập ${c.entered}/${c.of}">${c.code} ${c.entered}/${c.of}</span>`;
    })
    .join("");
}

function renderSections(sections, selectedId) {
  const container = document.getElementById("sections");
  if (!sections.length) {
    container.innerHTML = '<p class="muted">Học kỳ này bạn chưa được phân công lớp học phần nào.</p>';
    return;
  }
  container.innerHTML = sections
    .map((s) => `<button class="section-card${s.id === selectedId ? " selected" : ""}" type="button" data-id="${s.id}">
        <div class="att-sub"><span>${escapeHtml(s.code)}</span><span>${s.credits} TC · ${escapeHtml(s.room ?? "")}</span></div>
        <h4>${escapeHtml(s.course_name)}</h4>
        <div class="att-sub">
          <span><i class="fas fa-users"></i> ${s.n_students} SV · ${s.sessions_recorded}/${s.total_sessions} buổi</span>
          ${s.n_over_absence ? `<span class="chip bad">${s.n_over_absence} vượt ngưỡng vắng</span>` : ""}
        </div>
        ${s.n_flagged ? `<div class="chips"><span class="chip warn">${s.n_flagged} cần chú ý</span>${s.n_ai_only ? `<span class="chip ai"><i class="fas fa-wand-magic-sparkles"></i> ${s.n_ai_only} AI phát hiện sớm</span>` : ""}</div>` : ""}
        ${CURRENT_USER.role === "admin" && s.lecturer ? `<div class="att-sub">GV: ${escapeHtml(s.lecturer)}</div>` : ""}
        <div class="chips">${progressChips(s)}</div>
      </button>`)
    .join("");
  container.querySelectorAll(".section-card").forEach((card) =>
    card.addEventListener("click", () => selectSection(Number(card.dataset.id)))
  );
}

// ------------------------------------------------------------------ tình hình lớp
function renderDetail() {
  const data = currentDetail;
  const attentionOnly = document.getElementById("attention-only").checked;
  const comps = data.components;
  document.getElementById("detail-head").innerHTML = `<tr>
      <th>Mã SV</th><th>Họ tên</th><th>Lớp</th>
      ${comps.map((c) => `<th class="num">${c.code === "THI" ? "Thi" : c.code}<span class="weight">${Math.round(c.weight * 100)}%</span></th>`).join("")}
      <th class="num">Vắng</th><th class="num">ĐQT</th><th class="num">Thi tối thiểu</th><th>Luật quy chế</th><th>Nguy cơ trượt (AI)</th>
    </tr>`;

  const rows = data.students.filter((s) => !attentionOnly || needsAttention(s));
  document.getElementById("detail-rows").innerHTML = rows
    .map((s) => {
      const severe = s.flags.some((f) => f.includes("cấm thi") || f.includes("Không thể"));
      const cls = severe ? "row-alert" : s.ai?.source === "ai" ? "row-ai" : needsAttention(s) ? "row-warn" : "";
      const absences = s.absent + s.excused;
      const minExam = s.exam_unreachable
        ? '<span class="chip bad">&gt; 10</span>'
        : s.min_exam_score == null ? "" : formatScore(s.min_exam_score);
      return `<tr class="${cls}">
        <td>${studentLink(s)}${s.attempt_no > 1 ? ` <span class="chip info">Lần ${s.attempt_no}</span>` : ""}</td>
        <td class="nowrap">${escapeHtml(s.full_name)}</td>
        <td>${escapeHtml(s.class_code)}</td>
        ${comps.map((c) => `<td class="num">${formatScore(s.scores[c.code])}</td>`).join("")}
        <td class="num" title="Có phép ${s.excused}, không phép ${s.absent}, muộn ${s.late}">${absences}/${s.recorded}</td>
        <td class="num${s.process_score != null && s.process_score < 4 ? " score-fail" : ""}">${s.process_score == null ? "" : s.process_score.toFixed(1)}</td>
        <td class="num">${minExam}</td>
        <td><div class="chips">${s.flags.map((f) => `<span class="chip ${f.includes("nhiều") ? "warn" : "bad"}">${escapeHtml(f)}</span>`).join("")}</div></td>
        <td>${aiCell(s.ai)}</td>
      </tr>`;
    })
    .join("") || `<tr class="empty-row"><td colspan="${comps.length + 8}">Không có sinh viên nào cần chú ý.</td></tr>`;
}

// ------------------------------------------------------------------ nhập điểm
function gradeChanges() {
  return [...document.querySelectorAll("#grades-rows input.score-input")]
    .filter((input) => input.value.trim() !== input.dataset.orig)
    .map((input) => ({ input, enrollment_id: Number(input.dataset.e), component: input.dataset.c,
                       score: input.value.trim() === "" ? null : Number(input.value) }));
}

function updateGradeSave() {
  const changes = gradeChanges();
  let invalid = 0;
  document.querySelectorAll("#grades-rows input.score-input").forEach((input) => {
    const v = input.value.trim();
    const bad = v !== "" && (Number.isNaN(Number(v)) || Number(v) < 0 || Number(v) > 10);
    input.classList.toggle("invalid", bad);
    input.classList.toggle("changed", !bad && v !== input.dataset.orig);
    invalid += bad;
  });
  const button = document.getElementById("grades-save");
  button.disabled = !changes.length || invalid > 0;
  button.innerHTML = `<i class="fas fa-floppy-disk"></i> Lưu điểm${changes.length ? ` (${changes.length} ô)` : ""}`;
  document.getElementById("grades-hint").innerHTML = invalid
    ? `<span class="score-fail">${invalid} ô không hợp lệ: điểm phải từ 0 đến 10.</span>`
    : "Điểm thang 10, một chữ số thập phân. Enter để xuống dòng dưới. Để trống = chưa có điểm.";
}

function renderGrades() {
  const data = currentDetail;
  const comps = data.components;
  const editable = data.editable;
  document.getElementById("grades-head").innerHTML = `<tr><th>Mã SV</th><th>Họ tên</th>
    ${comps.map((c) => `<th class="num">${c.code === "THI" ? "Thi" : c.code}<span class="weight">${Math.round(c.weight * 100)}%</span></th>`).join("")}
    <th class="num">TBCHP</th><th class="num">Điểm chữ</th></tr>`;
  document.getElementById("grades-rows").innerHTML = data.students.map((s, row) => {
    const locked = !editable || s.status === "withdrawn";
    return `<tr>
      <td>${studentLink(s)}${s.status === "banned_exam" ? ' <span class="chip bad">Cấm thi</span>' : ""}</td>
      <td class="nowrap">${escapeHtml(s.full_name)}</td>
      ${comps.map((c, col) => {
        const v = s.scores[c.code];
        const orig = v == null ? "" : String(Number(v));
        return `<td class="num"><input class="score-input" type="number" inputmode="decimal" min="0" max="10" step="0.1"
          value="${orig}" data-orig="${orig}" data-e="${s.enrollment_id}" data-c="${c.code}" data-row="${row}" data-col="${col}"
          aria-label="${escapeHtml(c.code)} của ${escapeHtml(s.student_code)}" ${locked ? "disabled" : ""} /></td>`;
      }).join("")}
      <td class="num"><b>${formatScore(s.final_score)}</b></td>
      <td class="num">${s.letter_grade ?? ""}</td>
    </tr>`;
  }).join("");
  if (!editable) {
    document.getElementById("grades-hint").textContent = "Lớp không thuộc học kỳ hiện tại: chỉ xem, không sửa được.";
  }
  updateGradeSave();
}

document.getElementById("grades-rows").addEventListener("input", updateGradeSave);
document.getElementById("grades-rows").addEventListener("keydown", (event) => {
  const input = event.target.closest("input.score-input");
  if (!input || event.key !== "Enter") return;
  event.preventDefault();
  const next = document.querySelector(`#grades-rows input[data-row="${Number(input.dataset.row) + (event.shiftKey ? -1 : 1)}"][data-col="${input.dataset.col}"]`);
  if (next) { next.focus(); next.select(); }
});

document.getElementById("grades-save").addEventListener("click", async (event) => {
  const items = gradeChanges().map(({ enrollment_id, component, score }) => ({ enrollment_id, component, score }));
  if (!items.length) return;
  event.target.disabled = true;
  try {
    const res = await apiPut(`/teaching/sections/${currentSectionId}/grades`, { items });
    currentDetail = res.detail;
    renderGrades();
    flash(`Đã lưu điểm cho ${res.changed} sinh viên. AI Agent sẽ tự cập nhật nguy cơ trong vài phút.`);
  } catch (error) {
    flash(error, true);
    updateGradeSave();
  }
});

// Rời trang khi còn điểm chưa lưu: hỏi lại
addEventListener("beforeunload", (event) => {
  if (currentMode === "grades" && gradeChanges().length) event.preventDefault();
});

// ------------------------------------------------------------------ điểm danh
let attData = null;

async function loadSessions() {
  const select = document.getElementById("session-select");
  select.innerHTML = "<option>Đang tải...</option>";
  try {
    const data = await apiGet(`/teaching/sections/${currentSectionId}/sessions`);
    const past = data.sessions.filter((x) => !x.upcoming);
    select.innerHTML = data.sessions.map((x) => `<option value="${x.id}" ${x.upcoming ? "disabled" : ""}>
      Buổi ${x.no} · ${x.date.split("-").reverse().join("/")} · ${x.upcoming ? "chưa tới" : x.recorded ? `đã điểm danh ${x.recorded}/${data.n_students}` : "chưa điểm danh"}</option>`).join("");
    // Mặc định: buổi gần nhất đã diễn ra mà chưa điểm danh đủ, không có thì buổi gần nhất
    const pick = past.find((x) => x.recorded < data.n_students) ?? past[past.length - 1];
    if (pick) {
      select.value = pick.id;
      loadAttendance(pick.id);
    } else {
      document.getElementById("att-rows").innerHTML = '<tr class="empty-row"><td colspan="5">Chưa có buổi học nào diễn ra.</td></tr>';
    }
  } catch (error) {
    flash(error, true);
  }
}

async function loadAttendance(sessionId) {
  document.getElementById("att-rows").innerHTML = '<tr class="empty-row"><td colspan="5">Đang tải...</td></tr>';
  try {
    attData = await apiGet(`/teaching/sections/${currentSectionId}/sessions/${sessionId}`);
    renderAttendance();
  } catch (error) {
    flash(error, true);
  }
}

function renderAttendance() {
  const limit = Math.floor(attData.ban_ratio * attData.total_sessions);
  const locked = !currentDetail.editable || attData.session.upcoming;
  document.getElementById("att-rows").innerHTML = attData.students.map((s) => {
    const options = ATT_STATUS.map(([value, label]) => `<label class="seg ${value}">
        <input type="radio" name="att-${s.enrollment_id}" value="${value}" ${s.status === value ? "checked" : ""} ${locked ? "disabled" : ""} />
        <span>${label}</span></label>`).join("");
    const near = s.absences >= limit ? "score-fail" : s.absences >= limit - 1 ? "warn-text" : "";
    return `<tr data-e="${s.enrollment_id}" data-orig="${s.status ?? ""}">
      <td>${escapeHtml(s.student_code)}</td><td class="nowrap">${escapeHtml(s.full_name)}</td><td class="nowrap">${escapeHtml(s.class_code)}</td>
      <td><div class="seg-group">${options}</div></td>
      <td class="num ${near}" title="Vắng quá ${limit} buổi là bị cấm thi">${s.absences}/${attData.total_sessions}</td>
    </tr>`;
  }).join("");
  updateAttSave();
}

function attChanges() {
  return [...document.querySelectorAll("#att-rows tr[data-e]")].map((tr) => {
    const checked = tr.querySelector("input:checked");
    return checked && checked.value !== tr.dataset.orig ? { enrollment_id: Number(tr.dataset.e), status: checked.value } : null;
  }).filter(Boolean);
}

function updateAttSave() {
  const n = attChanges().length;
  const unset = [...document.querySelectorAll("#att-rows tr[data-e]")].filter((tr) => !tr.querySelector("input:checked")).length;
  const button = document.getElementById("att-save");
  button.disabled = !n;
  button.innerHTML = `<i class="fas fa-floppy-disk"></i> Lưu điểm danh${n ? ` (${n})` : ""}`;
  document.getElementById("att-all-present").disabled = !unset;
}

document.getElementById("att-rows").addEventListener("change", updateAttSave);
document.getElementById("session-select").addEventListener("change", (e) => loadAttendance(Number(e.target.value)));
document.getElementById("att-all-present").addEventListener("click", () => {
  document.querySelectorAll("#att-rows tr[data-e]").forEach((tr) => {
    if (!tr.querySelector("input:checked")) {
      const present = tr.querySelector('input[value="present"]');
      if (!present.disabled) present.checked = true;
    }
  });
  updateAttSave();
});
document.getElementById("att-save").addEventListener("click", async (event) => {
  const items = attChanges();
  if (!items.length) return;
  event.target.disabled = true;
  try {
    attData = await apiPut(`/teaching/sections/${currentSectionId}/sessions/${attData.session.id}`, { items });
    renderAttendance();
    flash(`Đã lưu điểm danh buổi ${attData.session.no} (${items.length} sinh viên).`);
    loadSessionsKeep();
  } catch (error) {
    flash(error, true);
    updateAttSave();
  }
});

// Cập nhật số đã điểm danh trong danh sách buổi, giữ buổi đang chọn
async function loadSessionsKeep() {
  const select = document.getElementById("session-select");
  const keep = select.value;
  const data = await apiGet(`/teaching/sections/${currentSectionId}/sessions`);
  const opt = data.sessions.find((x) => String(x.id) === keep);
  if (opt) select.selectedOptions[0].textContent =
    `Buổi ${opt.no} · ${opt.date.split("-").reverse().join("/")} · đã điểm danh ${opt.recorded}/${data.n_students}`;
}

// ------------------------------------------------------------------ nhật ký sửa điểm
async function loadLog() {
  const rows = document.getElementById("log-rows");
  rows.innerHTML = '<tr class="empty-row"><td colspan="7">Đang tải...</td></tr>';
  try {
    const log = await apiGet(`/teaching/sections/${currentSectionId}/grade-log`);
    rows.innerHTML = log.map((x) => `<tr>
      <td>${escapeHtml(x.at.replace("T", " "))}</td><td>${escapeHtml(x.by ?? "–")}</td>
      <td><span class="chip ${x.action === "Xóa" ? "bad" : x.action === "Sửa" ? "warn" : "ok"}">${x.action}</span></td>
      <td>${escapeHtml(x.student_code)}</td><td>${escapeHtml(x.component)}</td>
      <td class="num">${formatScore(x.old)}</td><td class="num"><b>${formatScore(x.new)}</b></td>
    </tr>`).join("") || '<tr class="empty-row"><td colspan="7">Chưa có lần nhập / sửa điểm nào trên web cho lớp này.</td></tr>';
  } catch (error) {
    flash(error, true);
  }
}

// ------------------------------------------------------------------ chuyển chế độ, chọn lớp
function flash(messageOrError, isError = false) {
  const box = document.getElementById("detail-message");
  box.hidden = false;
  if (isError) showError(box, messageOrError);
  else showSuccess(box, messageOrError);
}

function setMode(mode) {
  if (currentMode === "grades" && mode !== "grades" && gradeChanges().length &&
      !confirm("Còn điểm chưa lưu. Bỏ các thay đổi này?")) return;
  currentMode = mode;
  document.querySelectorAll("#detail-tabs .tab").forEach((t) => t.classList.toggle("active", t.dataset.mode === mode));
  for (const m of ["view", "grades", "attendance", "log"]) document.getElementById(`mode-${m}`).hidden = m !== mode;
  document.getElementById("detail-message").hidden = true;
  const params = new URLSearchParams(location.search);
  if (currentSectionId) params.set("section", currentSectionId);
  if (mode === "view") params.delete("mode"); else params.set("mode", mode);
  history.replaceState(null, "", `?${params}`);
  if (typeof refreshMenuCurrent === "function") refreshMenuCurrent();
  if (!currentDetail) return;
  if (mode === "view") renderDetail();
  if (mode === "grades") renderGrades();
  if (mode === "attendance") loadSessions();
  if (mode === "log") loadLog();
}

document.querySelectorAll("#detail-tabs .tab").forEach((tab) => tab.addEventListener("click", () => setMode(tab.dataset.mode)));

async function selectSection(id) {
  if (currentMode === "grades" && gradeChanges().length && !confirm("Còn điểm chưa lưu. Bỏ các thay đổi này?")) return;
  currentSectionId = id;
  currentDetail = null;
  document.querySelectorAll(".section-card").forEach((c) => c.classList.toggle("selected", Number(c.dataset.id) === id));
  document.getElementById("mode-hint").hidden = true;
  const panel = document.getElementById("detail");
  panel.hidden = false;
  document.getElementById("detail-rows").innerHTML = '<tr class="empty-row"><td>Đang tải...</td></tr>';
  try {
    currentDetail = await apiGet(`/teaching/sections/${id}`);
    const { section, students } = currentDetail;
    document.getElementById("detail-title").textContent = `${section.course_name} · ${section.code}`;
    const flagged = students.filter(needsAttention).length;
    const aiOnly = students.filter((s) => s.ai?.source === "ai").length;
    document.getElementById("detail-meta").textContent =
      `${students.length} sinh viên · ${flagged} cần chú ý` + (aiOnly ? ` (${aiOnly} do AI phát hiện sớm)` : "");
    setMode(currentMode);
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showError(document.getElementById("error"), error);
  }
}

async function loadSections() {
  try {
    const sections = await apiGet("/teaching/sections");
    const wanted = Number(new URLSearchParams(location.search).get("section"));
    // Mở từ menu "Nhập điểm" / "Điểm danh" khi chỉ dạy một lớp: chọn luôn lớp đó
    const selected = sections.find((s) => s.id === wanted)?.id ??
      (currentMode !== "view" && sections.length === 1 ? sections[0].id : undefined);
    renderSections(sections, selected);
    if (selected) selectSection(selected);
    else if (MODE_HINT[currentMode] && sections.length) {
      const hint = document.getElementById("mode-hint");
      hint.hidden = false;
      hint.innerHTML = `<i class="fas fa-hand-pointer"></i> ${MODE_HINT[currentMode]}`;
    }
  } catch (error) {
    document.getElementById("sections").innerHTML = "";
    showError(document.getElementById("error"), error);
  }
}

document.getElementById("attention-only").addEventListener("change", () => currentDetail && renderDetail());
loadSections();
