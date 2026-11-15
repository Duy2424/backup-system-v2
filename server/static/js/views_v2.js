// Tuan 4 (B): Tong quan v2 - RPO xanh/vang/do, may duoc bao ve, snapshot gan day, ti le khu trung lap, tinh trang kho.
// Tuan 6 (B): Thong bao (su kien + xac nhan Binh thuong / Su co, dong bo voi nut Telegram); Cai dat: Kho v2, Telegram.
import {
  ACK, EVENT_KIND, api, busy, confirmDialog, emptyState, field, fmtBytes, fmtDate, fmtDuration, fmtHours, fmtInt, fmtRatio,
  fmtRelative, h, icon, jobTitle, rpoPill, secondsBetween, skeletonRows, statusPill, store, toast,
} from "./lib.js";
import { agentOnline, pageHead, startBackup } from "./views.js";

const PRESET_KEY = "bks-last-backup";

function cell(label, iconName, value, meta, cls = "") {
  return h("div", { class: `status-cell ${cls}`.trim() },
    h("div", { class: "status-label" }, icon(iconName, "ico-sm"), label),
    h("div", { class: "status-value" }, value), meta ? h("div", { class: "status-meta" }, meta) : null);
}

function isOpen(ev) { return !ev.ack && (ev.level === "warn" || ev.level === "err"); }

// Mot dong su kien. compact: khong hien noi dung dai va nut xac nhan (dung o Tong quan).
function eventRow(ev, { compact = false, onAck } = {}) {
  const open = isOpen(ev);
  const meta = [fmtRelative(ev.created_at), EVENT_KIND[ev.kind] || ev.kind, ev.telegram ? "đã gửi Telegram" : null]
    .filter(Boolean).join(" · ");
  const right = h("div", { class: "event-right" });
  if (ev.ack) {
    right.append(h("span", { class: `pill ${ev.ack === "su_co" ? "err" : "ok"}` }, icon(ev.ack === "su_co" ? "alert" : "check"),
      `${ACK[ev.ack]}${ev.ack_by ? ` · ${ev.ack_by}` : ""}`));
  } else if (open && onAck && !compact) {
    const ok = h("button", { class: "btn btn-sm", type: "button" }, icon("check", "ico-sm"), "Bình thường");
    const bad = h("button", { class: "btn btn-sm btn-danger", type: "button" }, icon("alert", "ico-sm"), "Sự cố");
    ok.addEventListener("click", () => onAck(ev, "binh_thuong", ok));
    bad.addEventListener("click", () => onAck(ev, "su_co", bad));
    right.append(h("div", { class: "ack-row" }, ok, bad));
  } else if (open) {
    right.append(h("span", { class: "pill warn" }, "Chưa xác nhận"));
  }
  return h("div", { class: `event${open ? " open" : ""}` },
    h("span", { class: `lvl ${ev.level}`, "aria-hidden": "true" }),
    h("div", { class: "grow" }, h("div", { class: "t", text: ev.title }),
      ev.message && !compact ? h("div", { class: "m", text: ev.message }) : null,
      h("div", { class: "meta", text: meta })),
    right);
}

async function ackEvent(ctx, ev, verdict, btn) {
  busy(btn, true, "Đang ghi…");
  try {
    await api(`/api/ui/events/${ev.id}/ack`, { method: "POST", body: { verdict } });
    toast(`Đã ghi nhận: ${ACK[verdict]}`);
    ctx.refresh();
    return true;
  } catch (e) { toast(e.message, "err"); busy(btn, false); return false; }
}

