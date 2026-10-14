// Thu vien nho dung chung: tao DOM an toan (khong innerHTML voi du lieu), goi API, dinh dang, thong bao, hop thoai.

// ------------------------------------------------------------------ DOM
export function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k === "style") Object.assign(el.style, v);
    else if (k === "value" || k === "checked" || k === "disabled" || k === "selected") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  append(el, kids);
  return el;
}

export function append(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k == null || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return el;
}

const SVG = "http://www.w3.org/2000/svg";
export function icon(name, cls = "") {
  const s = document.createElementNS(SVG, "svg");
  s.setAttribute("class", `ico ${cls}`.trim());
  s.setAttribute("aria-hidden", "true");
  const u = document.createElementNS(SVG, "use");
  u.setAttribute("href", `#i-${name}`);
  s.append(u);
  return s;
}

export function clear(el) { el.replaceChildren(); return el; }

// O nhap co nhan gan dung (trinh doc man hinh doc duoc ten o)
let fieldSeq = 0;
export function field(labelText, input, hint) {
  const id = input.id || `f${++fieldSeq}`;
  input.id = id;
  return h("div", { class: "field" }, h("label", { for: id, text: labelText }), input,
    hint ? h("span", { class: "hint", text: hint }) : null);
}

// ------------------------------------------------------------------ API
let csrfToken = "";
export function setCsrf(t) { csrfToken = t || ""; }

export class ApiError extends Error {
  constructor(status, message, code) { super(message); this.status = status; this.code = code; }
}

export async function api(path, { method = "GET", body, signal } = {}) {
  const opts = { method, headers: { Accept: "application/json" }, credentials: "same-origin", signal };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  if (method !== "GET") opts.headers["X-CSRF-Token"] = csrfToken;
  let r;
  try {
    r = await fetch(path, opts);
  } catch (e) {
    if (e.name === "AbortError") throw e;
    throw new ApiError(0, "Không kết nối được máy chủ. Kiểm tra mạng / Tailscale.", "network");
  }
  let data = null;
  try { data = await r.json(); } catch { /* khong co than JSON */ }
  if (!r.ok) {
    const err = new ApiError(r.status, (data && data.message) || `Lỗi máy chủ (${r.status})`, data && data.error);
    if (r.status === 401 && path !== "/api/ui/login") window.dispatchEvent(new CustomEvent("auth-lost"));
    throw err;
  }
  return data;
}

// ------------------------------------------------------------------ dinh dang
const nf1 = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 1 });
const nf0 = new Intl.NumberFormat("vi-VN");
export const fmtInt = (n) => (n == null ? "–" : nf0.format(n));

export function fmtBytes(n) {
  if (n == null) return "–";
  if (n < 1024) return `${nf0.format(n)} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n / 1024, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v >= 100 ? nf0.format(Math.round(v)) : nf1.format(v)} ${units[i]}`;
}

