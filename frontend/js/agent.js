// Trang AI Agent: trạng thái, 5 tầng của lần chạy gần nhất, danh sách sinh viên cần chú ý theo nguồn phát hiện,
// kiểm chứng trên học kỳ cũ đã biết kết quả, nhật ký các lần chạy.

const LEVEL_INFO = {
  high: { label: "Cao", cls: "bad" },
  medium: { label: "Trung bình", cls: "warn" },
  low: { label: "Thấp", cls: "ok" },
};
const SOURCE_HINT = {
  ai: "Sinh viên chưa vi phạm luật nào (đi học đủ, điểm quá trình chưa dưới 4) nhưng mô hình AI dự báo nguy cơ trượt cao. Đây là những trường hợp chỉ AI phát hiện được, cần trao đổi sớm.",
  both: "Vừa vi phạm luật quy chế vừa được AI dự báo nguy cơ: những trường hợp chắc chắn nhất.",
  rule: "Luật gắn cờ nhưng AI dự báo nguy cơ thấp (ví dụ vắng nhiều nhưng điểm vẫn tốt). Trên học kỳ kiểm chứng, phần lớn các trường hợp này cuối cùng vẫn qua môn.",
  "": "Mọi lượt học cần chú ý, xếp theo xác suất trượt do AI dự báo.",
};
const RUN_STATUS = { success: "ok", failed: "bad", running: "warn" };

const agentState = { source: "ai", q: "", backtest: null, btChart: null, cp: "M1" };

const fmtPct = (v) => (v == null ? "–" : `${Math.round(v * 100)}%`);
const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" }) : "–");
const fmtNum = (v) => (v == null ? "–" : Number(v).toLocaleString("vi-VN"));

// Email cảnh báo của lần chạy (gửi ở luồng nền ngay sau khi Agent chạy xong)
function emailLine(e) {
  if (!e) return "";
  const done = e.mode === "smtp" ? `${fmtNum(e.sent)} email đã gửi` : `${fmtNum(e.outbox)} email (chế độ thử)`;
  const fail = e.failed ? `, <span class="score-fail">${fmtNum(e.failed)} lỗi</span>` : "";
  return `<li><a href="emails.html">${done}</a>${fail}; ${fmtNum(e.unlinked)} người chưa liên kết email</li>`;
}

async function loadAgentPage() {
  const error = document.getElementById("error");
  try {
    const overview = await apiGet("/agent/overview");
    renderOverview(overview);
    await Promise.all([loadList(), loadBacktest(), loadRuns()]);
  } catch (err) {
    showError(error, err);
  }
}

// ------------------------------------------------------------------ trạng thái + số liệu chính
function renderOverview(o) {
  document.getElementById("hero-semester").textContent = o.semester;
  const btn = document.getElementById("run-btn");
  btn.hidden = !o.can_run;
  const run = o.run;
  if (!run) {
    document.getElementById("hero-run").textContent = o.models_ready
      ? "Agent chưa chạy lần nào cho học kỳ này."
      : "Chưa có mô hình cho Agent. Chạy: python ml/train_dainam.py";
    return;
  }
  const s = run.stats;
  document.getElementById("hero-run").innerHTML =
    `Lần chạy gần nhất: <b>${fmtTime(run.finished_at)}</b> (${escapeHtml(run.trigger_label.toLowerCase())}), ` +
    `xét dữ liệu tính đến ${fmtTime(s.as_of)}, mất ${s.duration_s} giây.`;

  const c = s.combined;
  document.getElementById("k-flagged").textContent = fmtNum(c.flagged);
  document.getElementById("k-flagged-sub").textContent = `${fmtNum(c.students)} sinh viên / ${fmtNum(s.model.predicted)} lượt học`;
  document.getElementById("k-ai").textContent = fmtNum(c.ai);
  document.getElementById("k-rule").textContent = fmtNum(c.rule);
  document.getElementById("k-alerts").textContent = fmtNum(s.report.alerts);
  document.getElementById("k-alerts-sub").textContent =
    `GV ${fmtNum(s.report.lecturer)} · CVHT ${fmtNum(s.report.advisor)} · SV ${fmtNum(s.report.student)}`;
  renderPipeline(s);
}

