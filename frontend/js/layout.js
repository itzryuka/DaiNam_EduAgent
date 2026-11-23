// Bố cục dùng chung cho mọi trang (giống views/layout/header.php của OmniStock):
// thanh bên trái (logo + menu theo vai trò), thanh điều hướng trên (tiêu đề, tìm kiếm, thông báo, tài khoản, đăng xuất).
//
// Mỗi trang khai báo:
//   <body data-title="Tiêu đề" data-roles="admin,lecturer">   (data-roles: vai trò được mở trang; bỏ trống = mọi vai trò)
//   nội dung đặt trong <main>
// Thứ tự nạp: api.js, layout.js, rồi script riêng của trang.
// Chưa đăng nhập -> chuyển sang login.html. Sai vai trò -> chuyển về trang đầu của vai trò đó.

// roles: vai trò thấy mục này. when(user): điều kiện thêm. soon: true = chức năng sắp làm (hiện mờ).
const MENU = [
  // ---- Quản trị và giảng viên
  { icon: "fa-gauge-high", label: "Tổng quan", href: "index.html", roles: ["admin", "lecturer"] },
  { icon: "fa-robot", label: "AI Agent", href: "agent.html", roles: ["admin", "lecturer"] },
  {
    icon: "fa-chalkboard-user",
    label: "Giảng dạy",
    roles: ["lecturer"],
    links: [
      { label: "Lớp học phần của tôi", href: "teaching.html" },
      { label: "Nhập điểm", href: "teaching.html?mode=grades" },
      { label: "Điểm danh", href: "teaching.html?mode=attendance" },
      { label: "Lớp chủ nhiệm (CVHT)", href: "advising.html", when: (u) => u.advised_classes?.length > 0 },
      { label: "Sinh viên lớp chủ nhiệm", href: "manage-students.html", when: (u) => u.advised_classes?.length > 0 },
    ],
  },
  {
    icon: "fa-user-graduate",
    label: "Quản lý đào tạo",
    roles: ["admin"],
    links: [
      { label: "Lớp học phần", href: "teaching.html" },
      { label: "Lớp hành chính", href: "advising.html" },
      { label: "Sinh viên", href: "manage-students.html" },
      { label: "Môn học, học kỳ", soon: true },
    ],
  },
  {
    icon: "fa-triangle-exclamation",
    label: "Cảnh báo sớm",
    roles: ["admin", "lecturer"],
    links: [
      { label: "Cảnh báo của tôi", href: "alerts.html" },
      { label: "Lịch sử gửi email", href: "emails.html" },
    ],
  },
  {
    icon: "fa-brain",
    label: "Mô hình AI",
    roles: ["admin", "lecturer"],
    links: [
      { label: "So sánh mô hình", href: "models.html" },
      { label: "Sức khỏe AI", href: "ai-health.html", roles: ["admin"] },
    ],
  },
  {
    icon: "fa-user-shield",
    label: "Hệ thống",
    roles: ["admin"],
    links: [
      { label: "Tài khoản & phân quyền", href: "users.html" },
      { label: "Nhật ký hệ thống", soon: true },
    ],
  },
  // ---- Sinh viên
  { icon: "fa-book-open", label: "Kết quả học tập", href: "my-results.html", roles: ["student"] },
  { icon: "fa-calendar-check", label: "Điểm danh", href: "my-attendance.html", roles: ["student"] },
  { icon: "fa-lightbulb", label: "Lời nhắc học tập", href: "alerts.html", roles: ["student"] },
];

const SIDEBAR_KEY = "eduagent.sidebarCollapsed";
// api.js chưa nạp được hoặc trình duyệt còn giữ bản cũ trong bộ nhớ đệm (thiếu getAuth):
// mở trang đăng nhập bằng một địa chỉ mới để trình duyệt tải lại toàn bộ thay vì hiện trang lỗi.
const API_READY = typeof getAuth === "function" && typeof goToLogin === "function";
const AUTH = API_READY ? getAuth() : null;
const CURRENT_USER = AUTH?.user ?? null;

