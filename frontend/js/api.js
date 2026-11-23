// Hàm gọi API dùng chung cho mọi trang.
// Mở giao diện qua backend (http://127.0.0.1:8000) thì gọi đường dẫn tương đối;
// mở bằng Live Server (cổng 5500) thì gọi sang backend ở cổng 8000.
const API_BASE = location.port === "5500" ? "http://127.0.0.1:8000/api" : "/api";

// ---- Phiên đăng nhập -------------------------------------------------------------
// Lưu token + thông tin người dùng trong localStorage của trình duyệt sau khi đăng nhập.
const AUTH_KEY = "eduagent.auth";
// Trang mở đầu của từng vai trò
const ROLE_HOME = { admin: "index.html", lecturer: "teaching.html", student: "my-results.html" };

function getAuth() {
  try {
    const auth = JSON.parse(localStorage.getItem(AUTH_KEY));
    return auth && auth.token && auth.expires_at > Date.now() ? auth : null;
  } catch {
    return null;
  }
}

function saveAuth(loginResponse) {
  const auth = {
    token: loginResponse.access_token,
    expires_at: Date.now() + loginResponse.expires_in * 1000,
    user: loginResponse.user,
  };
  localStorage.setItem(AUTH_KEY, JSON.stringify(auth));
  return auth;
}

function updateAuthUser(user) {
  const auth = getAuth();
  if (auth) localStorage.setItem(AUTH_KEY, JSON.stringify({ ...auth, user }));
}

function clearAuth() {
  try {
    localStorage.removeItem(AUTH_KEY);
  } catch {
    // bỏ qua
  }
}

// Về trang đăng nhập, nhớ trang đang mở để đăng nhập xong quay lại
function goToLogin() {
  clearAuth();
  const here = location.pathname.split("/").pop() + location.search;
  location.replace(`login.html?next=${encodeURIComponent(here)}`);
}

async function api(path, options = {}) {
  const token = getAuth()?.token;
  let response;
  try {
    response = await fetch(API_BASE + path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...options.headers,
      },
    });
  } catch {
    throw new Error("Không gọi được backend. Đã chạy start.bat (hoặc uvicorn) chưa?");
  }

  const data = await response.json().catch(() => null);
  // Hết phiên hoặc token không hợp lệ: quay về đăng nhập (trừ chính lời gọi đăng nhập)
  if (response.status === 401 && !path.startsWith("/auth/login")) {
    goToLogin();
    throw new Error("Phiên đăng nhập đã hết hạn");
  }
  if (!response.ok) {
    // FastAPI trả lỗi dạng {"detail": "..."} hoặc {"detail": [{msg: ...}]} khi dữ liệu không hợp lệ
    const detail = data?.detail;
    const message = Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : detail;
    throw new Error(message || `Lỗi ${response.status}`);
  }
  return data;
}

const apiGet = (path) => api(path);
const apiPost = (path, body) => api(path, { method: "POST", body: JSON.stringify(body ?? {}) });
const apiPatch = (path, body) => api(path, { method: "PATCH", body: JSON.stringify(body ?? {}) });
const apiPut = (path, body) => api(path, { method: "PUT", body: JSON.stringify(body ?? {}) });

function formatScore(value) {
  return value == null ? "" : Number(value).toFixed(1);
}

function showError(container, error) {
  container.innerHTML = `<div class="alert-error"><i class="fas fa-exclamation-triangle"></i> ${escapeHtml(error.message)}</div>`;
}

function showSuccess(container, message) {
  container.innerHTML = `<div class="alert-success"><i class="fas fa-check-circle"></i> ${escapeHtml(message)}</div>`;
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value ?? "";
  return div.innerHTML;
}

function formatPercent(value) {
  return value == null ? "–" : `${(value * 100).toFixed(1)}%`;
}
