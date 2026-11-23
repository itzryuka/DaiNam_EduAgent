// Trang Sức khỏe AI (chỉ quản trị): số liệu từng lần Agent chạy theo thời gian, để thấy AI có chạy đều,
// có đổi hành vi bất thường (đột ngột cảnh báo nhiều / ít), email có đi được không và có lỗi gì.

// Màu: nguồn phát hiện (xanh lam / hổ phách / tím) đã kiểm tra phân biệt được với người mù màu;
// mức nguy cơ là một dải đỏ đậm -> nhạt; biểu đồ một chuỗi dùng xanh lam.
const H = {
  both: "#2a78d6", rule: "#d97706", ai: "#7c3aed",
  high: "#dc2626", medium: "#f87171",
  series: "#2a78d6", outbox: "#eb6834", bad: "#dc2626",
  grid: "#eef2f7", text: "#64748b",
};
const MAIL_MODE = { brevo: "gửi thật qua Brevo", smtp: "gửi thật qua SMTP", outbox: "chế độ thử (chỉ lưu outbox)" };
const STATUS = { success: ["ok", "Thành công"], failed: ["bad", "Lỗi"], running: ["warn", "Đang chạy"] };
const STUCK_MINUTES = 10;

Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
Chart.defaults.color = H.text;
Chart.defaults.plugins.tooltip.padding = 10;
Chart.defaults.plugins.legend.labels.boxWidth = 12;
Chart.defaults.plugins.legend.labels.boxHeight = 12;

const charts = {};
const pad2 = (n) => String(n).padStart(2, "0");
const shortTime = (iso) => {
  const d = new Date(iso);
  return `${pad2(d.getDate())}/${pad2(d.getMonth() + 1)} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
};
const fullTime = (iso) => new Date(iso).toLocaleString("vi-VN");
const mean = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
const sumMail = (e) => e.sent + e.outbox + e.failed;

function ago(iso, now) {
  const minutes = Math.round((new Date(now) - new Date(iso)) / 60000);
  if (minutes < 1) return "vừa xong";
  if (minutes < 60) return `${minutes} phút trước`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)} giờ trước`;
  return `${Math.round(minutes / 60 / 24)} ngày trước`;
}

const axes = (opts = {}) => ({
  grid: { color: H.grid, drawTicks: false },
  border: { display: false },
  ticks: { padding: 6, precision: 0 },
  beginAtZero: true,
  ...opts,
});
const xAxis = { grid: { display: false }, border: { display: false }, ticks: { maxRotation: 0, autoSkipPadding: 16 } };

// Tiêu đề tooltip chung: lần chạy, thời gian, lý do
function tooltipTitle(runs) {
  return (items) => {
    const r = runs[items[0].dataIndex];
    return `Lần ${r.id} · ${fullTime(r.started_at)} · ${r.trigger_label}`;
  };
}

function draw(id, config) {
  charts[id]?.destroy();
  charts[id] = new Chart(document.getElementById(id), config);
}

function barStack(id, runs, series, extra = {}) {
  draw(id, {
    type: "bar",
    data: {
      labels: runs.map((r) => shortTime(r.started_at)),
      datasets: series.map(([label, color, value]) => ({
        label, data: runs.map(value), backgroundColor: color,
        borderColor: "#fff", borderWidth: series.length > 1 ? 1 : 0, borderSkipped: false,
        borderRadius: series.length > 1 ? 0 : 3, maxBarThickness: 28,
      })),
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: series.length > 1, position: "bottom" },
        tooltip: { callbacks: { title: tooltipTitle(runs), ...(extra.callbacks || {}) } },
      },
      scales: { x: { ...xAxis, stacked: true }, y: axes({ stacked: true }) },
    },
  });
}

function lineChart(id, runs, label, value, opts = {}) {
  draw(id, {
    type: "line",
    data: {
      labels: runs.map((r) => shortTime(r.started_at)),
      datasets: [{
        label, data: runs.map(value), borderColor: opts.color || H.series, backgroundColor: opts.color || H.series,
        borderWidth: 2, tension: 0.25, spanGaps: true,
        pointRadius: runs.map((r) => (r.status === "success" ? 3 : 6)),
        pointHoverRadius: 7,
        pointBackgroundColor: runs.map((r) => (r.status === "success" ? opts.color || H.series : H.bad)),
        pointBorderColor: "#fff", pointBorderWidth: 2,
      }],
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { title: tooltipTitle(runs), ...(opts.callbacks || {}) } },
      },
      scales: { x: xAxis, y: axes(opts.y || {}) },
    },
  });
}

