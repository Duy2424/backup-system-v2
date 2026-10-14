// Cac man hinh. Moi view tra ve { el, destroy }.
import {
  ALL_COMPONENTS, COMPONENTS, JOB_TYPE, api, busy, compLabel, confirmDialog, copyText, dialog, emptyState,
  field, fmtBytes, fmtDate, fmtDuration, fmtInt, fmtRelative, h, icon, jobTitle, secondsBetween, skeletonRows,
  statusPill, store, toast,
} from "./lib.js";
import { pickFolder } from "./picker.js";

const PRESET_KEY = "bks-last-backup";
const NET = ALL_COMPONENTS.filter((c) => COMPONENTS[c].group !== "data");

function pageHead(title, lead, ...actions) {
  return h("header", { class: "page-head" },
    h("div", {}, h("h1", { text: title }), lead ? h("p", { class: "lead", text: lead }) : null),
    actions.length ? h("div", { class: "page-actions" }, actions) : null);
}

function compSummary(comps) {
  if (!comps || !comps.length) return h("span", { class: "subtle" }, "–");
  if (ALL_COMPONENTS.every((c) => comps.includes(c))) return h("span", { class: "chip" }, "Toàn bộ");
  const shown = comps.slice(0, 3).map((c) => h("span", { class: "chip", text: compLabel(c) }));
  if (comps.length > 3) shown.push(h("span", { class: "chip", text: `+${comps.length - 3}` }));
  return h("span", { class: "chips" }, shown);
}

function agentOnline(ov) {
  const a = (ov && ov.agents) || [];
  return a.find((x) => x.online) || null;
}

async function startBackup(ctx, preset, btn) {
  if (btn && btn.disabled) return null;     // dang gui -> bo qua lan bam them
  if (btn) busy(btn, true, "Đang gửi…");
  try {
    const r = await api("/api/ui/backups", { method: "POST", body: preset });
    store.set(PRESET_KEY, preset);
    toast(`Đã tạo tác vụ sao lưu #${r.job.id}`);
    ctx.refresh();
    return r.job;
  } catch (e) {
    toast(e.message, "err");
    return null;
  } finally {
    if (btn) busy(btn, false);
  }
}

function folderEditor(paths, onChange, defaultPaths) {
  const wrap = h("div");
  const render = () => {
    const items = paths.map((p, i) => h("li", {},
      icon("folder", "ico-sm"), h("code", { text: p, title: p }),
      h("button", { class: "btn btn-ghost btn-sm btn-icon", type: "button", "aria-label": `Bỏ ${p}`,
        onclick: () => { paths.splice(i, 1); render(); onChange(); } }, icon("x", "ico-sm"))));
    const add = h("button", { class: "btn btn-sm", type: "button", onclick: async () => {
      const p = await pickFolder({ initial: paths[paths.length - 1] || "" });
      if (p && !paths.includes(p)) { paths.push(p); render(); onChange(); }
    } }, icon("plus", "ico-sm"), "Thêm thư mục…");
    wrap.replaceChildren(
      paths.length ? h("ul", { class: "path-list" }, items)
        : h("div", { class: "info-note", style: { marginTop: "12px" } }, icon("info"),
          h("div", {}, "Chưa chọn thư mục: agent sẽ dùng thư mục mặc định ",
            h("code", { text: (defaultPaths || []).join(", ") || "trong cấu hình agent" }), ".")),
      h("div", { style: { marginTop: "12px" } }, add));
  };
  render();
  return wrap;
}

function componentChecks(selected, onChange, { compact = false } = {}) {
  const make = (c) => {
    const cb = h("input", { type: "checkbox", value: c, checked: selected.has(c) });
    cb.addEventListener("change", () => { cb.checked ? selected.add(c) : selected.delete(c); onChange(); });
    return h("label", { class: "check-row" }, cb,
      h("span", {}, h("span", { class: "t", text: COMPONENTS[c].label }),
        compact ? null : h("span", { class: "d", style: { display: "block" }, text: COMPONENTS[c].desc })));
  };
  return { make, sync: (root) => root.querySelectorAll("input[type=checkbox][value]").forEach((cb) => { cb.checked = selected.has(cb.value); }) };
}

