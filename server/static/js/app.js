// Khung ung dung: dang nhap, dieu huong (#/...), poll trang thai, thanh tien do toan cuc.
import { api, ApiError, busy, field, fmtRelative, h, icon, jobTitle, setCsrf, statusPill, toast } from "./lib.js";
import { backupView, backupsView, jobsView, overviewView, schedulesView, settingsView, usersView } from "./views.js";

const root = document.getElementById("app");
const bus = new EventTarget();
const state = { session: null, overview: null };

const ROUTES = [
  { path: "", title: "Tổng quan", icon: "home", view: overviewView },
  { path: "sao-luu", title: "Sao lưu", icon: "upload", view: backupView },
  { path: "ban-sao-luu", title: "Bản sao lưu", icon: "archive", view: backupsView },
  { path: "tac-vu", title: "Tác vụ", icon: "list", view: jobsView },
  { path: "lich", title: "Lịch", icon: "clock", view: schedulesView },
  { path: "nguoi-dung", title: "Người dùng", icon: "users", view: usersView, admin: true },
  { path: "cai-dat", title: "Cài đặt", icon: "sliders", view: settingsView },
];

const ctx = {
  state,
  on(name, fn) { bus.addEventListener(name, fn); return () => bus.removeEventListener(name, fn); },
  emit(name, detail) { bus.dispatchEvent(new CustomEvent(name, { detail })); },
  refresh() { poller.now(); },
  setTheme(pref) {
    try { localStorage.setItem("bks-theme", pref); } catch { /* bo qua */ }
    const dark = pref === "dark" || (pref === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  },
};

// ------------------------------------------------------------------ poll trang thai
const poller = (() => {
  let timer = null, running = false, prevActive = null, first = true;

  async function tick() {
    clearTimeout(timer);
    if (!state.session) return;
    running = true;
    try {
      const ov = await api("/api/ui/overview");
      const act = ov.active_job;
      if (!first) {
        if (act && (!prevActive || act.id !== prevActive.id)) ctx.emit("job-started", act);
        if (prevActive && (!act || act.id !== prevActive.id)) {
          const done = ov.jobs.find((j) => j.id === prevActive.id);
          if (done) {
            ctx.emit("job-done", done);
            const kind = done.status === "completed" ? "ok" : done.status === "failed" ? "err" : "info";
            toast(`${jobTitle(done)} #${done.id}: ${done.message || done.status}`, kind, 8000);
          }
        }
      }
      first = false;
      prevActive = act;
      state.overview = ov;
      ctx.emit("overview", ov);
      renderChrome();
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 401) renderOffline(e.message);
    } finally {
      running = false;
      const delay = document.hidden ? 15000 : state.overview && state.overview.active_job ? 1500 : 5000;
      timer = setTimeout(tick, delay);
    }
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden && state.session && !running) tick(); });
  return { now: () => { if (!running) tick(); }, stop: () => { clearTimeout(timer); first = true; prevActive = null; } };
})();

// ------------------------------------------------------------------ dang nhap
function renderLogin(note) {
  poller.stop();
  current && current.destroy && current.destroy();
  current = null;
  const user = h("input", { class: "input", name: "username", autocomplete: "username", required: true, autofocus: true });
  const pass = h("input", { class: "input", type: "password", name: "password", autocomplete: "current-password", required: true });
  const err = h("div", { class: "form-error", role: "alert", hidden: !note }, note ? [icon("alert", "ico-sm"), note] : null);
  const btn = h("button", { class: "btn btn-primary", type: "submit" }, "Đăng nhập");
  const form = h("form", { class: "panel", onsubmit: async (e) => {
    e.preventDefault();
    err.hidden = true;
    busy(btn, true, "Đang đăng nhập…");
    try {
      const s = await api("/api/ui/login", { method: "POST", body: { username: user.value.trim(), password: pass.value } });
      start(s);
    } catch (ex) {
      err.replaceChildren(icon("alert", "ico-sm"), ex.message);
      err.hidden = false;
      pass.select();
    } finally { busy(btn, false); }
  } }, h("div", { class: "panel-body" },
    h("h1", { text: "Đăng nhập" }), h("p", { class: "subtle", style: { marginBottom: "20px" }, text: "Bảng điều khiển sao lưu" }),
    field("Tên đăng nhập", user),
    field("Mật khẩu", pass),
    err, btn));
  root.replaceChildren(h("main", { class: "login" }, h("div", { class: "login-box" },
    h("div", { class: "brand" }, h("span", { class: "brand-mark" }, icon("shield")),
      h("div", { class: "brand-text" }, h("div", { class: "brand-name", text: "Backup System" }), h("div", { class: "brand-sub", text: "HUTECH · ĐACN" }))),
    form)));
  document.title = "Đăng nhập · Backup System";
  user.focus();
}

window.addEventListener("auth-lost", () => {
  if (state.session) { state.session = null; renderLogin("Phiên đăng nhập đã hết. Hãy đăng nhập lại."); }
});

// ------------------------------------------------------------------ khung
let nav, agentMini, jobStrip, viewHost, current = null;