function khoCell(ov, kho, dd, disk) {
  if (kho && kho.reachable) {
    const meta = [`${fmtInt(kho.snapshots)} snapshot`, `${fmtInt(kho.packs)} pack`,
      kho.disk ? `ổ còn trống ${fmtBytes(kho.disk.free)}` : null].filter(Boolean).join(" · ");
    return cell("Kho lưu trữ", "drive",
      [h("span", { class: "dot ok" }), h("span", { class: "num", text: fmtBytes(kho.bytes_on_disk) }),
        dd.ratio ? h("span", { class: "chip", title: `Dữ liệu ${fmtBytes(dd.logical)} chỉ chiếm ${fmtBytes(dd.uploaded)}`, text: `khử trùng lặp ${fmtRatio(dd.ratio)}` }) : null],
      meta);
  }
  if (kho) {
    return cell("Kho lưu trữ", "drive", [h("span", { class: "dot err" }), "Không kết nối được kho"],
      h("a", { href: "#/cai-dat" }, `${kho.where || ""} · xem Cài đặt`));
  }
  return cell("Kho lưu trữ", "drive", h("span", { class: "num", text: fmtBytes(ov.stats.total_size) }),
    `${fmtInt(ov.stats.total_backups)} bản` + (disk ? ` · ổ còn trống ${fmtBytes(disk.free)}` : ""));
}

