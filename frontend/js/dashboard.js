// Trang Tổng quan (CSDL v2): học kỳ hiện tại theo lần chạy AI Agent gần nhất, chuyên cần,
// và kết quả học tập qua các học kỳ. Quản trị thấy toàn trường; giảng viên thấy lớp mình dạy và lớp chủ nhiệm.

// Màu đã kiểm tra phân biệt được cả với người mù màu (red / violet / amber không đứng cạnh nhau sai thứ tự)
const C = {
  high: "#dc2626", ai: "#7c3aed", rule: "#d97706", none: "#e2e8f0",
  series: "#2a78d6", grid: "#eef2f7", text: "#64748b",
};
const SOURCE = { both: "Luật + AI", rule: "Luật quy chế", ai: "AI phát hiện sớm", none: "–" };
const LEVEL = { high: ["bad", "Cao"], medium: ["warn", "Trung bình"], low: ["ok", "Thấp"] };
const pct = (v, digits = 0) => (v == null ? "–" : `${(v * 100).toFixed(digits)}%`);
// Xác suất: không làm tròn 0.998 thành "100%" (mô hình không bao giờ chắc chắn tuyệt đối)
const proba = (p) => (p >= 0.995 ? "&gt;99%" : `${Math.round(p * 100)}%`);

Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
Chart.defaults.color = C.text;
Chart.defaults.plugins.tooltip.padding = 10;
Chart.defaults.plugins.legend.labels.boxWidth = 12;
Chart.defaults.plugins.legend.labels.boxHeight = 12;

const axes = (opts = {}) => ({
  grid: { color: C.grid, drawTicks: false },
  border: { display: false },
  ticks: { padding: 6, precision: 0 },
  beginAtZero: true,
  ...opts,
});

function renderContext(d) {
  const run = d.run
    ? `AI Agent cập nhật lúc ${d.run.finished_at.replace("T", " ")}`
    : "AI Agent chưa chạy trong học kỳ này";
  document.getElementById("context").innerHTML =
    `<b>${escapeHtml(d.semester.name)}</b> · tuần ${d.semester.week}/${d.semester.total_weeks} · ` +
    `<span class="chip info">${escapeHtml(d.scope)}</span> · ${run}`;
}

function renderCards(d) {
  const c = d.cards;
  document.getElementById("stat-students").textContent = c.students;
  document.getElementById("sub-students").textContent = `${c.sections} lớp học phần · ${c.enrollments} lượt đăng ký`;
  document.getElementById("stat-flagged").textContent = c.flagged_students;
  document.getElementById("sub-flagged").innerHTML =
    `${pct(c.predicted_students ? c.flagged_students / c.predicted_students : null)} · ` +
    `<span style="color: var(--ai)">${c.ai_students} do AI phát hiện sớm</span>`;
  document.getElementById("stat-high").textContent = c.high_students;
  document.getElementById("sub-high").textContent = "có môn xác suất trượt cao";
  document.getElementById("stat-warned").textContent = c.warned_students;
  document.getElementById("sub-warned").textContent = "học kỳ gần nhất có điểm";
  document.getElementById("stat-absent").textContent = pct(c.attendance.absent_rate, 1);
  document.getElementById("sub-absent").textContent = `${c.attendance.over_limit} SV quá ngưỡng cấm thi`;

  // Giảng viên: trang Sinh viên chỉ có lớp chủ nhiệm, nên danh sách nguy cơ xem ở trang AI Agent
  if (CURRENT_USER.role !== "admin") {
    const advises = CURRENT_USER.advised_classes?.length > 0;
    document.getElementById("card-students").href = advises ? "manage-students.html" : "teaching.html";
    for (const id of ["card-flagged", "card-high", "top-all"]) document.getElementById(id).href = "agent.html";
  }
}