function renderShell() {
  const s = state.session;
  nav = h("nav", { class: "nav", "aria-label": "Điều hướng chính" },
    ROUTES.filter((r) => !r.admin || s.user.role === "admin").map((r) =>
      h("a", { href: `#/${r.path}`, dataset: { path: r.path }, title: r.title }, icon(r.icon), h("span", { text: r.title }))));
  agentMini = h("a", { class: "agent-mini", href: "#/cai-dat", title: "Trạng thái agent" });
  const logout = h("button", { class: "btn btn-ghost btn-sm btn-icon", type: "button", "aria-label": "Đăng xuất", title: "Đăng xuất" }, icon("logout"));
  logout.addEventListener("click", async () => {
    try { await api("/api/ui/logout", { method: "POST" }); } catch { /* van thoat */ }
    state.session = null;
    renderLogin();
  });
  jobStrip = h("div", { class: "job-strip", hidden: true, role: "status" });
  viewHost = h("div");
  root.replaceChildren(h("div", { class: "app" },
    h("aside", { class: "sidebar" },
      h("a", { class: "brand", href: "#/", "aria-label": "Trang tổng quan" }, h("span", { class: "brand-mark" }, icon("shield")),
        h("div", { class: "brand-text" }, h("div", { class: "brand-name", text: "Backup System" }), h("div", { class: "brand-sub", text: `v${s.version}` }))),
      nav,
      h("div", { class: "sidebar-foot" }, agentMini,
        h("div", { class: "user-mini" }, h("span", { class: "truncate" }, h("strong", { text: s.user.username })),
          h("span", { class: "chip role", text: s.user.role === "admin" ? "Quản trị" : "Người dùng" }), logout))),
    h("main", { class: "main", id: "main" }, h("div", { class: "main-inner" }, jobStrip, viewHost))));
  renderChrome();
}

function renderChrome() {
  if (!agentMini) return;
  const ov = state.overview;
  const ag = ov && (ov.agents || []).find((a) => a.online);
  agentMini.replaceChildren(h("span", { class: `dot ${ag ? "ok" : ov ? "err" : ""}` }),
    h("span", { class: "truncate", text: !ov ? "Đang kiểm tra…" : ag ? `Agent: ${ag.hostname}` : "Agent chưa kết nối" }));
  // thanh tien do o moi trang tru Tong quan (o do da co khung lon)
  const j = ov && ov.active_job;
  const onOverview = currentPath() === "";
  if (!j || onOverview) { jobStrip.hidden = true; jobStrip._id = null; return; }
  jobStrip.hidden = false;
  if (jobStrip._id === j.id && jobStrip._status === j.status) {
    jobStrip._fill.style.transform = `scaleX(${j.progress / 100})`;
    jobStrip._pct.textContent = j.status === "pending" ? "" : `${j.progress}%`;
    return;
  }
  const fill = h("i", { style: { transform: `scaleX(${j.progress / 100})` } });
  const pct = h("span", { class: "pct num", text: j.status === "pending" ? "" : `${j.progress}%` });
  jobStrip.replaceChildren(statusPill(j.status), h("strong", { class: "nowrap", text: `${jobTitle(j)} #${j.id}` }),
    h("div", { class: `bar${j.status === "pending" ? " indeterminate" : ""}` }, fill), pct,
    h("a", { class: "btn btn-sm btn-ghost", href: "#/" }, "Chi tiết", icon("chev", "ico-sm")));
  Object.assign(jobStrip, { _id: j.id, _status: j.status, _fill: fill, _pct: pct });
}

function renderOffline(message) {
  if (!agentMini) return;
  agentMini.replaceChildren(h("span", { class: "dot warn" }), h("span", { class: "truncate", text: "Mất kết nối máy chủ" }));
  agentMini.title = message;
}

function currentPath() {
  return (location.hash.replace(/^#\/?/, "").split("/")[0] || "");
}

function route() {
  if (!state.session) return;
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  let r = ROUTES.find((x) => x.path === (parts[0] || ""));
  if (!r || (r.admin && state.session.user.role !== "admin")) r = ROUTES[0];
  if (current && current.destroy) current.destroy();
  current = r.view(ctx, parts[1]);
  viewHost.replaceChildren(current.el);
  nav.querySelectorAll("a").forEach((a) => {
    if (a.dataset.path === r.path) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  document.title = `${r.title} · Backup System`;
  renderChrome();
  document.getElementById("main").scrollTo?.(0, 0);
  window.scrollTo(0, 0);
}

window.addEventListener("hashchange", route);

function start(session) {
  state.session = session;
  setCsrf(session.csrf);
  renderShell();
  route();
  poller.now();
}

// ------------------------------------------------------------------ khoi dong
(async () => {
  try {
    start(await api("/api/ui/session"));
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) renderLogin();
    else root.replaceChildren(h("div", { class: "login" }, h("div", { class: "empty" }, icon("alert"),
      h("h3", { text: "Không kết nối được máy chủ" }), h("p", { text: e.message }),
      h("button", { class: "btn btn-primary", type: "button", onclick: () => location.reload() }, icon("refresh"), "Thử lại"))));
  }
})();

export { fmtRelative };