// ======================================================================== TONG QUAN
export function overviewView(ctx) {
  const quickBtn = h("button", { class: "btn btn-primary", type: "button" });
  const statusRow = h("section", { class: "panel status-row", "aria-label": "Tình trạng" });
  const active = h("div", { class: "panel-body" });
  const jobs = h("div", { class: "panel-body tight" });
  const backups = h("div", { class: "panel-body tight" });
  const el = h("div", { class: "view" },
    pageHead("Tổng quan", null, quickBtn),
    statusRow,
    h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", { text: "Tác vụ hiện tại" })), active),
    h("div", { class: "grid-2" },
      h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", { text: "Tác vụ gần đây" }),
        h("a", { href: "#/tac-vu", class: "btn btn-ghost btn-sm" }, "Xem tất cả", icon("chev", "ico-sm"))), jobs),
      h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", { text: "Bản sao lưu gần đây" }),
        h("a", { href: "#/ban-sao-luu", class: "btn btn-ghost btn-sm" }, "Xem tất cả", icon("chev", "ico-sm"))), backups)));

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

  function cell(label, iconName, value, meta) {
    return h("div", { class: "status-cell" },
      h("div", { class: "status-label" }, icon(iconName, "ico-sm"), label),
      h("div", { class: "status-value" }, value), meta ? h("div", { class: "status-meta" }, meta) : null);
  }

  function render(ov) {
    if (!ov) {
      statusRow.replaceChildren(skeletonRows(2));
      active.replaceChildren(h("span", { class: "skel" }));
      return;
    }
    const ag = agentOnline(ov);
    const anyAgent = (ov.agents || [])[0];
    const last = ov.stats.last_backup;
    const nx = ov.next_schedule;
    const disk = ov.disk;
    statusRow.replaceChildren(
      cell("Agent", "server",
        ag ? [h("span", { class: "dot ok" }), h("span", { class: "truncate", text: ag.hostname })]
          : [h("span", { class: "dot err" }), "Chưa kết nối"],
        ag ? `Phản hồi ${fmtRelative(ag.last_seen)}`
          : anyAgent ? `Lần cuối ${fmtRelative(anyAgent.last_seen)} · ${anyAgent.hostname}`
            : h("a", { href: "#/cai-dat" }, "Cách kết nối agent")),
      cell("Lần sao lưu gần nhất", "archive",
        last ? [statusPill(last.status), h("span", { class: "num", text: fmtRelative(last.created_at) })] : "Chưa có",
        last ? `${fmtDate(last.created_at)} · ${fmtBytes(last.size)}` : "Tạo bản đầu tiên ở mục Sao lưu"),
      cell("Lịch kế tiếp", "clock",
        nx ? h("span", { class: "num", text: fmtRelative(nx.next_run) }) : "Chưa đặt lịch",
        nx ? nx.name : h("a", { href: "#/lich" }, "Đặt lịch sao lưu")),
      cell("Kho lưu trữ", "drive",
        h("span", { class: "num", text: fmtBytes(ov.stats.total_size) }),
        `${fmtInt(ov.stats.total_backups)} bản` + (disk ? ` · ổ còn trống ${fmtBytes(disk.free)}` : "")));

    // tac vu hien tai: cung job + cung trang thai -> chi cap nhat so lieu (thanh tien do chay muot)
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

    jobs.replaceChildren((ov.jobs || []).length
      ? h("ul", { class: "list" }, ov.jobs.slice(0, 6).map((x) => h("li", { class: "list-item" },
        statusPill(x.status),
        h("div", { class: "grow" }, h("div", { class: "t truncate", text: `${jobTitle(x)} #${x.id}` }),
          h("div", { class: "m truncate", text: x.message || "—", title: x.message || "" })),
        h("span", { class: "subtle nowrap", text: fmtRelative(x.created_at) }))))
      : emptyState("list", "Chưa có tác vụ nào", "Các lần sao lưu và khôi phục sẽ hiện ở đây."));

    backups.replaceChildren((ov.backups || []).length
      ? h("ul", { class: "list" }, ov.backups.map((b) => h("li", { class: "list-item" },
        icon("archive"),
        h("div", { class: "grow" }, h("div", { class: "t tnum nowrap", text: fmtDate(b.created_at) }),
          h("div", { class: "m truncate", title: b.components.map(compLabel).join(", ") },
            [fmtBytes(b.size), b.files != null ? `${fmtInt(b.files)} file` : null,
              b.components.length === ALL_COMPONENTS.length ? "Toàn bộ" : b.components.map(compLabel).join(", ")]
              .filter(Boolean).join(" · "))),
        h("a", { class: "btn btn-sm", href: `#/ban-sao-luu/${b.id}` }, icon("restore", "ico-sm"), "Khôi phục"))))
      : emptyState("archive", "Chưa có bản sao lưu", "Bản đầu tiên chứa toàn bộ dữ liệu đã chọn.",
        h("a", { class: "btn btn-primary", href: "#/sao-luu" }, icon("upload"), "Tạo bản sao lưu")));
  }

  render(ctx.state.overview);
  const off = ctx.on("overview", (e) => render(e.detail));
  return { el, destroy: off };
}

// ======================================================================== SAO LUU (tao moi)
export function backupView(ctx) {
  const saved = store.get(PRESET_KEY, null);
  const selected = new Set(saved ? saved.components : ALL_COMPONENTS);
  const paths = saved && saved.paths ? [...saved.paths] : [];
  const checks = componentChecks(selected, () => update());

  const presets = [["all", "Toàn bộ"], ["data", "Chỉ dữ liệu"], ["net", "Chỉ cấu hình hệ thống"], ["custom", "Tuỳ chọn"]];
  const seg = h("div", { class: "segmented", role: "radiogroup", "aria-label": "Mẫu chọn nhanh" },
    presets.map(([v, label]) => h("label", {}, h("input", { type: "radio", name: "preset", value: v,
      onchange: () => applyPreset(v) }), h("span", { text: label }))));

  const filesBox = h("div");
  const filesCheck = checks.make("files");
  const netGrid = h("div", { class: "check-grid" }, NET.map((c) => checks.make(c)));
  const fullNote = h("div", { class: "info-note", style: { marginTop: "16px" } }, icon("info"),
    h("div", { text: "Khi chọn toàn bộ, agent sao lưu thêm CSDL SQL Server (nếu có) và các khoá Windows Registry quan trọng." }));
  const summary = h("div", { class: "muted" });
  const submit = h("button", { class: "btn btn-primary", type: "submit" }, icon("upload"), "Bắt đầu sao lưu");

  const form = h("form", { class: "view", onsubmit: async (e) => {
    e.preventDefault();
    const comps = ALL_COMPONENTS.filter((c) => selected.has(c));
    const job = await startBackup(ctx, { components: comps, paths: selected.has("files") ? [...paths] : [] }, submit);
    if (job) location.hash = "#/";
  } },
    pageHead("Sao lưu", "Chọn những gì cần sao lưu. Dữ liệu được nén và mã hoá trên máy agent trước khi gửi về kho."),
    h("section", { class: "panel" },
      h("div", { class: "panel-head" }, h("h2", { text: "Thành phần" }), seg),
      h("div", { class: "panel-body" },
        h("fieldset", {}, h("legend", {}, icon("folder", "ico-sm"), "Dữ liệu"), filesCheck, filesBox),
        h("fieldset", {}, h("legend", {}, icon("network", "ico-sm"), "Cấu hình mạng và hệ thống"), netGrid),
        fullNote)),
    h("div", { class: "sticky-foot" }, summary, submit));

  function applyPreset(v) {
    if (v === "custom") return;
    selected.clear();
    (v === "all" ? ALL_COMPONENTS : v === "data" ? ["files"] : NET).forEach((c) => selected.add(c));
    checks.sync(form);
    update();
  }

  function update() {
    const n = selected.size;
    const full = n === ALL_COMPONENTS.length;
    const which = full ? "all" : n === 1 && selected.has("files") ? "data"
      : !selected.has("files") && NET.every((c) => selected.has(c)) ? "net" : "custom";
    form.querySelectorAll("input[name=preset]").forEach((r) => { r.checked = r.value === which; });
    filesBox.replaceChildren(selected.has("files") ? folderEditor(paths, () => update(), ctx.state.session.default_paths) : "");
    fullNote.hidden = !full;
    submit.disabled = n === 0;
    const parts = [`${n}/${ALL_COMPONENTS.length} thành phần`];
    if (selected.has("files")) parts.push(paths.length ? `${paths.length} thư mục` : "thư mục mặc định");
    if (!agentOnline(ctx.state.overview)) parts.push("agent chưa kết nối (tác vụ sẽ chờ)");
    summary.textContent = n ? parts.join(" · ") : "Chọn ít nhất một thành phần";
  }
  update();
  return { el: form, destroy() {} };
}