function renderCharts(runs) {
  const ok = runs.filter((r) => r.status === "success");
  barStack("chart-source", ok, [
    ["Luật + AI cùng bắt", H.both, (r) => r.both],
    ["Chỉ luật quy chế", H.rule, (r) => r.rule],
    ["Chỉ AI (phát hiện sớm)", H.ai, (r) => r.ai],
  ], { callbacks: { footer: (items) => `Tổng: ${ok[items[0].dataIndex].flagged} lượt · ${ok[items[0].dataIndex].students} sinh viên` } });

  lineChart("chart-ai-share", ok, "AI phát hiện sớm", (r) => (r.flagged ? Math.round((r.ai / r.flagged) * 1000) / 10 : null), {
    color: H.ai,
    y: { suggestedMax: 40, ticks: { padding: 6, callback: (v) => `${v}%` } },
    callbacks: { label: (ctx) => ` ${ctx.parsed.y}% (${ok[ctx.dataIndex].ai}/${ok[ctx.dataIndex].flagged} lượt)` },
  });

  barStack("chart-level", ok, [
    ["Nguy cơ cao", H.high, (r) => r.high],
    ["Nguy cơ trung bình", H.medium, (r) => r.medium],
  ], { callbacks: { footer: (items) => `Mô hình dự báo ${ok[items[0].dataIndex].predicted} lượt học` } });

  barStack("chart-alerts", ok, [["Cảnh báo mới", H.series, (r) => r.alerts]], {
    callbacks: {
      footer: (items) => {
        const r = ok[items[0].dataIndex];
        return r.academic_students ? `Trong đó cảnh báo học tập: ${r.academic_students} sinh viên` : "";
      },
    },
  });

  barStack("chart-email", ok, [
    ["Gửi thật", H.series, (r) => r.emails.sent],
    ["Chế độ thử (outbox)", H.outbox, (r) => r.emails.outbox],
  ], {
    callbacks: {
      footer: (items) => {
        const e = ok[items[0].dataIndex].emails;
        return [e.failed ? `Gửi lỗi: ${e.failed}` : "", e.unlinked ? `Chưa liên kết email: ${e.unlinked} người` : ""]
          .filter(Boolean);
      },
    },
  });

  lineChart("chart-duration", runs, "Thời gian chạy", (r) => r.duration_s, {
    callbacks: {
      label: (ctx) => ` ${ctx.parsed.y ?? "–"} giây`,
      afterLabel: (ctx) => {
        const r = runs[ctx.dataIndex];
        return r.status === "success" ? "" : `${STATUS[r.status][1]}: ${r.message || ""}`.slice(0, 120);
      },
    },
  });
}

function renderStats(d) {
  const runs = d.runs;
  const ok = runs.filter((r) => r.status === "success");
  const last = ok[ok.length - 1];
  const failed = runs.filter((r) => r.status === "failed").length;

  document.getElementById("stat-success").textContent = runs.length ? `${Math.round((ok.length / runs.length) * 100)}%` : "–";
  document.getElementById("sub-success").textContent = `${ok.length}/${runs.length} lần · ${failed} lần lỗi`;

  const durations = ok.map((r) => r.duration_s).filter((x) => x != null);
  const avg = mean(durations);
  document.getElementById("stat-duration").textContent = avg == null ? "–" : `${avg.toFixed(1)} giây`;
  document.getElementById("sub-duration").textContent = durations.length ? `chậm nhất ${Math.max(...durations).toFixed(1)} giây` : "";

  document.getElementById("stat-ai").textContent = last ? `${last.ai} lượt` : "–";
  document.getElementById("sub-ai").textContent = last && last.flagged
    ? `${Math.round((last.ai / last.flagged) * 100)}% trong ${last.flagged} lượt cần chú ý` : "";

  const mails = ok.reduce((acc, r) => ({ sent: acc.sent + r.emails.sent, outbox: acc.outbox + r.emails.outbox,
                                         failed: acc.failed + r.emails.failed }), { sent: 0, outbox: 0, failed: 0 });
  document.getElementById("stat-email").textContent = sumMail(mails);
  document.getElementById("sub-email").textContent =
    `${mails.sent} gửi thật · ${mails.outbox} chế độ thử${mails.failed ? ` · ${mails.failed} lỗi` : ""}`;

  const lastAny = runs[runs.length - 1];
  document.getElementById("context").innerHTML = lastAny
    ? `Lần chạy gần nhất: <b>${ago(lastAny.started_at, d.now)}</b> (${escapeHtml(lastAny.trigger_label.toLowerCase())}) ·
       Email: <b>${MAIL_MODE[d.mail_mode]}</b> · Toàn bộ: ${d.totals.success || 0} lần thành công, ${d.totals.failed || 0} lần lỗi`
    : "Chưa có lần chạy nào.";
}

