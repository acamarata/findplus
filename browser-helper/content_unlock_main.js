/*
 * MAIN world, on https://accounts.google.com/encryption/unlock/*. Google's
 * unlock page calls window.mm.setVaultSharedKeys(...) with the end-to-end
 * vault keys once the Android screen lock passes. We define that hook (the
 * page has no other way to hand them over) and forward the value to the
 * isolated-world bridge via a same-page message. The bridge drops it unless
 * Find+ has a pending unlock, and the daemon requires a valid single-use
 * state, so this hook alone leaks nothing.
 */
(function () {
  if (window.__findplusMm) return;
  window.__findplusMm = true;
  window.mm = {
    setVaultSharedKeys: function (_str, vaultKeys) {
      window.postMessage({ source: "findplus-mm", method: "setVaultSharedKeys", vaultKeys: vaultKeys }, "*");
    },
    closeView: function () {
      window.postMessage({ source: "findplus-mm", method: "closeView" }, "*");
    },
  };
})();