// ======================================================================== BAN SAO LUU + KHOI PHUC
export function backupsView(ctx, param) {
  const search = h("input", { class: "input", type: "search", placeholder: "Tìm theo ngày, tên file, thành phần", "aria-label": "Tìm" });
  const count = h("span", { class: "subtle" });
  const body = h("div", {}, skeletonRows(4));
  const el = h("div", { class: "view" },
    pageHead("Bản sao lưu", "Chọn một bản để xem chi tiết và khôi phục. Nên chạy thử trước để xem những gì sẽ thay đổi.",
      count, h("div", { class: "search" }, icon("search", "ico-sm"), search)),
    h("section", { class: "panel" }, body));
  let all = [];
  let openId = param ? Number(param) : null;

  function restoreBox(b) {
    const hasFiles = b.components.includes("files");
    const hasSys = b.components.some((c) => c !== "files");
    let target = "";
    const targetLabel = h("code", { class: "truncate" });
    const pickBtn = h("button", { class: "btn btn-sm", type: "button" }, icon("folder", "ico-sm"), "Chọn…");
    const otherRow = h("div", { class: "input-row", style: { alignItems: "center", marginTop: "8px" } }, targetLabel, pickBtn);
    const where = h("div", { class: "segmented", role: "radiogroup", "aria-label": "Khôi phục về" },
      [["orig", "Vị trí ban đầu"], ["other", "Thư mục khác"]].map(([v, l]) => h("label", {},
        h("input", { type: "radio", name: `where-${b.id}`, value: v, checked: v === "orig", onchange: () => sync() }),
        h("span", { text: l }))));
    const sysCb = h("input", { type: "checkbox", checked: hasSys });
    const delCb = h("input", { type: "checkbox" });
    const sysOpt = h("label", { class: "check-row option" }, sysCb, h("span", {},
      h("span", { class: "t", text: "Áp dụng lại cấu hình mạng và hệ thống" }),
      h("span", { class: "d", style: { display: "block" }, text: "IP, tường lửa, route… đặt lại như lúc sao lưu. Kết nối có thể bị gián đoạn vài giây." })));
    const delOpt = h("label", { class: "check-row option" }, delCb, h("span", {},
      h("span", { class: "t", text: "Xoá file không có trong bản sao lưu" }),
      h("span", { class: "d", style: { display: "block" }, text: "File tạo sau thời điểm sao lưu trong các thư mục này sẽ bị xoá. Mặc định tắt." })));
    const dryBtn = h("button", { class: "btn", type: "button" }, icon("eye"), "Chạy thử");
    const goBtn = h("button", { class: "btn btn-primary", type: "button" }, icon("restore"), "Khôi phục…");

    pickBtn.addEventListener("click", async () => {
      const p = await pickFolder({ title: "Khôi phục vào thư mục" });
      if (p) { target = p; sync(); }
    });

    function mode() { return where.querySelector("input:checked").value; }
    function sync() {
      const other = mode() === "other";
      otherRow.hidden = !other;
      targetLabel.textContent = target || "(chưa chọn thư mục)";
      sysOpt.hidden = !hasSys || other;
      delOpt.hidden = !hasFiles || other;
      goBtn.disabled = other && !target;
      dryBtn.disabled = other;
    }

    let inFlight = false;
    async function run(dry) {
      if (inFlight) return;             // chong bam 2 lan / bam lien tiep
      inFlight = true;
      try { await runOnce(dry); } finally { inFlight = false; }
    }

    async function runOnce(dry) {
      const other = mode() === "other";
      const payload = { dry_run: dry, target_dir: other ? target : null,
        restore_system: !other && hasSys && sysCb.checked, delete_extra: !other && hasFiles && delCb.checked };
      if (!dry) {
        const items = [];
        if (hasFiles) items.push(other ? `Chép toàn bộ ${fmtInt(b.files)} file vào ${target}` :
          "Ghi lại các file bị thiếu hoặc khác so với bản sao lưu");
        if (payload.delete_extra) items.push("XOÁ các file không có trong bản sao lưu");
        if (payload.restore_system) items.push("Đặt lại cấu hình mạng/hệ thống như lúc sao lưu");
        const ok = await confirmDialog({ title: "Khôi phục từ bản sao lưu?",
          message: `Bản ngày ${fmtDate(b.created_at)}. Những việc sẽ làm:`, items,
          confirmLabel: "Khôi phục", danger: payload.delete_extra || payload.restore_system });
        if (!ok) return;
      }
      const btn = dry ? dryBtn : goBtn;
      busy(btn, true, "Đang gửi…");
      try {
        const r = await api(`/api/ui/backups/${b.id}/restore`, { method: "POST", body: payload });
        toast(dry ? `Đã tạo tác vụ chạy thử #${r.job.id} – kết quả hiện ở Tổng quan` : `Đã tạo tác vụ khôi phục #${r.job.id}`);
        ctx.refresh();
        location.hash = "#/";
      } catch (e) { toast(e.message, "err"); } finally { busy(btn, false); }
    }
    dryBtn.addEventListener("click", () => run(true));
    goBtn.addEventListener("click", () => run(false));

    const box = h("div", { class: "restore-box" }, h("h3", { text: "Khôi phục từ bản này" }),
      h("div", { class: "label", style: { marginBottom: "8px" } }, "Khôi phục về"), where, otherRow,
      h("div", { style: { marginTop: "16px" } }, sysOpt, delOpt),
      h("div", { class: "btn-row" }, dryBtn, goBtn));
    queueMicrotask(sync);
    return box;
  }

  function detailRow(b) {
    const st = b.stats || {};
    const facts = [
      ["Tên file", h("code", { text: b.filename })],
      ["Kiểu", b.backup_type === "full" ? "Toàn bộ" : "Chọn lọc"],
      ["Số file", fmtInt(b.files)],
      ["Dữ liệu gốc", fmtBytes(b.source_bytes)],
      ["Sau nén + mã hoá", fmtBytes(b.size)],
      ["Thời gian chạy", st.seconds != null ? fmtDuration(st.seconds) : "–"],
    ];
    if (st.skipped) facts.push(["File bỏ qua", `${fmtInt(st.skipped)} (không đọc được)`]);
    return h("tr", { class: "detail" }, h("td", { colspan: "6" }, h("div", { class: "detail-grid" },
      h("div", {},
        h("dl", { class: "facts" }, facts.map(([k, v]) => h("div", {}, h("dt", { text: k }), h("dd", {}, v)))),
        h("div", { style: { marginTop: "20px" } }, h("div", { class: "label", style: { marginBottom: "6px" } }, "Thành phần"),
          h("div", { class: "chips" }, b.components.map((c) => h("span", { class: "chip", text: compLabel(c) })))),
        b.paths && b.paths.length ? h("div", { style: { marginTop: "16px" } },
          h("div", { class: "label", style: { marginBottom: "6px" } }, "Thư mục nguồn"),
          h("ul", { class: "path-list" }, b.paths.map((p) => h("li", {}, icon("folder", "ico-sm"), h("code", { text: p, title: p }))))) : null),
      restoreBox(b))));
  }

  function render() {
    const q = search.value.trim().toLowerCase();
    const rows = all.filter((b) => !q || [fmtDate(b.created_at), b.filename, ...b.components.map(compLabel)]
      .join(" ").toLowerCase().includes(q));
    count.textContent = all.length ? `${rows.length}/${all.length} bản` : "";
    if (!all.length) {
      body.replaceChildren(emptyState("archive", "Chưa có bản sao lưu nào",
        "Sau lần sao lưu đầu tiên, các bản sẽ hiện ở đây để khôi phục khi cần.",
        h("a", { class: "btn btn-primary", href: "#/sao-luu" }, icon("upload"), "Tạo bản sao lưu")));
      return;
    }
    if (!rows.length) {
      body.replaceChildren(emptyState("search", "Không có bản nào khớp", "Thử từ khoá khác, vd một ngày (14/10) hoặc “Tường lửa”."));
      return;
    }
    const tbody = h("tbody");
    for (const b of rows) {
      const open = b.id === openId;
      const tr = h("tr", { class: `row-click${open ? " open" : ""}`, tabindex: "0", "aria-expanded": String(open) },
        h("td", { class: "tnum nowrap" }, fmtDate(b.created_at)),
        h("td", {}, compSummary(b.components)),
        h("td", { class: "num" }, fmtInt(b.files)),
        h("td", { class: "num" }, fmtBytes(b.size)),
        h("td", {}, statusPill(b.status)),
        h("td", { class: "actions" }, h("span", { class: "btn btn-ghost btn-sm" }, open ? "Thu gọn" : "Chi tiết",
          icon(open ? "up" : "chev", "ico-sm"))));
      const toggle = () => { openId = open ? null : b.id; history.replaceState(null, "", openId ? `#/ban-sao-luu/${openId}` : "#/ban-sao-luu"); render(); };
      tr.addEventListener("click", toggle);
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
      tbody.append(tr);
      if (open && b.status === "completed") tbody.append(detailRow(b));
    }
    body.replaceChildren(h("div", { class: "table-wrap" }, h("table", { class: "table" },
      h("thead", {}, h("tr", {}, h("th", {}, "Thời gian"), h("th", {}, "Thành phần"), h("th", { class: "num" }, "Số file"),
        h("th", { class: "num" }, "Dung lượng"), h("th", {}, "Trạng thái"), h("th", { class: "actions" }, h("span", { class: "sr-only" }, "Mở")))),
      tbody)));
    if (openId) {
      const r = body.querySelector("tr.open");
      if (r && param) { r.scrollIntoView({ block: "center" }); param = null; }
    }
  }

  async function load() {
    try {
      all = (await api("/api/ui/backups")).backups;
      render();
    } catch (e) {
      body.replaceChildren(emptyState("alert", "Không tải được danh sách", e.message));
    }
  }
  search.addEventListener("input", render);
  load();
  const off = ctx.on("job-done", (e) => { if (e.detail.type === "backup") load(); });
  return { el, destroy: off };
}