// Menu sau khi lọc theo vai trò và điều kiện của người đang đăng nhập
function visibleMenu(user) {
  const allowed = (entry) => (!entry.roles || entry.roles.includes(user.role)) && (!entry.when || entry.when(user));
  return MENU.filter(allowed)
    .map((item) => (item.links ? { ...item, links: item.links.filter(allowed) } : item))
    .filter((item) => !item.links || item.links.length);
}

// Trang đang mở: cùng đường dẫn, mọi tham số của mục menu đều có trên địa chỉ hiện tại; mục nhiều tham số hơn được ưu tiên
// (vd teaching.html?mode=grades&section=5 khớp "Nhập điểm" chứ không phải "Lớp học phần của tôi")
// Trang con không có mục menu riêng: sáng mục cha
const PAGE_PARENT = { "student.html": "manage-students.html" };

function findCurrentHref(menu) {
  let here = location.pathname.endsWith("/") ? location.pathname + "index.html" : location.pathname;
  const page = here.split("/").pop();
  if (PAGE_PARENT[page]) here = here.slice(0, -page.length) + PAGE_PARENT[page];
  const current = new URLSearchParams(location.search);
  const hrefs = menu.flatMap((item) => (item.links ? item.links : [item])).filter((l) => l.href).map((l) => l.href);
  return hrefs
    .map((href) => ({ href, url: new URL(href, location.href) }))
    .filter((p) => p.url.pathname === here && [...p.url.searchParams].every(([k, v]) => current.get(k) === v))
    .sort((a, b) => [...b.url.searchParams].length - [...a.url.searchParams].length)[0]?.href;
}

function initials(name) {
  const words = name.trim().split(/\s+/);
  return (words.length > 1 ? words[0][0] + words[words.length - 1][0] : words[0].slice(0, 2)).toUpperCase();
}

function renderSidebar(menu, currentHref) {
  const items = menu.map((item) => {
    if (!item.links) {
      if (item.soon) {
        return `<li class="menu-item"><a class="menu-btn soon" aria-disabled="true" title="${item.label} (sắp có)">
          <i class="fas ${item.icon} icon"></i><span class="menu-text">${item.label}</span><span class="soon-tag">Sắp có</span>
        </a></li>`;
      }
      return `<li class="menu-item">
        <a class="menu-btn${item.href === currentHref ? " current" : ""}" href="${item.href}" title="${item.label}">
          <i class="fas ${item.icon} icon"></i><span class="menu-text">${item.label}</span>
        </a>
      </li>`;
    }
    const open = item.links.some((l) => l.href === currentHref);
    const links = item.links
      .map((l, i) =>
        l.soon
          ? `<li style="--i: ${i}"><a class="soon" aria-disabled="true">${l.label}<span class="soon-tag">Sắp có</span></a></li>`
          : `<li style="--i: ${i}"><a href="${l.href}"${l.href === currentHref ? ' class="current"' : ""}>${l.label}</a></li>`
      )
      .join("");
    return `<li class="menu-item${open ? " active" : ""}">
      <button class="menu-btn" type="button" data-submenu title="${item.label}">
        <i class="fas ${item.icon} icon"></i><span class="menu-text">${item.label}</span>
        <i class="fas fa-chevron-right arrow"></i>
      </button>
      <div class="sub-menu-wrap"><div class="sub-menu-clip"><ul class="sub-menu">${links}</ul></div></div>
    </li>`;
  }).join("");

  return `<nav class="sidebar" id="sidebar">
    <a class="sidebar-header" href="${ROLE_HOME[CURRENT_USER.role]}" title="EduAgent - Cảnh báo sớm học tập">
      <img class="brand-logo" src="images/logo-dainam.svg" alt="Trường Đại học Đại Nam"
           onerror="this.onerror=null; this.src='images/logo.svg'" />
      <span class="brand-text">
        <span class="brand-school">ĐẠI NAM</span>
        <span class="brand-sub">EduAgent · Cảnh báo sớm</span>
      </span>
    </a>
    <ul class="menu">${items}</ul>
  </nav>`;
}