// Những điều quản trị nên để ý, ghi rõ bằng lời (không chỉ dựa vào màu)
function renderProblems(d) {
  const runs = d.runs;
  const items = [];
  if (!d.models_ready) items.push(["bad", "Chưa có mô hình AI: Agent không chạy được. Chạy python ml/train_dainam.py."]);
  const lastFail = [...runs].reverse().find((r) => r.status === "failed");
  if (lastFail) {
    items.push(["bad", `Lần ${lastFail.id} (${fullTime(lastFail.started_at)}) bị lỗi: ${lastFail.message || "không rõ"}`]);
  }
  const stuck = runs.filter((r) => r.status === "running" && (new Date(d.now) - new Date(r.started_at)) / 60000 > STUCK_MINUTES);
  if (stuck.length) items.push(["bad", `${stuck.length} lần chạy treo ở trạng thái "đang chạy" quá ${STUCK_MINUTES} phút.`]);
  const ok = runs.filter((r) => r.status === "success");
  const failedMails = ok.reduce((n, r) => n + r.emails.failed, 0);
  if (failedMails) items.push(["bad", `${failedMails} email gửi lỗi. Xem chi tiết ở trang Lịch sử gửi email.`]);
  if (d.mail_mode === "outbox") items.push(["warn", "Email đang ở chế độ thử: chỉ lưu vào outbox, chưa gửi tới hộp thư thật."]);
  const lastAny = runs[runs.length - 1];
  if (lastAny && (new Date(d.now) - new Date(lastAny.started_at)) / 3600000 > 24) {
    items.push(["warn", `Agent đã ${ago(lastAny.started_at, d.now)} không chạy. Kiểm tra cài đặt "Agent tự chạy".`]);
  }
  // Số lượt cần chú ý thay đổi đột ngột so với lần trước (> 30%) dù không phải chạy lại quá khứ
  for (let i = ok.length - 1; i > 0 && i >= ok.length - 5; i -= 1) {
    const a = ok[i - 1], b = ok[i];
    if (b.trigger !== "replay" && a.trigger !== "replay" && a.flagged >= 20 &&
        Math.abs(b.flagged - a.flagged) / a.flagged > 0.3) {
      items.push(["warn", `Lần ${b.id}: số lượt cần chú ý đổi đột ngột ${a.flagged} → ${b.flagged}. Nên xem lại dữ liệu vừa nhập.`]);
      break;
    }
  }
  const box = document.getElementById("problems");
  box.innerHTML = items.length
    ? `<section class="panel health-problems"><div class="panel-body">${items.map(([kind, text]) =>
        `<p class="health-item ${kind}"><i class="fas ${kind === "bad" ? "fa-circle-exclamation" : "fa-triangle-exclamation"}"></i>
         <span><b>${kind === "bad" ? "Cần xử lý" : "Lưu ý"}:</b> ${escapeHtml(text)}</span></p>`).join("")}</div></section>`
    : `<section class="panel health-problems"><div class="panel-body"><p class="health-item ok"><i class="fas fa-circle-check"></i>
       <span><b>Ổn định:</b> không có lỗi, không có thay đổi bất thường trong các lần chạy đang xem.</span></p></div></section>`;
}

function renderTable(runs) {
  document.getElementById("table-note").textContent = `${runs.length} lần, mới nhất ở trên`;
  document.getElementById("rows").innerHTML = runs.length
    ? [...runs].reverse().map((r) => {
        const [cls, label] = STATUS[r.status];
        const ok = r.status === "success";
        const mail = sumMail(r.emails);
        const note = ok
          ? [r.academic_students ? `${r.academic_students} SV cảnh báo học tập` : "",
             r.emails.failed ? `${r.emails.failed} email lỗi` : ""].filter(Boolean).join(" · ")
          : r.message || "";
        return `<tr>
          <td class="num">${r.id}</td>
          <td class="nowrap">${fullTime(r.started_at)}</td>
          <td class="nowrap">${escapeHtml(r.trigger_label)}</td>
          <td><span class="badge badge-${cls}">${label}</span></td>
          <td class="num">${r.duration_s ?? "–"}</td>
          <td class="num">${ok ? r.flagged : "–"}</td>
          <td class="num">${ok ? r.ai : "–"}</td>
          <td class="num">${ok ? r.high : "–"}</td>
          <td class="num">${ok ? r.alerts : "–"}</td>
          <td class="num">${ok ? `${mail}${r.emails.sent ? ` <span class="muted">(${r.emails.sent} thật)</span>` : ""}` : "–"}</td>
          <td class="health-note">${escapeHtml(note)}</td>
        </tr>`;
      }).join("")
    : '<tr class="empty-row"><td colspan="11">Chưa có lần chạy nào.</td></tr>';
}

async function loadHealth() {
  const error = document.getElementById("error");
  error.innerHTML = "";
  const params = new URLSearchParams({ limit: document.getElementById("limit").value });
  const trigger = document.getElementById("trigger").value;
  if (trigger) params.set("trigger", trigger);
  try {
    const d = await apiGet(`/agent/health?${params}`);
    renderStats(d);
    renderProblems(d);
    renderCharts(d.runs);
    renderTable(d.runs);
  } catch (e) {
    showError(error, e);
  }
}

["trigger", "limit"].forEach((id) => document.getElementById(id).addEventListener("change", loadHealth));
document.getElementById("reload").addEventListener("click", loadHealth);
loadHealth();
