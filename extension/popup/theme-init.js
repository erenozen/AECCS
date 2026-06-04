/*
 * Flash-prevention theme bootstrap.
 *
 * Runs synchronously in <head> before the body paints so the correct theme is
 * applied on the very first frame (no light/dark flash on open). It reads a
 * local-only mirror of the theme choice from localStorage; popup.js owns the
 * canonical value in browser.storage.local and keeps this mirror in sync.
 *
 * "system" (or no stored value) leaves the attribute off so the
 * prefers-color-scheme media query decides. No network, no remote assets.
 */
(function () {
  "use strict";
  try {
    var choice = localStorage.getItem("aeccs_theme");
    if (choice === "light" || choice === "dark") {
      document.documentElement.dataset.theme = choice;
    } else {
      delete document.documentElement.dataset.theme;
    }
  } catch (_) {
    /* localStorage may be unavailable; fall back to system/media-query theming. */
  }
})();
