// Trang "Kết quả học tập" của sinh viên: điểm từng môn qua các học kỳ, giống bảng điểm trên cổng thông tin.
const COMPONENT_ORDER = ["CC", "KT1", "KT2", "KT3", "THI"];
const COMPONENT_LABEL = { CC: "CC", KT1: "KT1", KT2: "KT2", KT3: "KT3", THI: "Thi" };

function statusChips(c) {
  const chips = [];
  if (c.attempt_no > 1) chips.push(`<span class="chip info">Học lại lần ${c.attempt_no}</span>`);
  if (c.status === "studying") {
    chips.push('<span class="chip">Đang học</span>');
    if (c.exam_unreachable) chips.push('<span class="chip bad">Không thể qua môn</span>');
    else if (c.min_exam_score != null) {
      const cls = c.min_exam_score >= 7 ? "bad" : c.min_exam_score >= 5 ? "warn" : "ok";
      chips.push(`<span class="chip ${cls}" title="Điểm thi tối thiểu để TBCHP đạt 4.0">Cần thi ≥ ${formatScore(c.min_exam_score)}</span>`);
    }
  } else if (c.status === "banned_exam") chips.push('<span class="chip bad">Cấm thi</span>');
  else if (c.passed) chips.push('<span class="chip ok">Đạt</span>');
  else chips.push('<span class="chip bad">Chưa đạt</span>');
  return `<div class="chips">${chips.join("")}</div>`;
}

function renderSemester(sem) {
  const codes = COMPONENT_ORDER.filter((code) => sem.courses.some((c) => c.components.some((x) => x.code === code)));
  const head = codes.map((code) => `<th class="num">${COMPONENT_LABEL[code]}</th>`).join("");
  const rows = sem.courses
    .map((c) => {
      const weights = Object.fromEntries(c.components.map((x) => [x.code, x.weight]));
      const cells = codes
        .map((code) => {
          if (!(code in weights)) return '<td class="num score-pending">—</td>';
          const score = c.scores[code];
          const title = `${code}: trọng số ${Math.round(weights[code] * 100)}%`;
          return `<td class="num" title="${title}">${score == null ? "" : formatScore(score)}</td>`;
        })
        .join("");
      const failed = c.final_score != null && !c.passed;
      return `<tr>
        <td>${escapeHtml(c.course_code)}</td>
        <td>${escapeHtml(c.course_name)}</td>
        <td class="num">${c.credits}</td>
        ${cells}
        <td class="num${failed ? " score-fail" : ""}"><b>${formatScore(c.final_score)}</b></td>
        <td class="num${failed ? " score-fail" : ""}">${c.letter_grade ?? ""}</td>
        <td>${statusChips(c)}</td>
      </tr>`;
    })
    .join("");

  const s = sem.summary;
  const meta = s
    ? `<span>ĐTB học kỳ <b>${fmt2(s.gpa4)}</b> (hệ 4)</span><span>Xếp loại <b>${escapeHtml(s.rank ?? "–")}</b></span>`
    : '<span>Học kỳ đang diễn ra, chưa có điểm tổng kết</span>';
  return `<section class="panel">
    <div class="panel-header">
      <h3>${escapeHtml(sem.name)}${sem.is_current ? ' <span class="chip info">Hiện tại</span>' : ""}</h3>
      <div class="semester-meta">${meta}</div>
    </div>
    <div class="table-scroll"><table>
      <thead><tr><th>Mã HP</th><th>Tên học phần</th><th class="num">TC</th>${head}
        <th class="num">TBCHP</th><th class="num">Điểm chữ</th><th>Trạng thái</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
    ${s ? semesterSummaryBlock(s) : ""}
  </section>`;
}

const fmt2 = (v) => (v == null ? "–" : Number(v).toFixed(2));

function warningText(w) {
  if (!w) return "–";
  return w.is_warned
    ? `<span class="chip bad">Có</span> <span class="muted">${w.reasons.map(escapeHtml).join("; ")}</span>`
    : '<span class="chip ok">Không</span>';
}

