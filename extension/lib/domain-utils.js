/*
 * Lightweight TLD extraction — replaces Python's tldextract without any
 * external library.  Handles common multi-part TLDs (co.uk, com.au …).
 */

const DomainUtils = (() => {
  "use strict";

  const MULTI_TLDS = new Set([
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk",
    "com.au", "net.au", "org.au",
    "com.br",
    "co.jp", "ac.jp", "or.jp", "ne.jp",
    "co.kr",
    "co.in",
    "co.za",
    "com.tr",
    "com.mx",
    "co.nz",
    "com.ar",
    "com.cn",
    "com.tw",
    "co.il",
    "com.sg",
    "com.hk",
    "co.th",
    "com.ua",
    "com.pk",
    "com.my",
    "com.ng",
    "com.eg",
    "com.vn",
    "com.ph",
    "com.co",
    "com.pe",
  ]);

  /**
   * Extract the registered domain from a hostname.
   * e.g. "tracker.ads.doubleclick.net" → "doubleclick.net"
   *      "www.bbc.co.uk"              → "bbc.co.uk"
   */
  function extractRegisteredDomain(hostname) {
    hostname = hostname.replace(/^\.+/, "").toLowerCase();

    const parts = hostname.split(".");
    if (parts.length <= 2) return hostname;

    const lastTwo = parts.slice(-2).join(".");
    if (MULTI_TLDS.has(lastTwo)) {
      return parts.length >= 3 ? parts.slice(-3).join(".") : hostname;
    }

    return parts.slice(-2).join(".");
  }

  /**
   * Determine if a cookie domain is third-party relative to the site domain.
   */
  function isThirdParty(cookieDomain, siteDomain) {
    const cookieReg = extractRegisteredDomain(cookieDomain);
    const siteReg = extractRegisteredDomain(siteDomain);
    return cookieReg !== siteReg;
  }

  return { extractRegisteredDomain, isThirdParty };
})();

if (typeof globalThis !== "undefined") {
  globalThis.DomainUtils = DomainUtils;
}