// ======================================================================== TAC VU
export function jobsView(ctx) {
  const body = h("div", {}, skeletonRows(5));
  const el = h("div", { class: "view" }, pageHead("Tác vụ", "Lịch sử sao lưu, khôi phục và kết quả của từng lần chạy."),
    h("section", { class: "panel" }, body));
  let timer = null;

  function render(jobs) {
    if (!jobs.length) {
      body.replaceChildren(emptyState("list", "Chưa có tác vụ nào", "Tác vụ được tạo khi bạn bấm sao lưu/khôi phục hoặc khi đến giờ của lịch."));
      return;
    }
    body.replaceChildren(h("div", { class: "table-wrap" }, h("table", { class: "table" },
      h("thead", {}, h("tr", {}, h("th", {}, "#"), h("th", {}, "Tác vụ"), h("th", {}, "Trạng thái"), h("th", {}, "Bắt đầu"),
        h("th", {}, "Thời lượng"), h("th", {}, "Kết quả"), h("th", { class: "actions" }, h("span", { class: "sr-only" }, "Thao tác")))),
      h("tbody", {}, jobs.map((j) => {
        const activeJob = j.status === "pending" || j.status === "running";
        let action = null;
        if (activeJob) {
          action = h("button", { class: "btn btn-sm btn-danger", type: "button", disabled: j.cancel_requested,
            onclick: async (e) => {
              busy(e.currentTarget, true, "Đang dừng…");
              try { await api(`/api/ui/jobs/${j.id}/cancel`, { method: "POST" }); load(); ctx.refresh(); }
              catch (err) { toast(err.message, "err"); }
            } }, icon("stop", "ico-sm"), j.status === "pending" ? "Huỷ" : "Dừng");
        }
        return h("tr", {},
          h("td", { class: "num subtle" }, String(j.id)),
          h("td", { class: "nowrap" }, jobTitle(j)),
          h("td", {}, statusPill(j.status)),
          h("td", { class: "tnum nowrap" }, fmtDate(j.started_at || j.created_at)),
          h("td", { class: "tnum nowrap" }, j.started_at ? fmtDuration(secondsBetween(j.started_at, j.completed_at)) : "–"),
          h("td", {}, activeJob && j.status === "running"
            ? h("div", {}, h("div", { class: "bar" }, h("i", { style: { transform: `scaleX(${j.progress / 100})` } })),
              h("div", { class: "subtle truncate", style: { marginTop: "4px", maxWidth: "48ch" }, text: j.message }))
            : h("span", { class: "muted", text: j.message || "—" })),
          h("td", { class: "actions" }, action));
      })))));
  }

  async function load() {
    clearTimeout(timer);
    try {
      const jobs = (await api("/api/ui/jobs?limit=100")).jobs;
      render(jobs);
      if (jobs.some((j) => j.status === "pending" || j.status === "running")) timer = setTimeout(load, 2000);
    } catch (e) {
      body.replaceChildren(emptyState("alert", "Không tải được danh sách", e.message));
    }
  }
  load();
  const off = ctx.on("job-done", load);
  const off2 = ctx.on("job-started", load);
  return { el, destroy() { clearTimeout(timer); off(); off2(); } };
}