const dtf = new Intl.DateTimeFormat("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
const tf = new Intl.DateTimeFormat("vi-VN", { hour: "2-digit", minute: "2-digit" });
const rtf = new Intl.RelativeTimeFormat("vi", { numeric: "auto" });

export function fmtDate(iso) {
  if (!iso) return "–";
  const d = new Date(iso);
  return isNaN(d) ? iso : dtf.format(d);
}

export function fmtRelative(iso, now = Date.now()) {
  if (!iso) return "–";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const s = Math.round((d - now) / 1000);
  const a = Math.abs(s);
  if (a < 45) return s <= 0 ? "vừa xong" : "trong giây lát";
  if (a < 3600) return rtf.format(Math.round(s / 60), "minute");
  if (a < 86400) return rtf.format(Math.round(s / 3600), "hour");
  if (a < 86400 * 7) return `${rtf.format(Math.round(s / 86400), "day")}, ${tf.format(d)}`;
  return dtf.format(d);
}

export function fmtDuration(sec) {
  if (sec == null || isNaN(sec)) return "–";
  sec = Math.max(0, Math.round(sec));
  if (sec < 60) return `${sec} giây`;
  const m = Math.floor(sec / 60), s = sec % 60;
  if (m < 60) return s ? `${m} phút ${s} giây` : `${m} phút`;
  const hh = Math.floor(m / 60);
  return `${hh} giờ ${m % 60} phút`;
}

export function secondsBetween(a, b) {
  if (!a) return null;
  return ((b ? new Date(b) : new Date()) - new Date(a)) / 1000;
}

// ------------------------------------------------------------------ nhan tieng Viet
export const COMPONENTS = {
  files: { label: "Thư mục dữ liệu", desc: "File trong các thư mục bạn chọn", group: "data" },
  ipv4: { label: "IPv4", desc: "Địa chỉ, subnet mask, gateway, DNS", group: "net" },
  ipv6: { label: "IPv6", desc: "Địa chỉ, prefix, gateway, DNS", group: "net" },
  firewall: { label: "Tường lửa", desc: "3 profile và các rule đang bật", group: "net" },
  hosts: { label: "File hosts", desc: "Bản ghi tên miền nội bộ", group: "net" },
  shares: { label: "Thư mục chia sẻ", desc: "Các share SMB", group: "net" },
  route: { label: "Định tuyến tĩnh", desc: "Persistent route", group: "net" },
  portproxy: { label: "Port proxy", desc: "Chuyển tiếp cổng netsh", group: "net" },
  defender: { label: "Windows Defender", desc: "Trạng thái bảo vệ thời gian thực", group: "sys" },
};
export const ALL_COMPONENTS = Object.keys(COMPONENTS);
export const compLabel = (c) => (COMPONENTS[c] ? COMPONENTS[c].label : c);

export const JOB_STATUS = {
  pending: { label: "Đang chờ", cls: "info", icon: "clock" },
  running: { label: "Đang chạy", cls: "info", icon: "loader" },
  completed: { label: "Thành công", cls: "ok", icon: "ok" },
  failed: { label: "Thất bại", cls: "err", icon: "err" },
  cancelled: { label: "Đã huỷ", cls: "", icon: "stop" },
};
export const JOB_TYPE = { backup: "Sao lưu", restore: "Khôi phục" };

export function statusPill(status) {
  const s = JOB_STATUS[status] || { label: status, cls: "", icon: "info" };
  const ic = icon(s.icon);
  if (status === "running") ic.classList.add("spin");
  return h("span", { class: `pill ${s.cls}` }, ic, s.label);
}

export function jobTitle(j) {
  if (j.type === "restore") return j.params && j.params.dry_run ? "Chạy thử khôi phục" : "Khôi phục";
  return j.params && j.params.schedule_id ? "Sao lưu theo lịch" : "Sao lưu";
}

// ------------------------------------------------------------------ thong bao
export function toast(message, kind = "ok", timeout) {
  const box = document.getElementById("toasts");
  const ico = { ok: "ok", err: "alert", info: "info" }[kind] || "info";
  const close = h("button", { class: "btn btn-ghost btn-sm btn-icon", "aria-label": "Đóng" }, icon("x", "ico-sm"));
  const t = h("div", { class: `toast ${kind}`, role: kind === "err" ? "alert" : "status" },
    icon(ico), h("div", { class: "grow", text: message }), close);
  const remove = () => { t.classList.add("out"); setTimeout(() => t.remove(), 220); };
  close.addEventListener("click", remove);
  box.append(t);
  setTimeout(remove, timeout || (kind === "err" ? 7000 : 4000));
}

// ------------------------------------------------------------------ hop thoai
export function dialog({ title, body, actions, wide = false, onClose }) {
  const dlg = h("dialog", { class: `dlg${wide ? " wide" : ""}`, "aria-labelledby": "dlg-title" },
    h("div", { class: "dlg-head" }, h("h2", { id: "dlg-title", text: title })),
    body,
    actions ? h("div", { class: "dlg-foot" }, actions) : null);
  dlg.addEventListener("close", () => { dlg.remove(); if (onClose) onClose(dlg.returnValue); });
  document.body.append(dlg);
  dlg.showModal();
  return dlg;
}

export function confirmDialog({ title, message, items, confirmLabel = "Đồng ý", danger = false }) {
  return new Promise((resolve) => {
    let ok = false;
    const cancel = h("button", { class: "btn", type: "button" }, "Huỷ");
    const yes = h("button", { class: `btn ${danger ? "btn-danger-solid" : "btn-primary"}`, type: "button" }, confirmLabel);
    const dlg = dialog({
      title,
      body: h("div", { class: "dlg-body" }, h("p", { text: message }),
        items && items.length ? h("ul", {}, items.map((t) => h("li", { text: t }))) : null),
      actions: [cancel, yes],
      onClose: () => resolve(ok),
    });
    cancel.addEventListener("click", () => dlg.close());
    yes.addEventListener("click", () => { ok = true; dlg.close(); });
    (danger ? cancel : yes).focus();
  });
}

// ------------------------------------------------------------------ tien ich
export async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch { /* thu cach cu */ }
  const ta = h("textarea", { class: "sr-only", readonly: true });
  ta.value = text;
  document.body.append(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch { ok = false; }
  ta.remove();
  return ok;
}

export function busy(btn, on, label) {
  if (on) {
    btn._label = btn._label || [...btn.childNodes];
    btn.disabled = true;
    const ic = icon("loader");
    ic.classList.add("spin");
    btn.replaceChildren(ic, label || "Đang xử lý…");
  } else {
    btn.disabled = false;
    if (btn._label) btn.replaceChildren(...btn._label);
    btn._label = null;
  }
}

export const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* bo qua */ } },
};

export function emptyState(iconName, title, text, action) {
  return h("div", { class: "empty" }, icon(iconName), h("h3", { text: title }), text ? h("p", { text }) : null, action || null);
}

export function skeletonRows(n = 3) {
  return h("div", { class: "panel-body" }, Array.from({ length: n }, (_, i) =>
    h("span", { class: "skel", style: { width: `${90 - i * 12}%` } })));
}
