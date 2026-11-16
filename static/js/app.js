// ตัวกรองส่งฟอร์มอัตโนมัติ · ปุ่มพิมพ์ — ไม่พึ่งไลบรารีภายนอก
// กำลังโหลดหน้าใหม่: แสดงแถบวิ่งด้านบน + หรี่เนื้อหา (ให้รู้ว่าระบบรับคำสั่งแล้ว ไม่ใช่ค้าง) · กลับด้วยปุ่ม Back ให้เคลียร์
function ncdLoading() { document.body.classList.add("is-loading"); }
window.addEventListener("pageshow", function () { document.body.classList.remove("is-loading"); });
document.addEventListener("click", function (e) {
  var a = e.target.closest(".menu a, .filters a, .tabs a");
  if (a && a.href && !e.ctrlKey && !e.metaKey && !e.shiftKey && a.target !== "_blank") ncdLoading();
});
document.addEventListener("change", function (e) {
  if (e.target.matches("[data-autosubmit]")) { ncdLoading(); e.target.form.submit(); }
});
document.addEventListener("click", function (e) {
  if (e.target.closest("[data-print]")) window.print();
});

// แถบเตือน "ยังไม่ได้ตรวจ" — ซ่อนเมื่อผู้ใช้กดยืนยันในหน้า /check (เก็บในเบราว์เซอร์นี้เท่านั้น)
(function () {
  var banner = document.getElementById("audit-banner");
  function key(h) { return "ncd_audited:" + h; }
  try {
    if (banner && localStorage.getItem(key(banner.dataset.hospital)) === "1") banner.hidden = true;
  } catch (e) { /* localStorage ใช้ไม่ได้ — แสดงแถบต่อไป */ }
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-audited]");
    if (!b) return;
    try { localStorage.setItem(key(b.dataset.audited), "1"); b.textContent = "บันทึกแล้ว (เบราว์เซอร์นี้)"; } catch (err) { b.textContent = "บันทึกไม่ได้ในเบราว์เซอร์นี้"; }
  });
})();