// ======================================================================== TONG QUAN (v2)
export function overviewView(ctx) {
  const quickBtn = h("button", { class: "btn btn-primary", type: "button" });
  const statusRow = h("section", { class: "panel status-row", "aria-label": "Tình trạng" });
  const active = h("div", { class: "panel-body" });
  const machines = h("div", { class: "panel-body tight" });
  const snaps = h("div");
  const events = h("div", { class: "panel-body tight" });
  const jobs = h("div", { class: "panel-body tight" });
  const rpoNote = h("span", { class: "subtle" });
  const el = h("div", { class: "view" },
    pageHead("Tổng quan", null, quickBtn),
    statusRow,
    h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", { text: "Tác vụ hiện tại" })), active),
    h("div", { class: "grid-2" },
      h("div", { class: "stack" },
        h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", { text: "Máy được bảo vệ" }), rpoNote), machines),
        h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", { text: "Snapshot gần đây" }),
          h("a", { href: "#/ban-sao-luu", class: "btn btn-ghost btn-sm" }, "Tất cả bản sao lưu", icon("chev", "ico-sm"))), snaps)),
      h("div", { class: "stack" },
        h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", { text: "Thông báo" }),
          h("a", { href: "#/thong-bao", class: "btn btn-ghost btn-sm" }, "Xem tất cả", icon("chev", "ico-sm"))), events),
        h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", { text: "Tác vụ gần đây" }),
          h("a", { href: "#/tac-vu", class: "btn btn-ghost btn-sm" }, "Xem tất cả", icon("chev", "ico-sm"))), jobs))));

  const preset = store.get(PRESET_KEY, null);
  if (preset) {
    quickBtn.append(icon("play"), "Sao lưu ngay");
    quickBtn.title = "Dùng lại lựa chọn của lần sao lưu trước";
    quickBtn.addEventListener("click", () => startBackup(ctx, preset, quickBtn));
  } else {
    quickBtn.append(icon("upload"), "Tạo bản sao lưu");
    quickBtn.addEventListener("click", () => { location.hash = "#/sao-luu"; });
  }

  let live = null;

  function render(ov) {
    if (!ov) {
      statusRow.replaceChildren(skeletonRows(2));
      active.replaceChildren(h("span", { class: "skel" }));
      return;
    }
    const ag = agentOnline(ov);
    const anyAgent = (ov.agents || [])[0];
    const nx = ov.next_schedule;
    const disk = ov.disk;
    const v2 = ov.v2 || {};
    const rpo = v2.rpo || { status: "do", message: "" };
    const dd = v2.dedup || {};
    rpoNote.textContent = `Mục tiêu RPO ${fmtHours(rpo.target_hours)}`;

    // ---- hang trang thai: tra loi "moi thu co on khong" truoc khi moi bam nut
    statusRow.replaceChildren(
      cell("Dữ liệu được bảo vệ", "shield",
        [rpoPill(rpo.status, { large: true }),
          rpo.last_ok ? h("span", { class: "subtle num", text: `bản gần nhất ${fmtRelative(rpo.last_ok)}` }) : null],
        rpo.message, "rpo-cell"),
      cell("Agent", "server",
        ag ? [h("span", { class: "dot ok" }), h("span", { class: "truncate", text: ag.hostname })]
          : [h("span", { class: "dot err" }), "Chưa kết nối"],
        ag ? `Phản hồi ${fmtRelative(ag.last_seen)}`
          : anyAgent ? `Lần cuối ${fmtRelative(anyAgent.last_seen)} · ${anyAgent.hostname}`
            : h("a", { href: "#/cai-dat" }, "Cách kết nối agent")),
      cell("Lịch kế tiếp", "clock",
        nx ? h("span", { class: "num", text: fmtRelative(nx.next_run) }) : "Chưa đặt lịch",
        nx ? nx.name : h("a", { href: "#/lich" }, "Đặt lịch sao lưu")),
      khoCell(ov, v2.kho, dd, disk));

    // ---- tac vu hien tai (giu tien do muot: cung job + cung trang thai -> chi cap nhat so)
    const j = ov.active_job;
    if (j && live && live.id === j.id && live.status === j.status && live.cancel === j.cancel_requested) {
      live.fill.style.transform = `scaleX(${j.progress / 100})`;
      live.bar.setAttribute("aria-valuenow", String(j.progress));
      if (j.status !== "pending") live.pct.textContent = `${j.progress}%`;
      if (j.status !== "pending") live.msg.textContent = j.message;
      live.foot.textContent = j.started_at
        ? `Bắt đầu ${fmtRelative(j.started_at)} · đã chạy ${fmtDuration(secondsBetween(j.started_at))}`
        : `Tạo ${fmtRelative(j.created_at)}`;
    } else if (j) {
      const pending = j.status === "pending";
      const cancel = h("button", { class: "btn btn-sm btn-danger", type: "button", disabled: j.cancel_requested },
        icon("stop", "ico-sm"), j.cancel_requested ? "Đang dừng…" : pending ? "Huỷ" : "Dừng");
      cancel.addEventListener("click", async () => {
        busy(cancel, true, "Đang dừng…");
        try { await api(`/api/ui/jobs/${j.id}/cancel`, { method: "POST" }); ctx.refresh(); }
        catch (e) { toast(e.message, "err"); busy(cancel, false); }
      });
      const fill = h("i", { style: { transform: `scaleX(${j.progress / 100})` } });
      const bar = h("div", { class: `bar lg${pending ? " indeterminate" : ""}`, role: "progressbar",
        "aria-label": "Tiến độ", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(j.progress) }, fill);
      const pct = h("div", { class: "job-live-pct num", text: pending ? "" : `${j.progress}%` });
      const msg = h("div", { class: "job-live-msg", text: pending ? (ag ? "Đang chờ agent nhận việc…" :
        "Agent chưa kết nối — tác vụ sẽ chạy ngay khi agent online.") : j.message });
      const foot = h("span", { class: "subtle num", text: j.started_at
        ? `Bắt đầu ${fmtRelative(j.started_at)} · đã chạy ${fmtDuration(secondsBetween(j.started_at))}`
        : `Tạo ${fmtRelative(j.created_at)}` });
      live = { id: j.id, status: j.status, cancel: j.cancel_requested, fill, bar, pct, msg, foot };
      active.replaceChildren(h("div", { class: "job-live" },
        h("div", { class: "job-live-top" },
          h("div", {}, h("div", { class: "job-live-title", text: `${jobTitle(j)} #${j.id}` }), statusPill(j.status)), pct),
        bar, msg, h("div", { class: "job-live-foot" }, foot, cancel)));
    } else {
      live = null;
      const lastJob = (ov.jobs || [])[0];
      active.replaceChildren(h("div", { class: "idle" },
        h("div", {}, h("p", { text: "Không có tác vụ nào đang chạy." }),
          lastJob ? h("p", { class: "subtle", text: `Lần trước: ${jobTitle(lastJob)} #${lastJob.id} – ${lastJob.message || ""}` }) : null)));
    }

    // ---- may duoc bao ve: moi may mot dong, RPO rieng
    const ms = v2.machines || [];
    machines.replaceChildren(ms.length
      ? h("ul", { class: "list" }, ms.map((m) => h("li", { class: "list-item" },
        h("span", { class: `dot ${m.online ? "ok" : "err"}`, title: m.online ? "Agent đang kết nối" : "Agent không kết nối" }),
        h("div", { class: "grow" }, h("div", { class: "t", text: m.hostname }),
          h("div", { class: "m", text: [m.last_backup ? `Sao lưu gần nhất ${fmtRelative(m.last_backup)}` : "Chưa có bản sao lưu",
            m.online ? "agent đang kết nối" : m.last_seen ? `agent lần cuối ${fmtRelative(m.last_seen)}` : null].filter(Boolean).join(" · ") })),
        rpoPill(m.rpo.status))))
      : emptyState("server", "Chưa có máy nào", "Chạy agent trên máy cần bảo vệ rồi tạo bản sao lưu đầu tiên.",
        h("a", { class: "btn btn-sm", href: "#/cai-dat" }, "Cách kết nối agent")));

    // ---- snapshot v2 gan day
    const sn = v2.snapshots || [];
    snaps.replaceChildren(sn.length
      ? h("div", { class: "table-wrap" }, h("table", { class: "table" },
        h("thead", {}, h("tr", {}, h("th", {}, "Thời gian"), h("th", {}, "Máy"), h("th", { class: "num" }, "File"),
          h("th", { class: "num" }, "Dữ liệu"), h("th", { class: "num" }, "Gửi lên kho"), h("th", { class: "num" }, "Mẩu mới"),
          h("th", { class: "actions" }, h("span", { class: "sr-only" }, "Khôi phục")))),
        h("tbody", {}, sn.map((s) => h("tr", {},
          h("td", { class: "tnum nowrap" }, fmtDate(s.created_at),
            s.anomaly ? h("span", { class: "pill warn", style: { marginLeft: "6px" } }, icon("alert"), "có dấu bất thường") : null),
          h("td", { class: "nowrap" }, s.host || "–"),
          h("td", { class: "num" }, fmtInt(s.files)),
          h("td", { class: "num" }, fmtBytes(s.bytes)),
          h("td", { class: "num" }, fmtBytes(s.uploaded)),
          h("td", { class: "num" }, s.chunks != null ? `${fmtInt(s.chunks_new)}/${fmtInt(s.chunks)}` : "–"),
          h("td", { class: "actions" }, h("a", { class: "btn btn-sm", href: `#/ban-sao-luu/${s.backup_id}` }, icon("restore", "ico-sm"), "Khôi phục")))))))
      : h("div", { class: "panel-body" }, emptyState("archive", "Chưa có snapshot v2",
        "Đặt ENGINE=v2 trong agent_config.txt rồi tạo bản sao lưu. Từ lần thứ hai chỉ gửi phần thay đổi.",
        h("a", { class: "btn btn-primary", href: "#/sao-luu" }, icon("upload"), "Tạo bản sao lưu"))));

    // ---- thong bao + tac vu gan day
    const evs = ov.events || [];
    events.replaceChildren(evs.length ? h("div", {}, evs.map((e) => eventRow(e, { compact: true })))
      : emptyState("bell", "Chưa có thông báo", "Kết quả sao lưu, cảnh báo bất thường và RPO sẽ hiện ở đây."));

    jobs.replaceChildren((ov.jobs || []).length
      ? h("ul", { class: "list" }, ov.jobs.slice(0, 6).map((x) => h("li", { class: "list-item" },
        statusPill(x.status),
        h("div", { class: "grow" }, h("div", { class: "t truncate", text: `${jobTitle(x)} #${x.id}` }),
          h("div", { class: "m truncate", text: x.message || "—", title: x.message || "" })),
        h("span", { class: "subtle nowrap", text: fmtRelative(x.created_at) }))))
      : emptyState("list", "Chưa có tác vụ nào", "Các lần sao lưu và khôi phục sẽ hiện ở đây."));
  }

  render(ctx.state.overview);
  const off = ctx.on("overview", (e) => render(e.detail));
  return { el, destroy: off };
}

