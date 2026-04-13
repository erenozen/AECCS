/* Browser API polyfill — normalizes Chrome's `chrome` namespace to `browser` */
if (typeof globalThis.browser === "undefined") {
  globalThis.browser = chrome;
}
