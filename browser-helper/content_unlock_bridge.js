/*
 * Isolated world, on https://accounts.google.com/encryption/unlock/*. Bridges
 * the MAIN-world hook to the service worker, but only while Find+ has a pending
 * unlock (asked once at start). Vault keys reach only the worker, which sends
 * them only to 127.0.0.1 with the single-use state.
 */
(function () {
  var active = false;
  try {
    chrome.runtime.sendMessage({ type: "findplus-unlock-active" }, function (resp) {
      active = Boolean(resp && resp.active);
    });
  } catch (_err) {
    /* worker unavailable: stay inactive, forward nothing */
  }
  window.addEventListener("message", function (event) {
    if (event.source !== window) return;
    var data = event.data;
    if (!data || data.source !== "findplus-mm") return;
    if (active && data.method === "setVaultSharedKeys") {
      try {
        chrome.runtime.sendMessage({ type: "findplus-vault", vaultKeys: data.vaultKeys });
      } catch (_err) {
        /* nothing to do */
      }
    }
  });
})();
