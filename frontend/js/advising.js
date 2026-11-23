// Trang "Lớp chủ nhiệm" (CVHT): toàn bộ sinh viên lớp hành chính, kết quả tích lũy và tình hình học kỳ hiện tại.
let advising = null;
const AI_LEVEL_CHIP = { high: ["bad", "Cao"], medium: ["warn", "Trung bình"], low: ["ok", "Thấp"] };
// Cần chú ý: vi phạm luật ở môn nào đó, hoặc AI Agent dự báo nguy cơ trượt ở môn nào đó
const flaggedStudent = (s) => s.attention.length > 0 || s.ai_flagged_courses.length > 0;

function aiWorstCell(s) {
  const w = s.ai_worst;
  if (!w) return '<span class="muted">–</span>';
  const [cls, label] = AI_LEVEL_CHIP[w.level];
  const why = w.factors.map((f) => `${f.label}: ${f.value}`).join("\n");
  return `<span class="ai-cell" title="${escapeHtml(why)}"><b>${Math.round(w.proba * 100)}%</b>
      <span class="chip ${cls}">${label}</span></span><div class="muted">${escapeHtml(w.course_code)} ${escapeHtml(w.course_name)}</div>
      ${s.ai_only_courses.length ? `<span class="chip ai"><i class="fas fa-wand-magic-sparkles"></i> AI phát hiện sớm: ${s.ai_only_courses.map(escapeHtml).join(", ")}</span>` : ""}`;
}

function render() {
  const attentionOnly = document.getElementById("attention-only").checked;
  const classCode = document.getElementById("class-select").value;
  const students = advising.students.filter((s) => (!classCode || s.class_code === classCode));
  const shown = students.filter((s) => !attentionOnly || flaggedStudent(s));

  const gpas = students.map((s) => s.gpa4).filter((g) => g != null);
  document.getElementById("stat-total").textContent = students.length;
  document.getElementById("stat-attention").textContent = students.filter(flaggedStudent).length;
  document.getElementById("stat-ai").textContent =
    `${students.filter((s) => s.ai_only_courses.length).length} SV do AI phát hiện sớm`;
  document.getElementById("stat-debt").textContent = students.filter((s) => s.failed_courses.length).length;
  document.getElementById("stat-gpa").textContent = gpas.length
    ? (gpas.reduce((a, b) => a + b, 0) / gpas.length).toFixed(2) : "–";

  document.getElementById("rows").innerHTML = shown
    .map((s) => `<tr class="${s.attention.length ? "row-warn" : s.ai_only_courses.length ? "row-ai" : ""}">
        <td><a href="student.html?id=${s.student_id}" title="Hồ sơ sinh viên">${escapeHtml(s.student_code)}</a></td>
        <td>${escapeHtml(s.full_name)}</td>
        <td>${escapeHtml(s.class_code)}</td>
        <td class="num${s.gpa4 != null && s.gpa4 < 2 ? " score-fail" : ""}">${s.gpa4?.toFixed(2) ?? ""}</td>
        <td class="num">${s.credits_passed}</td>
        <td><div class="chips">${s.failed_courses.map((c) => `<span class="chip bad">${escapeHtml(c)}</span>`).join("")}</div></td>
        <td class="num">${formatPercent(s.avg_absence_rate)}</td>
        <td><div class="chips">${s.attention.map((a) => `<span class="chip warn">${escapeHtml(a)}</span>`).join("")}</div></td>
        <td>${aiWorstCell(s)}</td>
      </tr>`)
    .join("") || '<tr class="empty-row"><td colspan="9">Không có sinh viên nào.</td></tr>';
}

async function load() {
  try {
    advising = await apiGet("/advising/students");
    document.getElementById("title").textContent = `Lớp ${advising.classes.join(", ")} · ${advising.semester}`;
    const select = document.getElementById("class-select");
    if (advising.classes.length > 1) {
      select.innerHTML = '<option value="">Tất cả lớp</option>' +
        advising.classes.map((c) => `<option>${escapeHtml(c)}</option>`).join("");
      select.hidden = false;
    }
    render();
  } catch (error) {
    document.getElementById("rows").innerHTML = "";
    showError(document.getElementById("error"), error);
  }
}

document.getElementById("attention-only").addEventListener("change", () => advising && render());
document.getElementById("class-select").addEventListener("change", () => advising && render());
load();
