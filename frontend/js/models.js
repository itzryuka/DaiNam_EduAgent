const MODEL_LABELS = {
  logistic_regression: "Logistic Regression",
  decision_tree: "Decision Tree",
  random_forest: "Random Forest",
  svm: "SVM",
};
const MODEL_COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6"];

const METRICS = [
  { key: "cv_f1", label: "CV F1" },
  { key: "recall", label: "Recall" },
  { key: "precision", label: "Precision" },
  { key: "f1", label: "F1" },
  { key: "accuracy", label: "Accuracy" },
  { key: "roc_auc", label: "ROC-AUC" },
];

const FEATURE_LABELS = {
  gpa_prev: "GPA kỳ trước",
  attendance_rate: "Tỷ lệ đi học",
  midterm_avg: "Điểm giữa kỳ",
  failed_courses_prev: "Số môn từng trượt",
  credits_registered: "Tín chỉ đăng ký",
  assignment_submission_rate: "Tỷ lệ nộp bài",
  lms_logins_per_week: "Lần vào LMS/tuần",
};

const modelLabel = (name) => MODEL_LABELS[name] ?? name;
const formatMetric = (value) => value.toFixed(3);
const formatTime = (iso) => new Date(iso).toLocaleString("vi-VN");

async function loadModelsPage() {
  try {
    const [run, history] = await Promise.all([apiGet("/experiments/latest"), apiGet("/experiments/history")]);
    renderRunInfo(run);
    renderBest(run);
    renderMetricsChart(run);
    renderMetricsTable(run);
    renderConfusionMatrices(run);
    renderImportance(run.feature_importance);
    renderDataInfo(run.data);
    renderHistory(history);
  } catch (err) {
    showError(document.getElementById("error"), err);
  }
}

function renderRunInfo(run) {
  document.getElementById("run-info").textContent = `Train lúc ${formatTime(run.trained_at)}`;
  document.getElementById("run-note").textContent = run.note ? `Ghi chú: ${run.note}` : "";
}

function renderBest(run) {
  const best = run.results[run.best_model];
  document.getElementById("best-name").textContent = modelLabel(run.best_model);
  document.getElementById("best-reason").textContent =
    "Chọn theo F1 kiểm định chéo cao nhất. Các chỉ số dưới đây đo trên tập kiểm tra.";
  document.getElementById("best-metrics").innerHTML = ["recall", "precision", "f1", "roc_auc"]
    .map((key) => {
      const label = METRICS.find((m) => m.key === key).label;
      return `<div><b>${formatMetric(best[key])}</b><span>${label}</span></div>`;
    })
    .join("");
}