// ======================================================================== THONG BAO (tuan 6)
export function eventsView(ctx) {
  const filters = [["all", "Tất cả"], ["open", "Chưa xác nhận"], ["alert", "Cảnh báo và lỗi"]];
  let filter = store.get("bks-events-filter", "all");
  const seg = h("div", { class: "segmented", role: "radiogroup", "aria-label": "Lọc thông báo" }, filters.map(([v, l]) => h("label", {},
    h("input", { type: "radio", name: "evf", value: v, checked: v === filter,
      onchange: () => { filter = v; store.set("bks-events-filter", v); render(); } }), h("span", { text: l }))));
  const count = h("span", { class: "subtle" });
  const body = h("div", {}, skeletonRows(4));
  const admin = ctx.state.session.user.role === "admin";
  const testBtn = admin ? h("button", { class: "btn", type: "button" }, icon("send"), "Gửi tin thử Telegram") : null;
  const el = h("div", { class: "view" },
    pageHead("Thông báo", "Kết quả sao lưu, cảnh báo bất thường, RPO và khôi phục thử. Bấm Bình thường / Sự cố để xác nhận; bấm nút trên Telegram cũng được ghi nhận ở đây.",
      ...[count, seg, testBtn].filter(Boolean)),
    h("section", { class: "panel" }, body));
  let all = [];

  function render() {
    const rows = all.filter((e) => filter === "all" || (filter === "open" ? isOpen(e) : e.level === "warn" || e.level === "err"));
    count.textContent = all.length ? `${rows.length}/${all.length}` : "";
    body.replaceChildren(rows.length
      ? h("div", { class: "panel-body tight" }, rows.map((e) => eventRow(e, {
        onAck: async (ev, v, btn) => { if (await ackEvent(ctx, ev, v, btn)) load(); } })))
      : emptyState("bell", all.length ? "Không có mục nào khớp" : "Chưa có thông báo",
        all.length ? "Chọn bộ lọc khác." : "Khi sao lưu xong, thất bại, hoặc cổng chặn bất thường kích hoạt, sự kiện hiện ở đây và gửi qua Telegram nếu đã cấu hình.",
        admin && !all.length ? h("a", { class: "btn", href: "#/cai-dat" }, icon("sliders"), "Cấu hình Telegram") : null));
  }

  async function load() {
    try { all = (await api("/api/ui/events?limit=200")).events; render(); }
    catch (e) { body.replaceChildren(emptyState("alert", "Không tải được thông báo", e.message)); }
  }
  if (testBtn) {
    testBtn.addEventListener("click", async () => {
      busy(testBtn, true, "Đang gửi…");
      try { await api("/api/ui/settings/telegram/test", { method: "POST" }); toast("Đã gửi tin thử. Mở Telegram và bấm một nút để thử xác nhận.", "ok", 8000); load(); }
      catch (e) { toast(e.message, "err", 9000); }
      finally { busy(testBtn, false); }
    });
  }
  load();
  let lastOpen = null;
  const off = ctx.on("overview", (e) => {
    if (lastOpen !== null && e.detail.alerts_open !== lastOpen) load();
    lastOpen = e.detail.alerts_open;
  });
  const off2 = ctx.on("job-done", load);
  return { el, destroy() { off(); off2(); } };
}