// ======================================================================== LICH
const DOW = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"];

function freqText(s) {
  if (s.schedule_type === "hourly") return `Mỗi ${s.interval_hours} giờ`;
  if (s.schedule_type === "weekly") return `${DOW[s.day_of_week] || "?"} hằng tuần, ${s.time_of_day}`;
  return `Hằng ngày lúc ${s.time_of_day}`;
}

export function schedulesView(ctx) {
  const addBtn = h("button", { class: "btn btn-primary", type: "button" }, icon("plus"), "Thêm lịch");
  const formWrap = h("div");
  const body = h("div", {}, skeletonRows(3));
  const el = h("div", { class: "view" },
    pageHead("Lịch sao lưu", "Server tự tạo tác vụ khi đến giờ; agent thực hiện ngay nếu đang kết nối.", addBtn),
    formWrap, h("section", { class: "panel" }, body));

  addBtn.addEventListener("click", () => { formWrap.hidden = false; addBtn.hidden = true; formWrap.replaceChildren(scheduleForm()); formWrap.querySelector("input").focus(); });

  function scheduleForm() {
    const selected = new Set(ALL_COMPONENTS);
    const paths = [];
    const checks = componentChecks(selected, () => sync(), { compact: true });
    const name = h("input", { class: "input", required: true, maxlength: "80", placeholder: "vd Sao lưu hằng đêm" });
    const type = h("div", { class: "segmented", role: "radiogroup", "aria-label": "Tần suất" },
      [["daily", "Hằng ngày"], ["weekly", "Hằng tuần"], ["hourly", "Mỗi N giờ"]].map(([v, l]) => h("label", {},
        h("input", { type: "radio", name: "stype", value: v, checked: v === "daily", onchange: () => sync() }), h("span", { text: l }))));
    const time = h("input", { class: "input", type: "time", value: "02:00", required: true });
    const dow = h("select", { class: "input" }, DOW.map((d, i) => h("option", { value: String(i), text: d })));
    const hours = h("input", { class: "input", type: "number", min: "1", max: "720", value: "6" });
    const fTime = field("Giờ chạy", time);
    const fDow = field("Thứ", dow);
    const fHours = field("Cách nhau (giờ)", hours);
    const filesBox = h("div");
    const submit = h("button", { class: "btn btn-primary", type: "submit" }, icon("check"), "Lưu lịch");
    const cancel = h("button", { class: "btn", type: "button", onclick: () => { formWrap.hidden = true; addBtn.hidden = false; } }, "Huỷ");
    const err = h("div", { class: "form-error", hidden: true });

    function stype() { return type.querySelector("input:checked").value; }
    function sync() {
      fTime.hidden = stype() === "hourly";
      fDow.hidden = stype() !== "weekly";
      fHours.hidden = stype() !== "hourly";
      filesBox.replaceChildren(selected.has("files") ? folderEditor(paths, () => {}, ctx.state.session.default_paths) : "");
      submit.disabled = selected.size === 0;
    }

    const form = h("form", { class: "panel", style: { marginBottom: "20px" }, onsubmit: async (e) => {
      e.preventDefault();
      err.hidden = true;
      busy(submit, true, "Đang lưu…");
      try {
        await api("/api/ui/schedules", { method: "POST", body: {
          name: name.value.trim(), schedule_type: stype(), time_of_day: time.value, day_of_week: Number(dow.value),
          interval_hours: Number(hours.value), components: ALL_COMPONENTS.filter((c) => selected.has(c)),
          paths: selected.has("files") ? paths : [] } });
        toast("Đã thêm lịch");
        formWrap.hidden = true; addBtn.hidden = false;
        load();
      } catch (ex) {
        err.replaceChildren(icon("alert", "ico-sm"), ex.message); err.hidden = false;
      } finally { busy(submit, false); }
    } },
      h("div", { class: "panel-head" }, h("h2", { text: "Lịch mới" })),
      h("div", { class: "panel-body" },
        h("div", { class: "form-grid" }, field("Tên lịch", name),
          h("div", { class: "field" }, h("span", { class: "label" }, "Tần suất"), type)),
        h("div", { class: "form-grid", style: { marginTop: "16px" } }, fTime, fDow, fHours),
        h("fieldset", { style: { marginTop: "20px" } }, h("legend", {}, "Thành phần"),
          h("div", { class: "check-grid" }, ALL_COMPONENTS.map((c) => checks.make(c))), filesBox),
        err,
        h("div", { class: "btn-row" }, submit, cancel)));
    sync();
    return form;
  }

  function render(list) {
    if (!list.length) {
      body.replaceChildren(emptyState("clock", "Chưa có lịch nào",
        "Đặt lịch để sao lưu tự động, ví dụ toàn bộ dữ liệu lúc 02:00 mỗi đêm khi không ai dùng máy."));
      return;
    }
    body.replaceChildren(h("div", { class: "table-wrap" }, h("table", { class: "table" },
      h("thead", {}, h("tr", {}, h("th", {}, "Bật"), h("th", {}, "Tên"), h("th", {}, "Tần suất"), h("th", {}, "Thành phần"),
        h("th", {}, "Lần tới"), h("th", {}, "Lần trước"), h("th", { class: "actions" }, h("span", { class: "sr-only" }, "Thao tác")))),
      h("tbody", {}, list.map((s) => {
        const sw = h("input", { type: "checkbox", class: "switch", role: "switch", checked: s.enabled, "aria-label": `Bật lịch ${s.name}` });
        sw.addEventListener("change", async () => {
          try { await api(`/api/ui/schedules/${s.id}/toggle`, { method: "POST" }); toast(sw.checked ? "Đã bật lịch" : "Đã tắt lịch"); load(); }
          catch (e) { sw.checked = !sw.checked; toast(e.message, "err"); }
        });
        const run = h("button", { class: "btn btn-sm", type: "button", title: "Chạy ngay một lần" }, icon("play", "ico-sm"), "Chạy ngay");
        run.addEventListener("click", async () => {
          busy(run, true, "Đang gửi…");
          try { const r = await api(`/api/ui/schedules/${s.id}/run`, { method: "POST" }); toast(`Đã tạo tác vụ #${r.job.id}`); ctx.refresh(); }
          catch (e) { toast(e.message, "err"); } finally { busy(run, false); }
        });
        const del = h("button", { class: "btn btn-sm btn-ghost btn-icon", type: "button", "aria-label": `Xoá lịch ${s.name}` }, icon("trash", "ico-sm"));
        del.addEventListener("click", async () => {
          if (!await confirmDialog({ title: "Xoá lịch?", message: `Lịch “${s.name}” sẽ không chạy nữa. Các bản sao lưu đã tạo vẫn giữ nguyên.`, confirmLabel: "Xoá lịch", danger: true })) return;
          try { await api(`/api/ui/schedules/${s.id}`, { method: "DELETE" }); toast("Đã xoá lịch"); load(); }
          catch (e) { toast(e.message, "err"); }
        });
        return h("tr", {},
          h("td", {}, sw), h("td", { class: "nowrap" }, h("strong", { text: s.name })), h("td", { class: "nowrap" }, freqText(s)),
          h("td", {}, compSummary(s.components)),
          h("td", { class: "tnum nowrap" }, s.enabled ? fmtRelative(s.next_run) : h("span", { class: "subtle" }, "Đang tắt")),
          h("td", { class: "tnum nowrap subtle" }, s.last_run ? fmtRelative(s.last_run) : "Chưa chạy"),
          h("td", { class: "actions" }, run, " ", del));
      })))));
  }

  async function load() {
    try { render((await api("/api/ui/schedules")).schedules); }
    catch (e) { body.replaceChildren(emptyState("alert", "Không tải được lịch", e.message)); }
  }
  formWrap.hidden = true;
  load();
  return { el, destroy() {} };
}