function renderPipeline(s) {
  const o = s.observe;
  const cps = Object.entries(o.by_checkpoint).filter(([, n]) => n > 0)
    .map(([cp, n]) => `${cp}: ${n} lớp`).join(" · ");
  const reasons = Object.entries(s.rules.by_reason).slice(0, 3)
    .map(([r, n]) => `<li>${escapeHtml(r)} <b>${fmtNum(n)}</b></li>`).join("");
  const models = Object.entries(s.model.models)
    .map(([cp, m]) => `<li>${cp}: ${escapeHtml(m.model.replaceAll("_", " "))} <span class="muted">(${m.n} lượt)</span></li>`).join("");
  const f = s.follow;
  const stages = [
    { n: "①", title: "Quan sát", icon: "fa-eye", main: `${o.sections} lớp học phần`, sub: cps,
      list: `<li>Điểm mới nhập: <b>${fmtNum(o.new_grades)}</b></li><li>Lượt điểm danh mới: <b>${fmtNum(o.new_attendance)}</b></li>` },
    { n: "②", title: "Luật quy chế", icon: "fa-scale-balanced", main: `${fmtNum(s.rules.flagged)} vi phạm`, sub: "trường hợp chắc chắn", list: reasons },
    { n: "③", title: "Mô hình AI", icon: "fa-brain", main: `${fmtNum(s.model.predicted)} dự báo`,
      sub: `${fmtNum(s.model.high)} cao · ${fmtNum(s.model.medium)} trung bình`, list: models, accent: true },
    { n: "④", title: "Báo cáo", icon: "fa-paper-plane", main: `${fmtNum(s.report.alerts)} cảnh báo`,
      sub: `cho ${fmtNum(s.report.enrollments)} lượt học`,
      list: `<li>Giảng viên bộ môn <b>${fmtNum(s.report.lecturer)}</b></li><li>CVHT <b>${fmtNum(s.report.advisor)}</b></li><li>Sinh viên (lời nhắc) <b>${fmtNum(s.report.student)}</b></li>${emailLine(s.email)}` },
    { n: "⑤", title: "Theo dõi", icon: "fa-chart-line", main: f.compared ? `${fmtNum(f.improved)} cải thiện` : "Lần chạy đầu tiên",
      sub: f.compared ? `so với lần trước (${fmtNum(f.compared)} lượt)` : "chưa có lần trước để so",
      list: f.compared ? `<li class="good">Cải thiện <b>${fmtNum(f.improved)}</b></li><li class="bad">Xấu đi <b>${fmtNum(f.worse)}</b></li><li>Giữ nguyên <b>${fmtNum(f.same)}</b></li>` : "" },
  ];
  document.getElementById("pipeline").innerHTML = stages.map((st) => `
    <div class="stage${st.accent ? " accent" : ""}">
      <div class="stage-head"><span class="stage-num">${st.n}</span><i class="fas ${st.icon}"></i> ${st.title}</div>
      <div class="stage-main">${st.main}</div>
      <div class="stage-sub">${escapeHtml(st.sub)}</div>
      <ul class="stage-list">${st.list}</ul>
    </div>`).join("");
  document.getElementById("pipeline-meta").textContent = `Học kỳ ${s.semester}`;
}

// ------------------------------------------------------------------ danh sách
async function loadList() {
  const params = new URLSearchParams({ limit: 300 });
  if (agentState.source) params.set("source", agentState.source);
  if (agentState.q) params.set("q", agentState.q);
  const data = await apiGet(`/agent/predictions?${params}`);
  for (const el of document.querySelectorAll("[data-count]")) {
    const n = data.counts[el.dataset.count];
    el.textContent = n ? n : "";
  }
  document.getElementById("tab-hint").textContent = SOURCE_HINT[agentState.source];
  const rows = document.getElementById("rows");
  if (!data.items.length) {
    rows.innerHTML = `<tr class="empty-row"><td colspan="6">Không có sinh viên nào trong mục này.</td></tr>`;
    return;
  }
  rows.innerHTML = data.items.map(renderRow).join("");
}