// ======================================================================== CAI DAT: Kho v2 + Telegram
export function renderSettingsExtras(ctx, el) {
  // ---- Kho v2 (moi nguoi dung): trang thai, ti le khu trung lap, khoi phuc thu / kiem tra toan ven
  const khoBody = h("div", { class: "panel-body" }, h("span", { class: "skel" }));
  const refresh = h("button", { class: "btn btn-ghost btn-sm", type: "button" }, icon("refresh", "ico-sm"), "Làm mới");
  el.append(h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", { text: "Kho v2 (chia mẩu, khử trùng lặp)" }), refresh), khoBody));

  async function runKhoJob(path, body, btn, title, explain) {
    if (!await confirmDialog({ title, message: explain, confirmLabel: "Bắt đầu" })) return;
    busy(btn, true, "Đang gửi…");
    try {
      const r = await api(path, { method: "POST", body });
      toast(`Đã tạo tác vụ #${r.job.id} – theo dõi ở Tổng quan`);
      ctx.refresh();
      location.hash = "#/";
    } catch (e) { toast(e.message, "err"); busy(btn, false); }
  }

  async function loadKho(force) {
    try {
      const { kho, dedup, rpo_hours } = await api(`/api/ui/kho${force ? "?refresh=1" : ""}`);
      const facts = [];
      if (kho) {
        facts.push(["Nơi lưu", h("code", { text: kho.where || "–" })],
          ["Trạng thái", kho.reachable
            ? h("span", { class: "pill ok" }, icon("ok"), kho.initialized ? "Đang chạy · đã khởi tạo" : "Đang chạy · chưa init")
            : h("span", { class: "pill err" }, icon("err"), "Không kết nối được")]);
        if (kho.reachable) {
          facts.push(["Snapshot", fmtInt(kho.snapshots)], ["Pack", fmtInt(kho.packs)],
            ["Dung lượng trên đĩa", fmtBytes(kho.bytes_on_disk)], ["Ổ đĩa còn trống", kho.disk ? fmtBytes(kho.disk.free) : "–"]);
        }
        if (kho.rejected != null) facts.push(["Lệnh xoá / ghi đè bị từ chối", fmtInt(kho.rejected)]);
        if (kho.error) facts.push(["Lỗi", kho.error]);
      } else {
        facts.push(["Nơi lưu", "Chưa cấu hình: đặt BACKUP_KHO_URL (API kho) hoặc BACKUP_KHO_DIR trên server"]);
      }
      facts.push(["Khử trùng lặp", dedup.ratio
        ? `${fmtRatio(dedup.ratio)} · ${fmtInt(dedup.snapshots)} snapshot, dữ liệu ${fmtBytes(dedup.logical)} chỉ gửi ${fmtBytes(dedup.uploaded)} (tiết kiệm ${fmtBytes(dedup.saved)})`
        : "Chưa có snapshot v2"],
      ["Mục tiêu RPO", `${fmtHours(rpo_hours)} (biến BACKUP_RPO_HOURS trên server)`]);
      const verify = h("button", { class: "btn", type: "button" }, icon("eye"), "Khôi phục thử ngay");
      const check = h("button", { class: "btn", type: "button" }, icon("shield"), "Kiểm tra toàn vẹn");
      verify.addEventListener("click", () => runKhoJob("/api/ui/kho/verify", { sample: 20 }, verify, "Khôi phục thử ngay?",
        "Agent lấy snapshot mới nhất, khôi phục 20 file ngẫu nhiên ra thư mục tạm, so SHA-256 với lúc sao lưu rồi xoá. Không đụng dữ liệu thật."));
      check.addEventListener("click", () => runKhoJob("/api/ui/kho/check", { full: false }, check, "Kiểm tra toàn vẹn kho?",
        "Kiểm tra nhanh: SHA-256 và cấu trúc từng pack, đối chiếu mọi mẩu mà các snapshot cần. Kho lớn có thể mất vài phút."));
      khoBody.replaceChildren(
        h("dl", { class: "facts" }, facts.map(([k, v]) => h("div", {}, h("dt", { text: k }), h("dd", {}, v)))),
        h("div", { class: "btn-row" }, verify, check),
        h("p", { class: "subtle", style: { marginTop: "8px" }, text: "Cần agent đang chạy với ENGINE=v2. Kết quả hiện ở Tổng quan và Thông báo (và Telegram nếu đã cấu hình)." }));
    } catch (e) { khoBody.replaceChildren(h("p", { class: "form-error", text: e.message })); }
  }
  refresh.addEventListener("click", () => loadKho(true));
  loadKho(false);

  // ---- Telegram (chi quan tri)
  if (ctx.state.session.user.role !== "admin") return;
  const token = h("input", { class: "input", type: "password", autocomplete: "off", "aria-label": "Token bot" });
  const chat = h("input", { class: "input", placeholder: "vd 123456789 (nhắn /id cho bot để lấy)", inputmode: "numeric", "aria-label": "Chat ID" });
  const enabled = h("input", { type: "checkbox", class: "switch", role: "switch", checked: true });
  const notifyOk = h("input", { type: "checkbox", class: "switch", role: "switch", checked: true });
  const state = h("div");
  const save = h("button", { class: "btn btn-primary", type: "submit" }, "Lưu");
  const test = h("button", { class: "btn", type: "button", disabled: true }, icon("send"), "Gửi tin thử");
  const err = h("div", { class: "form-error", hidden: true });
  let hasToken = false;

  function apply(st) {
    hasToken = st.has_token;
    chat.value = st.chat_id || "";
    enabled.checked = st.enabled;
    notifyOk.checked = st.notify_ok;
    token.placeholder = st.has_token ? `Đang dùng ${st.token_masked}${st.from_env ? " (từ biến môi trường)" : ""} – nhập để thay`
      : "123456789:ABCdef… (lấy từ @BotFather)";
    state.replaceChildren(st.configured ? h("span", { class: "pill ok" }, icon("ok"), "Đã cấu hình")
      : h("span", { class: "pill warn" }, icon("alert"), "Chưa cấu hình"));
    test.disabled = !st.configured;
  }

  const form = h("form", { class: "panel", onsubmit: async (e) => {
    e.preventDefault();
    err.hidden = true;
    busy(save, true, "Đang lưu…");
    const body = { chat_id: chat.value.trim(), enabled: enabled.checked, notify_ok: notifyOk.checked };
    if (token.value.trim() || !hasToken) body.token = token.value.trim();
    try { apply(await api("/api/ui/settings/telegram", { method: "POST", body })); toast("Đã lưu cài đặt Telegram"); token.value = ""; }
    catch (ex) { err.replaceChildren(icon("alert", "ico-sm"), ex.message); err.hidden = false; }
    finally { busy(save, false); }
  } },
    h("div", { class: "panel-head" }, h("h2", { text: "Thông báo Telegram" }), state),
    h("div", { class: "panel-body" },
      h("p", { class: "muted", style: { marginBottom: "16px" },
        text: "Sao lưu xong hay thất bại, cổng chặn bất thường kích hoạt, RPO đổi màu: bot gửi tin kèm hai nút Bình thường / Sự cố để xác nhận ngay trên điện thoại. Tạo bot bằng @BotFather để lấy token; nhắn /id cho bot để lấy chat ID." }),
      h("div", { class: "form-grid" }, field("Token bot", token), field("Chat ID", chat)),
      h("div", { style: { marginTop: "16px", display: "flex", gap: "24px", flexWrap: "wrap" } },
        h("label", { class: "check-inline" }, enabled, "Bật thông báo"),
        h("label", { class: "check-inline" }, notifyOk, "Báo cả khi thành công")),
      err,
      h("div", { class: "btn-row" }, save, test)));
  el.append(form);
  test.addEventListener("click", async () => {
    busy(test, true, "Đang gửi…");
    try { await api("/api/ui/settings/telegram/test", { method: "POST" }); toast("Đã gửi. Mở Telegram, bấm một nút để thử xác nhận.", "ok", 8000); }
    catch (e) { toast(e.message, "err", 9000); }
    finally { busy(test, false); }
  });
  api("/api/ui/settings/telegram").then(apply).catch((e) => { err.replaceChildren(icon("alert", "ico-sm"), e.message); err.hidden = false; });
}