// ======================================================================== NGUOI DUNG (admin)
export function usersView(ctx) {
  const body = h("div", {}, skeletonRows(3));
  const uname = h("input", { class: "input", required: true, placeholder: "Tên đăng nhập", autocomplete: "off", "aria-label": "Tên đăng nhập" });
  const pw = h("input", { class: "input", type: "password", required: true, minlength: "8", placeholder: "Mật khẩu (≥ 8 ký tự)", autocomplete: "new-password", "aria-label": "Mật khẩu" });
  const role = h("select", { class: "input", "aria-label": "Vai trò" }, h("option", { value: "user", text: "Người dùng" }), h("option", { value: "admin", text: "Quản trị" }));
  const addBtn = h("button", { class: "btn btn-primary", type: "submit" }, icon("plus"), "Thêm");
  const err = h("div", { class: "form-error", hidden: true });
  const form = h("form", { class: "panel", onsubmit: async (e) => {
    e.preventDefault(); err.hidden = true; busy(addBtn, true, "Đang thêm…");
    try {
      await api("/api/ui/users", { method: "POST", body: { username: uname.value.trim(), password: pw.value, role: role.value } });
      toast(`Đã thêm ${uname.value.trim()}`); uname.value = ""; pw.value = ""; load();
    } catch (ex) { err.replaceChildren(icon("alert", "ico-sm"), ex.message); err.hidden = false; } finally { busy(addBtn, false); }
  } }, h("div", { class: "panel-head" }, h("h2", { text: "Thêm người dùng" })),
    h("div", { class: "panel-body" }, h("div", { class: "input-row" }, uname, pw, role, addBtn), err));
  const el = h("div", { class: "view" }, pageHead("Người dùng", "Mỗi người dùng có token riêng cho agent và chỉ thấy bản sao lưu của mình."),
    form, h("section", { class: "panel" }, body));

  function render(users) {
    const me = ctx.state.session.user.id;
    body.replaceChildren(h("div", { class: "table-wrap" }, h("table", { class: "table" },
      h("thead", {}, h("tr", {}, h("th", {}, "Tên đăng nhập"), h("th", {}, "Vai trò"), h("th", {}, "Token agent"), h("th", {}, "Ngày tạo"),
        h("th", { class: "actions" }, h("span", { class: "sr-only" }, "Thao tác")))),
      h("tbody", {}, users.map((u) => {
        const sel = h("select", { class: "input", style: { height: "32px", width: "auto" }, "aria-label": `Vai trò của ${u.username}` },
          h("option", { value: "user", text: "Người dùng", selected: u.role === "user" }),
          h("option", { value: "admin", text: "Quản trị", selected: u.role === "admin" }));
        sel.addEventListener("change", async () => {
          try { await api(`/api/ui/users/${u.id}`, { method: "PATCH", body: { role: sel.value } }); toast("Đã đổi vai trò"); }
          catch (e) { toast(e.message, "err"); sel.value = u.role; }
        });
        const copy = h("button", { class: "btn btn-sm btn-ghost", type: "button", title: "Chép token" }, icon("copy", "ico-sm"), `${u.token.slice(0, 6)}…`);
        copy.addEventListener("click", async () => toast(await copyText(u.token) ? "Đã chép token" : "Không chép được – hãy chép tay ở trang Cài đặt", "info"));
        const pwBtn = h("button", { class: "btn btn-sm", type: "button" }, icon("key", "ico-sm"), "Đặt mật khẩu");
        pwBtn.addEventListener("click", () => setPasswordDialog(u));
        const tokBtn = h("button", { class: "btn btn-sm", type: "button" }, icon("refresh", "ico-sm"), "Token mới");
        tokBtn.addEventListener("click", async () => {
          if (!await confirmDialog({ title: "Tạo token mới?", message: `Agent đang dùng token cũ của ${u.username} sẽ mất kết nối cho tới khi cập nhật agent_config.txt.`, confirmLabel: "Tạo token mới", danger: true })) return;
          try { await api(`/api/ui/users/${u.id}/token`, { method: "POST" }); toast("Đã tạo token mới"); load(); } catch (e) { toast(e.message, "err"); }
        });
        const del = h("button", { class: "btn btn-sm btn-ghost btn-icon", type: "button", disabled: u.id === me, "aria-label": `Xoá ${u.username}` }, icon("trash", "ico-sm"));
        del.addEventListener("click", async () => {
          if (!await confirmDialog({ title: `Xoá ${u.username}?`, message: "Tài khoản, lịch và lịch sử tác vụ của người này bị xoá. File sao lưu trong kho vẫn được giữ.", confirmLabel: "Xoá người dùng", danger: true })) return;
          try { await api(`/api/ui/users/${u.id}`, { method: "DELETE" }); toast("Đã xoá"); load(); } catch (e) { toast(e.message, "err"); }
        });
        return h("tr", {}, h("td", {}, h("strong", { text: u.username }), u.id === me ? h("span", { class: "subtle" }, " (bạn)") : null),
          h("td", {}, sel), h("td", {}, copy), h("td", { class: "tnum nowrap" }, fmtDate(u.created_at)),
          h("td", { class: "actions" }, pwBtn, " ", tokBtn, " ", del));
      })))));
  }

  function setPasswordDialog(u) {
    const inp = h("input", { class: "input", type: "password", minlength: "8", autocomplete: "new-password", "aria-label": "Mật khẩu mới" });
    const err = h("div", { class: "form-error", hidden: true });
    const save = h("button", { class: "btn btn-primary", type: "button" }, "Lưu");
    const cancel = h("button", { class: "btn", type: "button" }, "Huỷ");
    const dlg = dialog({ title: `Đặt mật khẩu cho ${u.username}`,
      body: h("div", { class: "dlg-body" }, field("Mật khẩu mới (≥ 8 ký tự)", inp), err),
      actions: [cancel, save] });
    cancel.addEventListener("click", () => dlg.close());
    save.addEventListener("click", async () => {
      try { await api(`/api/ui/users/${u.id}`, { method: "PATCH", body: { password: inp.value } }); toast("Đã đặt mật khẩu"); dlg.close(); }
      catch (e) { err.replaceChildren(icon("alert", "ico-sm"), e.message); err.hidden = false; }
    });
    inp.focus();
  }

  async function load() {
    try { render((await api("/api/ui/users")).users); }
    catch (e) { body.replaceChildren(emptyState("alert", "Không tải được danh sách", e.message)); }
  }
  load();
  return { el, destroy() {} };
}