function renderRow(it) {
  const level = LEVEL_INFO[it.level];
  const tag = it.source === "ai" ? `<span class="chip ai"><i class="fas fa-wand-magic-sparkles"></i> AI phát hiện sớm</span>` : "";
  const factors = it.factors.length
    ? `<ul class="factor-list">${it.factors.map((f) => `<li><b>${escapeHtml(f.label)}</b>: ${escapeHtml(f.value)} <span class="muted">(thường gặp ${escapeHtml(f.typical)})</span></li>`).join("")}</ul>`
    : `<span class="muted">Không có yếu tố nổi bật</span>`;
  const rules = it.rule_flags.length
    ? `<div class="chips">${it.rule_flags.map((r) => `<span class="chip ${r.startsWith("Vắng quá") ? "bad" : "warn"}">${escapeHtml(r)}</span>`).join("")}</div>`
    : `<span class="muted">Chưa vi phạm</span>`;
  return `<tr class="${it.source === "ai" ? "row-ai" : ""}">
    <td><b>${escapeHtml(it.student_code)}</b><br />${escapeHtml(it.full_name)}<br /><span class="muted">${escapeHtml(it.class_code)}${it.attempt_no > 1 ? ` · học lần ${it.attempt_no}` : ""}</span></td>
    <td>${escapeHtml(it.course_name)}<br /><span class="muted">${escapeHtml(it.section_code)} · ${escapeHtml(it.lecturer ?? "")}</span><br />${tag}</td>
    <td class="prob-cell">
      <div class="prob"><div class="prob-bar ${level.cls}" style="width:${Math.round(it.proba * 100)}%"></div></div>
      <b>${fmtPct(it.proba)}</b> <span class="chip ${level.cls}">${level.label}</span>
      <div class="muted">${it.checkpoint} · ${escapeHtml(it.checkpoint_label)}</div>
    </td>
    <td>${renderTrend(it.history)}</td>
    <td>${factors}</td>
    <td>${rules}</td>
  </tr>`;
}

function renderTrend(history) {
  if (history.length < 2) return `<span class="muted">–</span>`;
  const first = history[0];
  const last = history[history.length - 1];
  const diff = last.proba - first.proba;
  const cls = diff > 0.05 ? "up" : diff < -0.05 ? "down" : "flat";
  const icon = { up: "fa-arrow-trend-up", down: "fa-arrow-trend-down", flat: "fa-arrow-right" }[cls];
  return `<span class="trend ${cls}" title="${history.map((h) => `${h.checkpoint}: ${fmtPct(h.proba)}`).join(" → ")}">
    ${fmtPct(first.proba)} <i class="fas ${icon}"></i> ${fmtPct(last.proba)}</span>
    <div class="muted">${first.checkpoint} → ${last.checkpoint}</div>`;
}

// ------------------------------------------------------------------ kiểm chứng
async function loadBacktest() {
  try {
    agentState.backtest = await apiGet("/agent/backtest");
  } catch (err) {
    document.getElementById("bt-intro").textContent = err.message;
    return;
  }
  const cps = Object.keys(agentState.backtest.checkpoints);
  document.getElementById("bt-cp").innerHTML = cps.map((cp) =>
    `<button type="button" class="seg-btn${cp === agentState.cp ? " active" : ""}" data-cp="${cp}">${cp}</button>`).join("");
  renderBacktest();
}

