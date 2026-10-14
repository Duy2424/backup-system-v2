// Hop thoai chon thu muc tren may agent (server proxy toi folder browser cua agent).
import { api, dialog, h, icon } from "./lib.js";

const QUICK_ICON = { drive: "drive" };

function crumbsOf(path) {
  // "C:\Users\Duy" -> [["C:\", "C:\"], ["Users", "C:\Users"], ["Duy", "C:\Users\Duy"]]
  if (!path) return [];
  const isWin = /^[A-Za-z]:/.test(path);
  const sep = isWin ? "\\" : "/";
  const parts = path.split(/[\\/]+/).filter(Boolean);
  const out = [];
  let acc = isWin ? "" : "/";
  parts.forEach((p, i) => {
    if (isWin && i === 0) acc = `${p}\\`;
    else acc = acc.endsWith(sep) ? acc + p : acc + sep + p;
    out.push([isWin && i === 0 ? `${p}\\` : p, acc]);
  });
  return out;
}

export function pickFolder({ title = "Chọn thư mục trên máy agent", initial = "" } = {}) {
  return new Promise((resolve) => {
    let current = initial || "";
    let chosen = null;
    let ctrl = null;

    const side = h("div", { class: "picker-side", "aria-label": "Thư mục hay dùng" },
      h("div", { class: "picker-msg", text: "Đang tải…" }));
    const pathInput = h("input", { class: "input", placeholder: "Gõ đường dẫn, vd D:\\DuLieu", "aria-label": "Đường dẫn" });
    const goBtn = h("button", { class: "btn", type: "button" }, "Mở");
    const crumbs = h("nav", { class: "crumbs", "aria-label": "Đường dẫn hiện tại" });
    const list = h("div", { class: "picker-list", role: "list" });
    const selLabel = h("code", { class: "truncate" });
    const chooseBtn = h("button", { class: "btn btn-primary", type: "button" }, icon("check"), "Chọn thư mục này");
    const cancelBtn = h("button", { class: "btn", type: "button" }, "Huỷ");

    const body = h("div", { class: "picker" }, side,
      h("div", { class: "picker-main" }, h("div", { class: "picker-path" }, pathInput, goBtn), crumbs, list));
    const foot = [h("div", { class: "subtle truncate", style: { marginRight: "auto", maxWidth: "50%" } }, "Đã chọn: ", selLabel),
      cancelBtn, chooseBtn];
    const dlg = dialog({ title, body, actions: foot, wide: true, onClose: () => resolve(chosen) });

    function renderCrumbs() {
      const items = [h("button", { type: "button", onclick: () => load("") }, "Máy agent")];
      for (const [label, p] of crumbsOf(current)) {
        items.push(h("span", { class: "sep", "aria-hidden": "true" }, "›"),
          h("button", { type: "button", onclick: () => load(p) }, label));
      }
      crumbs.replaceChildren(...items);
      selLabel.textContent = current || "(chưa chọn)";
      chooseBtn.disabled = !current;
      pathInput.value = current;
    }

    async function load(path) {
      if (ctrl) ctrl.abort();
      ctrl = new AbortController();
      current = path;
      renderCrumbs();
      list.replaceChildren(h("div", { class: "picker-msg", text: "Đang tải…" }));
      try {
        const data = await api(`/api/ui/fs/list?path=${encodeURIComponent(path)}`, { signal: ctrl.signal });
        if (data.error) throw new Error(data.error);
        const folders = data.folders || [];
        if (!folders.length) {
          list.replaceChildren(h("div", { class: "picker-msg", text: "Không có thư mục con. Bấm “Chọn thư mục này” để dùng thư mục hiện tại." }));
          return;
        }
        list.replaceChildren(...folders.map((f) =>
          h("button", { type: "button", role: "listitem", onclick: () => load(f.path), title: f.path },
            icon(f.is_drive ? "drive" : "folder"), h("span", { class: "truncate", text: f.name }))));
      } catch (e) {
        if (e.name === "AbortError") return;
        list.replaceChildren(h("div", { class: "picker-msg" },
          h("p", { text: e.message }),
          h("p", { class: "subtle", text: "Vẫn có thể gõ đường dẫn ở trên rồi bấm “Chọn thư mục này”." })));
      }
    }

    async function loadQuick() {
      try {
        const data = await api("/api/ui/fs/quick");
        const picks = data.quick_picks || [];
        side.replaceChildren(...picks.map((p) =>
          h("button", { type: "button", onclick: () => load(p.path), title: p.path },
            icon(QUICK_ICON[p.icon] || "folder"), h("span", { class: "truncate", text: p.name }))));
      } catch (e) {
        side.replaceChildren(h("div", { class: "picker-msg", text: e.message }));
      }
    }

    goBtn.addEventListener("click", () => load(pathInput.value.trim()));
    pathInput.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); load(pathInput.value.trim()); } });
    cancelBtn.addEventListener("click", () => dlg.close());
    chooseBtn.addEventListener("click", () => {
      chosen = (pathInput.value.trim() || current) || null;
      dlg.close();
    });
    loadQuick();
    load(current);
  });
}