function renderClassChart(rows) {
  const stack = [
    ["high", "Nguy cơ cao", C.high],
    ["ai", "Chỉ AI phát hiện", C.ai],
    ["rule", "Vi phạm luật quy chế", C.rule],
    ["none", "Bình thường", C.none],
  ];
  new Chart(document.getElementById("chart-class"), {
    type: "bar",
    data: {
      labels: rows.map((r) => r.class_code.split(" ")),
      datasets: stack.map(([key, label, color]) => ({
        label, data: rows.map((r) => r[key]), backgroundColor: color,
        borderColor: "#fff", borderWidth: 2, borderSkipped: false, maxBarThickness: 44,
      })),
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { position: "bottom" },
        tooltip: { callbacks: { title: (items) => rows[items[0].dataIndex].class_code,
                                footer: (items) => `Tổng: ${rows[items[0].dataIndex].total} sinh viên` } },
      },
      scales: { x: axes({ stacked: true, grid: { display: false }, ticks: { autoSkip: false, maxRotation: 0 } }),
                y: axes({ stacked: true }) },
    },
  });
}

function renderCourseChart(rows) {
  new Chart(document.getElementById("chart-course"), {
    type: "bar",
    data: {
      labels: rows.map((r) => r.code),
      datasets: [{
        label: "Tỷ lệ cần chú ý", data: rows.map((r) => Math.round(r.rate * 1000) / 10),
        backgroundColor: C.series, borderRadius: 4, borderSkipped: "start", maxBarThickness: 20,
      }],
    },
    options: {
      indexAxis: "y",
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => `${rows[items[0].dataIndex].code} · ${rows[items[0].dataIndex].name}`,
            label: (item) => {
              const r = rows[item.dataIndex];
              return [`${item.raw}% (${r.flagged}/${r.n} lượt)`, `AI phát hiện sớm: ${r.ai}`,
                      `Xác suất trượt TB: ${pct(r.avg_proba)}`];
            },
          },
        },
      },
      scales: { x: axes({ ticks: { callback: (v) => `${v}%` } }), y: axes({ grid: { display: false } }) },
    },
  });
}

function renderGpa(rows) {
  const short = (name) => name.replace(/Học kỳ (\w+) năm học 20(\d\d)-20(\d\d)/, "HK$1 $2-$3");
  new Chart(document.getElementById("chart-gpa"), {
    type: "line",
    data: {
      labels: rows.map((r) => short(r.name)),
      datasets: [{
        label: "ĐTB học kỳ", data: rows.map((r) => r.gpa4), borderColor: C.series, backgroundColor: C.series,
        borderWidth: 2, pointRadius: 4, pointHoverRadius: 6, tension: 0.25,
      }],
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (item) => {
              const r = rows[item.dataIndex];
              return [`ĐTB: ${r.gpa4?.toFixed(2)}`, `Tỷ lệ tín chỉ đạt: ${pct(r.pass_rate, 1)}`,
                      `ĐTB dưới 2.0: ${r.weak}/${r.n_students}`, `Bị cảnh báo: ${r.warned}/${r.n_students}`];
            },
          },
        },
      },
      scales: { x: axes({ grid: { display: false } }), y: axes({ min: 0, max: 4, ticks: { stepSize: 1 } }) },
    },
  });
  document.getElementById("gpa-rows").innerHTML = rows.map((r) => `<tr>
      <td class="nowrap" title="${escapeHtml(r.name)}">${escapeHtml(short(r.name))}</td><td class="num">${r.n_students}</td>
      <td class="num">${r.gpa4?.toFixed(2) ?? "–"}</td><td class="num">${pct(r.pass_rate, 1)}</td>
      <td class="num${r.warned ? " score-fail" : ""}">${r.warned}</td>
    </tr>`).join("") || '<tr class="empty-row"><td colspan="5">Chưa có học kỳ nào có điểm tổng kết.</td></tr>';
}