function renderBacktest() {
  const r = agentState.backtest.checkpoints[agentState.cp];
  const b = r.backtest;
  document.getElementById("bt-semester").textContent = b.semester;
  document.getElementById("bt-intro").innerHTML =
    `Mô hình chỉ học từ các kỳ ${r.split.train.join(", ")} và ${r.split.val}, rồi dự báo học kỳ <b>${b.semester}</b> ` +
    `như thể đang ở mốc <b>${agentState.cp}</b> (${escapeHtml(r.label.toLowerCase())}), sau đó đối chiếu với kết quả thật.` +
    (b.weeks_before_exam ? ` Mốc này cách kỳ thi khoảng <b>${b.weeks_before_exam} tuần</b>, còn đủ thời gian can thiệp.` : "");

  const box = (label, value, sub, cls = "") => `<div class="bt-box ${cls}"><div class="bt-value">${value}</div><div class="bt-label">${label}</div>${sub ? `<div class="bt-sub">${sub}</div>` : ""}</div>`;
  document.getElementById("bt-numbers").innerHTML = [
    box("Lượt học trượt thật", fmtNum(b.n_failed), `trên ${fmtNum(b.n)} lượt học`),
    box("Luật bắt được", fmtNum(b.rule.caught), `báo nhầm ${fmtNum(b.rule.false_alarms)}`),
    box("AI bắt được", fmtNum(b.ai.caught), `báo nhầm ${fmtNum(b.ai.false_alarms)}`, "ai"),
    box("AI bắt, luật bỏ sót", fmtNum(b.ai_only_caught), "chỉ AI phát hiện", "ai"),
    box("Agent (luật + AI)", fmtNum(b.agent_caught), `${fmtPct(b.agent_caught / b.n_failed)} số lượt trượt`, "strong"),
  ].join("");

  if (agentState.btChart) agentState.btChart.destroy();
  agentState.btChart = new Chart(document.getElementById("bt-chart"), {
    type: "bar",
    data: {
      labels: ["Bắt đúng (trượt thật)", "Báo nhầm (thật ra qua môn)"],
      datasets: [
        { label: "Luật quy chế", data: [b.rule.caught, b.rule.false_alarms], backgroundColor: "#94a3b8", borderRadius: 4 },
        { label: "Mô hình AI", data: [b.ai.caught, b.ai.false_alarms], backgroundColor: "#6d28d9", borderRadius: 4 },
      ],
    },
    options: { maintainAspectRatio: false, plugins: { legend: { position: "bottom" } }, scales: { y: { beginAtZero: true } } },
  });

  const ex = document.getElementById("bt-examples");
  ex.innerHTML = b.examples.length
    ? b.examples.map((e) => `<tr>
        <td><b>${escapeHtml(e.student_code)}</b> ${escapeHtml(e.full_name)}</td>
        <td>${escapeHtml(e.course_name)}</td>
        <td class="num"><b>${fmtPct(e.proba)}</b></td>
        <td>${e.status === "banned_exam" ? '<span class="chip bad">Bị cấm thi</span>' : `<span class="chip bad">Trượt · TBCHP ${formatScore(e.final_score)}</span>`}</td>
      </tr>`).join("")
    : `<tr class="empty-row"><td colspan="4">Không có trường hợp nào ở mốc này.</td></tr>`;

  document.getElementById("bt-note").innerHTML =
    `Mô hình mốc ${agentState.cp}: ${escapeHtml(r.chosen.model.replaceAll("_", " "))}, bộ đặc trưng "${escapeHtml(r.chosen.feature_set)}", ` +
    `ngưỡng cảnh báo ${r.thresholds.alert} (chọn trên kỳ ${r.split.val} để AI không báo nhầm nhiều hơn luật). ` +
    `<b>Lưu ý:</b> đây là ${escapeHtml(agentState.backtest.data)}, chỉ chứng minh Agent chạy đúng quy trình; ` +
    `độ chính xác trên dữ liệu thật xem ở trang <a href="models.html#oulad">So sánh mô hình</a> (bộ dữ liệu công khai OULAD).`;
}

// ------------------------------------------------------------------ nhật ký
async function loadRuns() {
  const runs = await apiGet("/agent/runs?limit=10");
  document.getElementById("runs").innerHTML = runs.length
    ? runs.map((r) => `<tr>
        <td>${fmtTime(r.started_at)}</td>
        <td>${escapeHtml(r.trigger_label)}</td>
        <td>${fmtTime(r.as_of)}</td>
        <td><span class="chip ${RUN_STATUS[r.status]}">${r.status === "success" ? "Xong" : r.status === "failed" ? "Lỗi" : "Đang chạy"}</span> ${escapeHtml(r.message ?? "")}</td>
        <td class="num">${r.stats?.duration_s != null ? `${r.stats.duration_s} s` : "–"}</td>
      </tr>`).join("")
    : `<tr class="empty-row"><td colspan="5">Chưa có lần chạy nào.</td></tr>`;
}

// ------------------------------------------------------------------ sự kiện
document.getElementById("tabs").addEventListener("click", (e) => {
  const tab = e.target.closest(".tab");
  if (!tab) return;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
  agentState.source = tab.dataset.source;
  loadList().catch((err) => showError(document.getElementById("error"), err));
});

document.getElementById("list-search").addEventListener("submit", (e) => {
  e.preventDefault();
  agentState.q = document.getElementById("q").value.trim();
  loadList().catch((err) => showError(document.getElementById("error"), err));
});

document.getElementById("bt-cp").addEventListener("click", (e) => {
  const btn = e.target.closest(".seg-btn");
  if (!btn) return;
  agentState.cp = btn.dataset.cp;
  document.querySelectorAll(".seg-btn").forEach((b) => b.classList.toggle("active", b === btn));
  renderBacktest();
});

document.getElementById("run-btn").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Agent đang chạy...';
  try {
    const run = await apiPost("/agent/run");
    showSuccess(document.getElementById("error"), `Agent đã chạy xong: ${run.message}`);
    renderOverview(await apiGet("/agent/overview"));
    await Promise.all([loadList(), loadRuns()]);
  } catch (err) {
    showError(document.getElementById("error"), err);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-play"></i> Chạy Agent ngay';
  }
});

loadAgentPage();