function renderNavbar(title) {
  const user = CURRENT_USER;
  const staff = user.role !== "student";
  const q = new URLSearchParams(location.search).get("q") ?? "";
  // Ô tìm sinh viên và chuông cảnh báo chỉ dành cho quản trị, giảng viên
  const search = staff
    ? `<form class="nav-search" action="manage-students.html" role="search">
        <input type="search" name="q" value="${escapeHtml(q)}" placeholder="Tìm sinh viên theo mã, họ tên..." aria-label="Tìm sinh viên" />
        <button type="submit" title="Tìm"><i class="fas fa-search"></i></button>
      </form>`
    : "";
  // Chuông: số cảnh báo / lời nhắc chưa đọc AI Agent gửi tới tài khoản này
  const bell = `<a class="nav-bell" href="alerts.html" title="${staff ? "Cảnh báo chưa đọc" : "Lời nhắc học tập"}">
      <i class="fas fa-bell"></i><span class="nav-bell-count" id="bellCount" hidden></span>
    </a>`;
  return `<header class="top-navbar">
    <div class="nav-left">
      <button class="toggle-btn" id="toggleBtn" type="button" title="Thu gọn / mở rộng menu"><i class="fas fa-bars"></i></button>
      <h2 class="page-title-nav">${escapeHtml(title)}</h2>
    </div>
    <div class="nav-center">${search}</div>
    <div class="nav-right">
      ${bell}
      <a class="user-link" href="account.html" id="userBtn" title="Tài khoản: ${escapeHtml(user.username)} (email nhận cảnh báo, đổi mật khẩu)">
        <div class="user-info">
          <strong>${escapeHtml(user.full_name)}</strong>
          <span>${escapeHtml(user.role_label)}</span>
        </div>
        <div class="avatar">${escapeHtml(initials(user.full_name))}</div>
      </a>
      <button class="toggle-btn" type="button" id="logoutBtn" title="Đăng xuất"><i class="fas fa-right-from-bracket"></i></button>
    </div>
  </header>`;
}

function readCollapsed() {
  // Màn hình hẹp luôn bắt đầu với menu thu gọn để nhường chỗ cho nội dung
  if (window.matchMedia("(max-width: 760px)").matches) return true;
  try {
    return localStorage.getItem(SIDEBAR_KEY) === "1";
  } catch {
    return false;
  }
}

function saveCollapsed(collapsed) {
  try {
    localStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0");
  } catch {
    // trình duyệt chặn localStorage: bỏ qua, chỉ không nhớ được trạng thái
  }
}

// Kiểm tra đăng nhập và vai trò trước khi vẽ trang. Trả về false nếu đang chuyển trang.
function guardPage() {
  if (!API_READY) {
    location.replace(`login.html?fresh=${Date.now()}`);
    return false;
  }
  if (!CURRENT_USER) {
    goToLogin();
    return false;
  }
  const roles = document.body.dataset.roles?.split(",").map((r) => r.trim()).filter(Boolean);
  if (roles?.length && !roles.includes(CURRENT_USER.role)) {
    location.replace(ROLE_HOME[CURRENT_USER.role]);
    return false;
  }
  return true;
}

// Trang đổi địa chỉ mà không tải lại (vd teaching.html đổi ?mode=): đánh dấu lại mục menu đang mở
function refreshMenuCurrent() {
  const menu = visibleMenu(CURRENT_USER);
  const href = findCurrentHref(menu);
  document.querySelectorAll("#sidebar a[href]").forEach((a) =>
    a.classList.toggle("current", a.getAttribute("href") === href));
}

