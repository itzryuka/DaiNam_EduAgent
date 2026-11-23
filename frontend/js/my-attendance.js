// Trang "Điểm danh" của sinh viên: từng buổi của từng môn học kỳ hiện tại, số buổi còn được vắng.
const STATUS_LABEL = { present: "Có mặt", late: "Đi muộn", excused: "Vắng có phép", absent: "Vắng" };

function renderCourse(c) {
  const absences = c.absent + c.excused;
  const ratio = c.absences_allowed ? absences / c.absences_allowed : 1;
  const level = absences > c.absences_allowed ? "bad" : ratio >= 0.6 ? "warn" : "ok";
  const remaining = c.absences_allowed - absences;
  const note = remaining < 0
    ? '<span class="chip bad"><i class="fas fa-ban"></i> Đã vượt ngưỡng cấm thi</span>'
    : remaining === 0
      ? '<span class="chip bad">Không được vắng thêm buổi nào</span>'
      : `<span class="chip ${level}">Còn được vắng ${remaining} buổi</span>`;
  const dots = c.sessions
    .map((s) => {
      const cls = s.upcoming ? "upcoming" : s.status ?? "none";
      const label = s.upcoming ? "Chưa học" : STATUS_LABEL[s.status] ?? "Chưa điểm danh";
      return `<span class="dot ${cls}" title="Buổi ${s.no} · ${s.date} · ${label}">${s.no}</span>`;
    })
    .join("");
  return `<div class="att-card">
    <h4>${escapeHtml(c.course_name)}</h4>
    <div class="att-sub">${escapeHtml(c.course_code)} · ${escapeHtml(c.lecturer ?? "")}</div>
    <div class="att-stats">
      <span>Có mặt <b>${c.present}</b></span><span>Muộn <b>${c.late}</b></span>
      <span>Có phép <b>${c.excused}</b></span><span>Vắng <b>${c.absent}</b></span>
      <span class="muted">${c.recorded}/${c.total_sessions} buổi</span>
    </div>
    <div class="progress" title="Đã vắng ${absences}/${c.absences_allowed} buổi được phép">
      <div class="progress-bar ${level}" style="width: ${Math.min(ratio, 1) * 100}%"></div>
    </div>
    ${note}
    <div class="att-dots">${dots}</div>
  </div>`;
}

async function loadAttendance() {
  const container = document.getElementById("courses");
  try {
    const data = await apiGet("/me/attendance");
    document.getElementById("semester-name").textContent = `Điểm danh · ${data.semester}`;
    document.getElementById("ban-note").textContent =
      `Vắng quá ${Math.round(data.ban_ratio * 100)}% số buổi sẽ bị cấm thi`;
    container.innerHTML = data.courses.map(renderCourse).join("") || '<p class="muted">Học kỳ này chưa có môn nào.</p>';
  } catch (error) {
    container.innerHTML = "";
    showError(document.getElementById("error"), error);
  }
}

loadAttendance();