// ======================================================================== CAI DAT
export function settingsView(ctx) {
  const el = h("div", { class: "view stack" }, pageHead("Cài đặt"));
  const agentBody = h("div", { class: "panel-body" }, h("span", { class: "skel" }));
  const sysBody = h("div", { class: "panel-body" }, h("span", { class: "skel" }));

  // --- giao dien
  const pref = store.get("bks-theme-pref", null) || (() => { try { return localStorage.getItem("bks-theme") || "light"; } catch { return "light"; } })();
  const theme = h("div", { class: "segmented", role: "radiogroup", "aria-label": "Giao diện" },
    [["light", "Sáng"], ["dark", "Tối"], ["system", "Theo hệ thống"]].map(([v, l]) => h("label", {},
      h("input", { type: "radio", name: "theme", value: v, checked: v === pref, onchange: () => ctx.setTheme(v) }), h("span", { text: l }))));

  // --- mat khau
  const cur = h("input", { class: "input", type: "password", autocomplete: "current-password", required: true });
  const nw = h("input", { class: "input", type: "password", autocomplete: "new-password", minlength: "8", required: true });
  const nw2 = h("input", { class: "input", type: "password", autocomplete: "new-password", required: true });
  const pwErr = h("div", { class: "form-error", hidden: true });
  const pwBtn = h("button", { class: "btn btn-primary", type: "submit" }, "Đổi mật khẩu");
  const pwForm = h("form", { class: "panel", onsubmit: async (e) => {
    e.preventDefault(); pwErr.hidden = true;
    if (nw.value !== nw2.value) { pwErr.replaceChildren(icon("alert", "ico-sm"), "Hai lần nhập mật khẩu mới không khớp"); pwErr.hidden = false; return; }
    busy(pwBtn, true, "Đang lưu…");
    try { await api("/api/ui/me/password", { method: "POST", body: { current: cur.value, new: nw.value } }); toast("Đã đổi mật khẩu"); pwForm.reset(); }
    catch (ex) { pwErr.replaceChildren(icon("alert", "ico-sm"), ex.message); pwErr.hidden = false; } finally { busy(pwBtn, false); }
  } }, h("div", { class: "panel-head" }, h("h2", { text: "Mật khẩu" })),
    h("div", { class: "panel-body" }, h("div", { class: "form-grid" },
      field("Mật khẩu hiện tại", cur),
      field("Mật khẩu mới (≥ 8 ký tự)", nw),
      field("Nhập lại mật khẩu mới", nw2)), pwErr,
      h("div", { class: "btn-row" }, pwBtn)));

  el.append(
    h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", { text: "Kết nối agent" })), agentBody),
    pwForm,
    h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", { text: "Giao diện" })),
      h("div", { class: "panel-body" }, theme, h("p", { class: "subtle", style: { marginTop: "8px" },
        text: "Nền sáng dễ đọc hơn khi chiếu lên máy chiếu." }))),
    h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", { text: "Máy chủ" })), sysBody));

  async function loadAgent() {
    try {
      const { user } = await api("/api/ui/me");
      let shown = false;
      const tok = h("input", { class: "input", type: "password", readonly: true, value: user.token, "aria-label": "Token agent" });
      const eye = h("button", { class: "btn btn-icon", type: "button", "aria-label": "Hiện token" }, icon("eye"));
      eye.addEventListener("click", () => { shown = !shown; tok.type = shown ? "text" : "password"; });
      const snippet = `SERVER_URL=${location.origin}\nAGENT_TOKEN=${user.token}`;
      const copyTok = h("button", { class: "btn", type: "button" }, icon("copy"), "Chép");
      copyTok.addEventListener("click", async () => toast(await copyText(user.token) ? "Đã chép token" : "Trình duyệt chặn chép tự động – bấm hiện rồi chép tay", "info"));
      const copySnip = h("button", { class: "btn btn-sm", type: "button" }, icon("copy", "ico-sm"), "Chép cấu hình");
      copySnip.addEventListener("click", async () => toast(await copyText(snippet) ? "Đã chép cấu hình" : "Không chép được – hãy chọn và chép tay", "info"));
      const rotate = h("button", { class: "btn btn-danger", type: "button" }, icon("refresh"), "Tạo token mới");
      rotate.addEventListener("click", async () => {
        if (!await confirmDialog({ title: "Tạo token mới?", message: "Agent đang chạy sẽ mất kết nối cho tới khi bạn sửa agent_config.txt và khởi động lại agent.", confirmLabel: "Tạo token mới", danger: true })) return;
        try { await api("/api/ui/me/token", { method: "POST" }); toast("Đã tạo token mới"); loadAgent(); } catch (e) { toast(e.message, "err"); }
      });
      const agents = (ctx.state.overview && ctx.state.overview.agents) || [];
      agentBody.replaceChildren(
        h("p", { class: "muted", text: "Trên PC chạy agent, mở agent\\agent_config.txt và dán hai dòng dưới đây, rồi chạy agent\\start_agent.bat." }),
        h("pre", { class: "snippet", text: `SERVER_URL=${location.origin}\nAGENT_TOKEN=••••••••••••` }),
        h("div", { class: "btn-row", style: { marginTop: "12px" } }, copySnip),
        h("div", { class: "field", style: { marginTop: "20px" } }, h("label", { text: "Token của bạn" }),
          h("div", { class: "token-box" }, tok, eye, copyTok, rotate)),
        h("div", { style: { marginTop: "20px" } }, h("div", { class: "label", style: { marginBottom: "6px" } }, "Agent đã từng kết nối"),
          agents.length ? h("ul", { class: "list panel" }, agents.map((a) => h("li", { class: "list-item" },
            h("span", { class: `dot ${a.online ? "ok" : "err"}` }),
            h("div", { class: "grow" }, h("div", { class: "t", text: a.hostname }),
              h("div", { class: "m", text: `${a.ip || "?"} · phiên bản ${a.version || "?"} · ${a.platform || ""}` })),
            h("span", { class: "subtle nowrap", text: a.online ? "Đang kết nối" : `Lần cuối ${fmtRelative(a.last_seen)}` }))))
            : h("p", { class: "subtle", text: "Chưa có agent nào kết nối." })));
    } catch (e) { agentBody.replaceChildren(h("p", { class: "form-error", text: e.message })); }
  }

  async function loadSys() {
    try {
      const s = await api("/api/ui/system");
      const rows = [["Phiên bản", s.version], ["Tên máy chủ", s.hostname], ["Hệ điều hành", s.platform],
        ["Giờ máy chủ", fmtDate(s.server_time)]];
      if (s.storage_dir) rows.push(["Thư mục kho", h("code", { text: s.storage_dir })]);
      const disk = s.disk ? h("div", { style: { marginTop: "20px" } },
        h("div", { class: "label", style: { marginBottom: "6px" } }, "Ổ đĩa chứa kho"),
        h("div", { class: `bar${s.disk.free / s.disk.total < 0.1 ? " err" : ""}` }, h("i", { style: { transform: `scaleX(${s.disk.used / s.disk.total})` } })),
        h("p", { class: "subtle num", style: { marginTop: "6px" }, text: `Đã dùng ${fmtBytes(s.disk.used)} / ${fmtBytes(s.disk.total)} · còn trống ${fmtBytes(s.disk.free)}` })) : null;
      sysBody.replaceChildren(h("dl", { class: "kv" }, rows.map(([k, v]) => [h("dt", { text: k }), h("dd", {}, v)])), disk);
    } catch (e) { sysBody.replaceChildren(h("p", { class: "form-error", text: e.message })); }
  }
  loadAgent();
  loadSys();
  return { el, destroy() {} };
}

export { JOB_TYPE };