function renderMetricsChart(run) {
  const models = Object.keys(run.results);
  new Chart(document.getElementById("chart-metrics"), {
    type: "bar",
    data: {
      labels: METRICS.map((m) => m.label),
      datasets: models.map((name, i) => ({
        label: modelLabel(name),
        data: METRICS.map((m) => run.results[name][m.key]),
        backgroundColor: MODEL_COLORS[i % MODEL_COLORS.length],
        borderRadius: 3,
      })),
    },
    options: {
      maintainAspectRatio: false,
      scales: { y: { min: 0, max: 1 } },
      plugins: {
        tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${formatMetric(ctx.parsed.y)}` } },
      },
    },
  });
}

function renderMetricsTable(run) {
  const models = Object.keys(run.results);
  const bestPerMetric = Object.fromEntries(
    METRICS.map((m) => [m.key, Math.max(...models.map((name) => run.results[name][m.key]))])
  );

  document.getElementById("metrics-head").innerHTML = `<tr>
    <th>Mô hình</th>${METRICS.map((m) => `<th class="text-right">${m.label}</th>`).join("")}
  </tr>`;
  document.getElementById("metrics-body").innerHTML = models
    .map((name) => {
      const r = run.results[name];
      const cells = METRICS.map((m) => {
        const isBest = r[m.key] === bestPerMetric[m.key];
        return `<td class="text-right num${isBest ? " best" : ""}">${formatMetric(r[m.key])}</td>`;
      }).join("");
      const chosen = name === run.best_model;
      return `<tr class="${chosen ? "row-chosen" : ""}">
        <td class="nowrap">${modelLabel(name)}${chosen ? ' <span class="badge badge-ok">được chọn</span>' : ""}</td>
        ${cells}
      </tr>`;
    })
    .join("");
}

function renderConfusionMatrices(run) {
  document.getElementById("confusion-matrices").innerHTML = Object.entries(run.results)
    .map(([name, r]) => {
      const { tn, fp, fn, tp } = r.confusion_matrix;
      return `<div>
        <div class="cm-title">${modelLabel(name)}</div>
        <table class="cm-table">
          <thead>
            <tr><th></th><th>Dự báo: yếu</th><th>Dự báo: bình thường</th></tr>
          </thead>
          <tbody>
            <tr>
              <th>Thực tế: yếu</th>
              <td class="cm-tp"><b>${tp}</b><span>Bắt đúng</span></td>
              <td class="cm-fn"><b>${fn}</b><span>Bỏ sót</span></td>
            </tr>
            <tr>
              <th>Thực tế: bình thường</th>
              <td class="cm-fp"><b>${fp}</b><span>Báo nhầm</span></td>
              <td><b>${tn}</b><span>Đúng</span></td>
            </tr>
          </tbody>
        </table>
      </div>`;
    })
    .join("");
}

function renderImportance(importance) {
  const entries = Object.entries(importance);
  new Chart(document.getElementById("chart-importance"), {
    type: "bar",
    data: {
      labels: entries.map(([feature]) => FEATURE_LABELS[feature] ?? feature),
      datasets: [{ data: entries.map(([, value]) => value), backgroundColor: "#3b82f6", borderRadius: 3 }],
    },
    options: {
      indexAxis: "y",
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
    },
  });
}

function renderDataInfo(data) {
  const rows = [
    ["File dữ liệu", escapeHtml(data.file)],
    ["Số sinh viên", data.rows],
    ["Tỷ lệ học yếu", formatPercent(data.at_risk_rate)],
    ["Tập kiểm tra", `${data.test_size * 100}% (${Math.round(data.rows * data.test_size)} sinh viên)`],
    ["Đặc trưng", data.features.map((f) => FEATURE_LABELS[f] ?? f).join(", ")],
  ];
  document.getElementById("data-info").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
}

function renderHistory(history) {
  const tbody = document.getElementById("history-body");
  if (history.length === 0) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="7">Chưa có lịch sử.</td></tr>';
    return;
  }
  tbody.innerHTML = history
    .map((run) => {
      const best = run.results[run.best_model];
      return `<tr>
        <td class="nowrap">${formatTime(run.trained_at)}</td>
        <td>${escapeHtml(run.note || "–")}</td>
        <td class="text-right num">${run.data.rows}</td>
        <td class="nowrap">${modelLabel(run.best_model)}</td>
        <td class="text-right num">${formatMetric(best.cv_f1)}</td>
        <td class="text-right num">${formatMetric(best.recall)}</td>
        <td class="text-right num">${formatMetric(best.precision)}</td>
      </tr>`;
    })
    .join("");
}

loadModelsPage();

// ------------------------------------------------------------------ mô hình chính (OULAD)
const OULAD_MODEL_LABELS = { ...MODEL_LABELS, gradient_boosting: "Gradient Boosting" };
const OULAD_FEATURES = {
  prev_attempts: "Số lần đã học môn", credit_load: "Khối lượng tín chỉ", course_fail_rate: "Tỷ lệ trượt của môn",
  engagement: "Mức tham gia học tập", process_score: "Điểm quá trình", submission_rate: "Tỷ lệ nộp bài",
  score_trend: "Xu hướng điểm", recent_engagement: "Tham gia 14 ngày gần nhất", inactive_days: "Số ngày không hoạt động",
  late_rate: "Tỷ lệ nộp muộn",
};

function ouladPair(x) {
  return x ? `${x.test.caught.toLocaleString("vi-VN")} / ${x.test.false_alarms.toLocaleString("vi-VN")}` : "–";
}

function ouladVerdict(c) {
  const wins = [c.same_recall, c.same_precision].filter((x) => x?.beats_baseline);
  if (!wins.length) return '<span class="chip warn">Chưa hơn quy tắc</span>';
  const w = wins[0];
  const parts = [];
  if (w.extra_caught > 0) parts.push(`bắt thêm ${w.extra_caught}`);
  if (w.fewer_false_alarms > 0) parts.push(`báo nhầm ít hơn ${w.fewer_false_alarms}`);
  return `<span class="chip ok">AI hơn quy tắc</span> <span class="muted">${parts.join(", ")}</span>`;
}

async function loadOulad() {
  let r;
  try {
    r = await apiGet("/experiments/oulad");
  } catch (err) {
    document.getElementById("oulad-rows").innerHTML = `<tr class="empty-row"><td colspan="7">${escapeHtml(err.message)}</td></tr>`;
    return;
  }
  const cps = Object.entries(r.checkpoints);
  const m1 = r.checkpoints.M1;
  document.getElementById("oulad-info").textContent = `Train lúc ${formatTime(r.trained_at)}`;
  document.getElementById("oulad-intro").innerHTML =
    `Open University Learning Analytics Dataset (Anh): dữ liệu học tập thật, đã ẩn danh, công khai cho nghiên cứu. ` +
    `Chia theo thời gian: học từ các kỳ trước, chọn mô hình trên kỳ <b>${r.split.val_term}</b>, ` +
    `báo cáo trên kỳ mới nhất <b>${r.split.test_term}</b> (${m1.n_test.toLocaleString("vi-VN")} lượt học, ` +
    `${formatPercent(m1.test_fail_rate)} trượt) mà mô hình chưa từng thấy.`;
  if (m1.same_recall?.beats_baseline) {
    document.getElementById("oulad-highlight").innerHTML =
      `<i class="fas fa-trophy"></i> Ở mốc <b>M1</b> (${escapeHtml(m1.label.toLowerCase())}), khi bắt cùng số sinh viên trượt như quy tắc, ` +
      `AI <b>bắt thêm ${m1.same_recall.extra_caught}</b> sinh viên và <b>báo nhầm ít hơn ${m1.same_recall.fewer_false_alarms}</b> trường hợp.`;
  }
  document.getElementById("oulad-rows").innerHTML = cps.map(([cp, c]) => `<tr>
      <td><b>${cp}</b><br /><span class="muted">${escapeHtml(c.label)}</span></td>
      <td>${escapeHtml(OULAD_MODEL_LABELS[c.best_model] ?? c.best_model)}<br /><span class="muted">bộ đặc trưng ${escapeHtml(c.feature_set)}</span></td>
      <td class="num">${formatMetric(c.test.pr_auc)}</td>
      <td class="num">${c.baseline_test.caught.toLocaleString("vi-VN")} / ${c.baseline_test.false_alarms.toLocaleString("vi-VN")}</td>
      <td class="num">${ouladPair(c.same_recall)}</td>
      <td class="num">${ouladPair(c.same_precision)}</td>
      <td>${ouladVerdict(c)}</td>
    </tr>`).join("");

  new Chart(document.getElementById("oulad-chart"), {
    type: "bar",
    data: {
      labels: cps.map(([cp]) => cp),
      datasets: [
        { label: "Quy tắc", data: cps.map(([, c]) => c.baseline_test.false_alarms), backgroundColor: "#94a3b8", borderRadius: 4 },
        { label: "AI (cùng recall)", data: cps.map(([, c]) => c.same_recall?.test.false_alarms ?? null), backgroundColor: "#6d28d9", borderRadius: 4 },
      ],
    },
    options: { maintainAspectRatio: false, plugins: { legend: { position: "bottom" } }, scales: { y: { beginAtZero: true } } },
  });

  const imp = Object.entries(m1.feature_importance).filter(([, v]) => v > 0).slice(0, 7);
  new Chart(document.getElementById("oulad-importance"), {
    type: "bar",
    data: {
      labels: imp.map(([k]) => OULAD_FEATURES[k] ?? k),
      datasets: [{ data: imp.map(([, v]) => v), backgroundColor: "#00358f", borderRadius: 3 }],
    },
    options: { indexAxis: "y", maintainAspectRatio: false, plugins: { legend: { display: false } } },
  });
}

loadOulad();
