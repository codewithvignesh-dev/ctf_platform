/*
 * Best-effort client-side anti-cheat.
 * NOTE: True, unbypassable blocking of devtools/F12 is not possible from
 * client-side JS alone (a determined user can always disable JS or use
 * browser dev tools before the page loads). This script raises violations
 * to the server, which enforces the actual block/disqualify decision.
 */
(function () {
  const REPORT_URL = "/api/anti-cheat/report";
  let devtoolsWarned = false;

  function reportViolation(type) {
    fetch(REPORT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type }),
    })
      .then((r) => r.json())
      .then((data) => {
        showToast(type, data);
        if (data.blocked) {
          setTimeout(() => {
            window.location.href = "/logout";
          }, 2000);
        }
      })
      .catch(() => {});
  }

  function showToast(type, data) {
    const el = document.createElement("div");
    el.className =
      "fixed bottom-4 right-4 z-[9999] px-4 py-3 rounded-lg border text-sm shadow-lg " +
      (data.blocked
        ? "bg-danger/10 border-danger text-danger"
        : "bg-warn/10 border-warn text-warn");
    el.innerText = data.blocked
      ? "Violation limit exceeded. Your account has been BLOCKED."
      : `Warning ${data.total_violations}/${data.block_limit}: ${type.replace("_", " ")} detected. Further violations will get you permanently blocked.`;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 5000);
  }

  // --- Tab switch / window blur detection ---
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) reportViolation("tab_switch");
  });
  window.addEventListener("blur", () => reportViolation("tab_switch"));

  // --- Disable right-click, copy, cut, paste ---
  document.addEventListener("contextmenu", (e) => e.preventDefault());
  document.addEventListener("copy", (e) => {
    e.preventDefault();
    reportViolation("copy_paste");
  });
  document.addEventListener("cut", (e) => e.preventDefault());
  document.addEventListener("paste", (e) => {
    e.preventDefault();
    reportViolation("copy_paste");
  });

  // --- Block common devtools / view-source shortcuts ---
  document.addEventListener("keydown", (e) => {
    const key = e.key ? e.key.toUpperCase() : "";
    const blockedCombo =
      key === "F12" ||
      (e.ctrlKey && e.shiftKey && ["I", "J", "C"].includes(key)) ||
      (e.ctrlKey && key === "U");

    if (blockedCombo) {
      e.preventDefault();
      reportViolation("devtools");
    }
  });

  // --- Heuristic devtools-open detection (window size delta) ---
  const threshold = 160;
  setInterval(() => {
    const widthDelta = window.outerWidth - window.innerWidth;
    const heightDelta = window.outerHeight - window.innerHeight;
    if ((widthDelta > threshold || heightDelta > threshold) && !devtoolsWarned) {
      devtoolsWarned = true;
      reportViolation("devtools");
      setTimeout(() => (devtoolsWarned = false), 5000);
    }
  }, 1500);
})();