// Khối tổng kết cuối mỗi học kỳ, giống cổng thông tin: học kỳ bên trái, tích lũy bên phải
function semesterSummaryBlock(s) {
  const row = (label, value) => `<div class="kv"><span>${label}</span><b>${value}</b></div>`;
  return `<div class="semester-summary">
    <div>
      ${row("Điểm trung bình học kỳ hệ 10", fmt2(s.gpa10))}
      ${row("Điểm trung bình học kỳ hệ 4", fmt2(s.gpa4))}
      ${row("Số tín chỉ đăng ký", s.credits_registered)}
      ${row("Số tín chỉ đạt", s.credits_passed)}
      ${row("Số tín chỉ chưa đạt", s.credits_failed)}
      ${row("Xếp loại học lực học kỳ", escapeHtml(s.rank ?? "–"))}
    </div>
    <div>
      ${row("Điểm trung bình tích lũy hệ 10", fmt2(s.cum_gpa10))}
      ${row("Điểm trung bình tích lũy hệ 4", fmt2(s.cum_gpa4))}
      ${row("Số tín chỉ tích lũy", s.cum_credits)}
      ${row("Số tín chỉ nợ", s.owed_credits)}
      ${row("Xếp loại học lực tích lũy", escapeHtml(s.cum_rank ?? "–"))}
      ${row("Cảnh báo học tập", warningText(s.warning))}
    </div>
  </div>`;
}

function renderOverall(data) {
  const c = data.cumulative;
  const st = data.student;
  document.getElementById("student-info").textContent = `${st.code} · ${st.full_name} · Lớp ${st.class_code}`;
  const card = (label, value, cls = "") => `<div class="summary-card ${cls}"><div class="summary-value">${value}</div><div class="summary-label">${label}</div></div>`;
  document.getElementById("overall-grid").innerHTML = [
    card("ĐTB tích lũy hệ 10", fmt2(c.gpa10)),
    card("ĐTB tích lũy hệ 4", fmt2(c.gpa4)),
    card("Xếp loại học lực", escapeHtml(c.rank ?? "–")),
    card("Tín chỉ tích lũy", c.credits_passed),
    card("Tín chỉ nợ", c.credits_owed, c.credits_owed ? "bad" : ""),
    card("Học kỳ đã hoàn thành", c.semesters_done),
  ].join("");
  const owed = c.failed_not_retaken;
  document.getElementById("overall-warning").innerHTML =
    (c.warning?.is_warned
      ? `<div class="alert-error"><i class="fas fa-triangle-exclamation"></i><span>Học kỳ gần nhất thuộc diện <b>cảnh báo học tập</b>: ${c.warning.reasons.map(escapeHtml).join("; ")}.</span></div>`
      : "") +
    (owed.length ? `<p class="note">Học phần đang nợ (chưa học lại đạt): ${owed.map(escapeHtml).join(", ")}</p>` : "");

  const done = data.semesters.filter((sem) => sem.summary);
  document.getElementById("overall-rows").innerHTML = done.map((sem) => {
    const s = sem.summary;
    return `<tr>
      <td>${escapeHtml(sem.name)}</td>
      <td class="num">${fmt2(s.gpa10)}</td><td class="num">${fmt2(s.gpa4)}</td>
      <td class="num">${fmt2(s.cum_gpa10)}</td><td class="num"><b>${fmt2(s.cum_gpa4)}</b></td>
      <td class="num">${s.credits_registered}</td><td class="num">${s.credits_passed}</td><td class="num">${s.cum_credits}</td>
      <td>${escapeHtml(s.rank ?? "–")}</td><td>${escapeHtml(s.cum_rank ?? "–")}</td>
      <td>${warningText(s.warning)}</td>
    </tr>`;
  }).join("") || '<tr class="empty-row"><td colspan="11">Chưa có học kỳ nào có điểm tổng kết.</td></tr>';
}

async function loadResults() {
  const container = document.getElementById("semesters");
  try {
    const data = await apiGet("/me/results");
    renderOverall(data);
    container.innerHTML = [...data.semesters].reverse().map(renderSemester).join("") ||
      '<p class="muted">Chưa có kết quả học tập.</p>';
    // Dữ liệu về sau khi trang đã hiện: cho hiện dần thay vì nháy
    for (const id of ["overall-grid", "overall-rows", "semesters"]) document.getElementById(id).classList.add("fade-in");
  } catch (error) {
    container.innerHTML = "";
    showError(document.getElementById("error"), error);
  }
}

loadResults();