function initLayout() {
  if (!guardPage()) {
    document.querySelector("main")?.remove(); // không lộ nội dung trong lúc chuyển trang
    return;
  }
  const main = document.querySelector("main");
  const title = document.body.dataset.title ?? "EduAgent";
  document.title = `${title} · EduAgent`;

  const menu = visibleMenu(CURRENT_USER);
  document.body.insertAdjacentHTML("afterbegin", renderSidebar(menu, findCurrentHref(menu)));
  const wrapper = document.createElement("div");
  wrapper.className = "main-content";
  wrapper.innerHTML = renderNavbar(title);
  const contentBody = document.createElement("div");
  contentBody.className = "content-body";
  contentBody.append(main);
  wrapper.append(contentBody);
  document.getElementById("sidebar").after(wrapper);

  const sidebar = document.getElementById("sidebar");
  if (readCollapsed()) sidebar.classList.add("collapsed");

  document.getElementById("toggleBtn").addEventListener("click", () => {
    const collapsed = sidebar.classList.toggle("collapsed");
    if (collapsed) document.querySelectorAll(".menu-item.active").forEach((el) => el.classList.remove("active"));
    saveCollapsed(collapsed);
  });

  // Bấm nhóm menu: mở nhóm đó, đóng các nhóm khác (menu đang thu gọn thì mở rộng ra trước)
  sidebar.querySelectorAll("[data-submenu]").forEach((button) => {
    button.addEventListener("click", () => {
      if (sidebar.classList.contains("collapsed")) {
        sidebar.classList.remove("collapsed");
        saveCollapsed(false);
      }
      const parent = button.parentElement;
      sidebar.querySelectorAll(".menu-item").forEach((el) => el !== parent && el.classList.remove("active"));
      parent.classList.toggle("active");
    });
  });

  document.getElementById("logoutBtn").addEventListener("click", () => {
    clearAuth();
    location.href = "login.html";
  });

  loadBellCount();
  refreshCurrentUser();
}

// Cập nhật thông tin tài khoản (vd vừa được phân công CVHT); token hết hạn thì api() tự chuyển về đăng nhập
async function refreshCurrentUser() {
  try {
    const user = await apiGet("/auth/me");
    updateAuthUser(user);
    showEmailBanner(user);
  } catch {
    // mất kết nối tạm thời: giữ thông tin cũ
  }
}

// Mỗi tài khoản cần liên kết email để nhận cảnh báo: nhắc trên mọi trang cho tới khi liên kết xong
function showEmailBanner(user) {
  if (user.email_verified || location.pathname.endsWith("account.html") || document.getElementById("email-banner")) return;
  const text = user.role === "student"
    ? "Bạn chưa liên kết email: lời nhắc học tập sẽ không được gửi tới hộp thư của bạn."
    : "Tài khoản chưa liên kết email: bạn sẽ không nhận được email cảnh báo sinh viên.";
  document.querySelector("main")?.insertAdjacentHTML("afterbegin",
    `<div class="alert-warning email-banner" id="email-banner"><i class="fas fa-envelope"></i>
      <span>${text}</span><a class="btn btn-primary btn-sm" href="account.html">Liên kết email</a></div>`);
}

// Chuông thông báo: số cảnh báo chưa đọc
async function loadBellCount() {
  try {
    const { unread } = await apiGet("/alerts/mine?limit=1");
    const badge = document.getElementById("bellCount");
    badge.textContent = unread > 99 ? "99+" : unread;
    badge.hidden = unread === 0;
  } catch {
    // backend hoặc MySQL chưa chạy: trang vẫn hiển thị, chỉ không có số trên chuông
  }
}

initLayout();

// Chuyển trang mượt: trình duyệt chạy View Transitions (style.css) thì để nó lo; không chạy (trình duyệt cũ,
// trình duyệt nhúng tắt tính năng này) thì cho phần nội dung hiện dần, thanh bên và thanh trên vẫn đứng yên.
if ("onpagereveal" in window) {
  addEventListener("pagereveal", (e) => {
    if (!e.viewTransition) document.documentElement.classList.add("page-enter");
  });
} else {
  document.documentElement.classList.add("page-enter");
}