function renderRanks(rows, reasons, warned) {
  const total = rows.reduce((s, r) => s + r.n, 0);
  document.getElementById("rank-meta").textContent = `${total} sinh viên có điểm`;
  new Chart(document.getElementById("chart-rank"), {
    type: "bar",
    data: {
      labels: rows.map((r) => r.rank),
      datasets: [{
        label: "Số sinh viên", data: rows.map((r) => r.n),
        // Yếu, Kém: màu cảnh báo (kèm nhãn trên trục, không chỉ dựa vào màu)
        backgroundColor: rows.map((r) => (r.rank === "Yếu" || r.rank === "Kém" ? C.high : C.series)),
        borderRadius: 4, borderSkipped: "start", maxBarThickness: 40,
      }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (item) => `${item.raw} sinh viên (${pct(total ? item.raw / total : null)})` } },
      },
      scales: { x: axes({ grid: { display: false } }), y: axes() },
    },
  });
  document.getElementById("reasons").innerHTML = reasons.length
    ? reasons.map(([label, n]) => `<div class="bar-row">
        <span>${escapeHtml(label)}</span>
        <div class="bar-track"><div class="bar-fill" style="width: ${Math.round((n / warned) * 100)}%"></div></div>
        <b>${n}</b></div>`).join("") + '<p class="note">Một sinh viên có thể bị cảnh báo vì nhiều lý do.</p>'
    : '<p class="muted">Không có sinh viên nào bị cảnh báo học tập.</p>';
}

function renderWeeks(rows) {
  const max = Math.max(...rows.map((r) => r.recorded), 0);
  new Chart(document.getElementById("chart-week"), {
    type: "line",
    data: {
      labels: rows.map((r) => `Tuần ${r.week}`),
      datasets: [{
        label: "Tỷ lệ vắng", data: rows.map((r) => Math.round(r.absent_rate * 1000) / 10),
        borderColor: C.series, backgroundColor: C.series, borderWidth: 2, pointRadius: 4, pointHoverRadius: 6,
        tension: 0.25,
        // Tuần đang học, chưa điểm danh đủ: nét đứt
        segment: { borderDash: (ctx) => (rows[ctx.p1DataIndex].recorded < 0.8 * max ? [5, 4] : undefined) },
      }],
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (item) => {
              const r = rows[item.dataIndex];
              const lines = [`Vắng: ${item.raw}%`, `Đi muộn: ${pct(r.late_rate, 1)}`, `${r.recorded} lượt điểm danh`];
              if (r.recorded < 0.8 * max) lines.push("Tuần này chưa điểm danh xong");
              return lines;
            },
          },
        },
      },
      scales: { x: axes({ grid: { display: false } }), y: axes({ ticks: { callback: (v) => `${v}%` } }) },
    },
  });
}

function renderTop(rows) {
  document.getElementById("top-rows").innerHTML = rows.map((s) => {
    const [cls, label] = LEVEL[s.level];
    return `<tr>
      <td><a href="student.html?id=${s.id}">${escapeHtml(s.student_code)}</a></td>
      <td class="nowrap">${escapeHtml(s.full_name)}</td>
      <td class="nowrap">${escapeHtml(s.class_code)}</td>
      <td>${escapeHtml(s.course)} <span class="muted">(mốc ${s.checkpoint})</span></td>
      <td class="nowrap"><b>${proba(s.proba)}</b> <span class="chip ${cls}">${label}</span></td>
      <td>${s.source === "ai" ? '<span class="chip ai"><i class="fas fa-wand-magic-sparkles"></i> AI phát hiện sớm</span>' : SOURCE[s.source]}</td>
      <td class="num">${s.flagged}</td>
    </tr>`;
  }).join("") || '<tr class="empty-row"><td colspan="7">Chưa có sinh viên nào cần chú ý.</td></tr>';
}

async function loadDashboard() {
  try {
    const d = await apiGet("/dashboard");
    renderContext(d);
    renderCards(d);
    renderClassChart(d.risk_by_class);
    renderCourseChart(d.risk_by_course);
    renderGpa(d.semesters);
    renderRanks(d.ranks, d.cards.warning_reasons, d.cards.warned_students);
    renderWeeks(d.attendance_by_week);
    renderTop(d.top_students);
  } catch (error) {
    document.getElementById("context").textContent = "";
    showError(document.getElementById("error"), error);
  }
}

loadDashboard();
