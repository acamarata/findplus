/*
 * Runs on Find+'s own begin page (http://127.0.0.1/auth/google/begin*). It
 * marks the page so the page's own script knows the helper is installed, and
 * hands the single-use state to the service worker. It does NOT navigate; the
 * begin page decides when to redirect to Google. Isolated world.
 */
(function () {
  try {
    document.documentElement.setAttribute("data-findplus-helper", "1");
    var params = new URLSearchParams(location.search);
    var state = params.get("state");
    if (!state) return;
    var mode = location.pathname.indexOf("/unlock/") !== -1 ? "unlock" : "signin";
    chrome.runtime.sendMessage({
      type: "findplus-begin",
      mode: mode,
      state: state,
      port: location.port || "80",
    });
  } catch (_err) {
    /* not our page, or the worker is gone; the begin page falls back to install steps */
  }
})();
