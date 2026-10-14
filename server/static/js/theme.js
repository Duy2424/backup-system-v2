// Dat giao dien sang/toi TRUOC khi ve trang (tranh nhay mau). Mac dinh: sang (demo tren may chieu).
(function () {
  var pref = "light";
  try { pref = localStorage.getItem("bks-theme") || "light"; } catch (e) { /* trinh duyet chan storage */ }
  var dark = pref === "dark" || (pref === "system" && window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
})();
