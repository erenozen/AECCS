/*
 * Cookie Classifier — port of analysis/classifier.py classify_cookie().
 *
 * Classification cascade:
 *   1. Fallback tracker map  (domain → vendor/category)
 *   2. Cookie-name heuristics (regex → vendor/category)
 *   3. First-party defaults   (CDN/session → Functional, else Unknown)
 */

const Classifier = (() => {
  "use strict";

  const bloomCache = new Map();

  function decodeBase64ToBytes(base64) {
    if (!base64) return new Uint8Array(0);
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    return bytes;
  }

  function hashDomain(value, seed) {
    let hash = seed >>> 0;
    for (let i = 0; i < value.length; i++) {
      hash ^= value.charCodeAt(i);
      hash = Math.imul(hash, 16777619) >>> 0;
    }
    return hash >>> 0;
  }

  function getBloomMatcher(key) {
    if (bloomCache.has(key)) return bloomCache.get(key);

    const bloomData = globalThis.AECCSTrackerIndex && globalThis.AECCSTrackerIndex[key];
    if (!bloomData) {
      bloomCache.set(key, null);
      return null;
    }

    const bitCount = bloomData.bitCount || 0;
    const hashSeeds = bloomData.hashSeeds || [];
    const bytes = decodeBase64ToBytes(bloomData.base64 || "");

    const matcher = {
      has(domain) {
        if (!domain || !bitCount || hashSeeds.length === 0 || bytes.length === 0) {
          return false;
        }
        for (const seed of hashSeeds) {
          const position = hashDomain(domain, seed) % bitCount;
          const byte = bytes[position >> 3];
          const mask = 1 << (position & 7);
          if ((byte & mask) === 0) {
            return false;
          }
        }
        return true;
      },
    };

    bloomCache.set(key, matcher);
    return matcher;
  }

  function matchesPrecompiledIndex(key, fullDomain, registeredDomain) {
    const matcher = getBloomMatcher(key);
    if (!matcher) return false;
    return matcher.has(registeredDomain) || matcher.has(fullDomain);
  }

  /**
   * Classify a single cookie.
   *
   * @param {object} cookie        - Raw cookie from browser.cookies API
   * @param {string} cookie.name   - Cookie name
   * @param {string} cookie.domain - Cookie domain (may have leading dot)
   * @param {number} cookie.expirationDate - Unix timestamp (absent for session)
   * @param {string} siteHostname  - Hostname of the active tab
   * @returns {object} Classified cookie record
   */
  function classifyCookie(cookie, siteHostname) {
    const domain = cookie.domain.replace(/^\.+/, "").toLowerCase();
    const registeredDomain = DomainUtils.extractRegisteredDomain(domain);
    const thirdParty = DomainUtils.isThirdParty(domain, siteHostname);

    // Calculate expiration in days (0 for session cookies)
    let expirationDays = 0;
    if (cookie.expirationDate) {
      const nowSec = Date.now() / 1000;
      expirationDays = Math.max(0, Math.round((cookie.expirationDate - nowSec) / 86400));
    }

    const result = {
      name: cookie.name,
      domain: domain,
      registered_domain: registeredDomain,
      is_third_party: thirdParty,
      expiration_days: expirationDays,
      vendor: "Unknown",
      category: "Unknown",
      is_tracker: false,
      classification_source: "unknown",
    };

    // Step 1: Check tracker-domain map by registered/full domain
    const trackerMatch = AECCS.FALLBACK_TRACKERS[registeredDomain]
                      || AECCS.FALLBACK_TRACKERS[domain];
    if (trackerMatch) {
      result.vendor = trackerMatch.vendor;
      result.category = trackerMatch.category;
      result.is_tracker = true;
      result.classification_source = "fallback";
      return result;
    }

    // Step 2: Check the compact precompiled filter index
    if (matchesPrecompiledIndex("easyprivacy", domain, registeredDomain)) {
      result.category = "Analytics";
      result.is_tracker = true;
      result.classification_source = "easyprivacy";
      return result;
    }

    if (matchesPrecompiledIndex("easylist", domain, registeredDomain)) {
      result.category = "Advertising";
      result.is_tracker = true;
      result.classification_source = "easylist";
      return result;
    }

    // Step 3: Check cookie-name heuristics
    for (const h of AECCS.COOKIE_HEURISTICS) {
      if (h.pattern.test(cookie.name)) {
        result.vendor = h.vendor;
        result.category = h.category;
        result.is_tracker = h.category !== "Functional";
        result.classification_source = "heuristic";
        return result;
      }
    }

    // Step 4: First-party heuristic defaults
    if (!thirdParty) {
      if (/cdn|static|assets/i.test(domain)) {
        result.category = "Functional";
        result.classification_source = "heuristic";
        return result;
      }
      if (expirationDays === 0 || expirationDays < 1) {
        result.category = "Functional";
        result.classification_source = "heuristic";
        return result;
      }
    }

    return result;
  }

  /**
   * Classify all cookies for a site.
   *
   * @param {object[]} cookies     - Array of raw cookies from browser.cookies API
   * @param {string}   siteHostname - Hostname of the active tab
   * @returns {object[]} Array of classified cookie records
   */
  function classifyAll(cookies, siteHostname) {
    return cookies.map(c => classifyCookie(c, siteHostname));
  }

  return { classifyCookie, classifyAll };
})();

if (typeof globalThis !== "undefined") {
  globalThis.Classifier = Classifier;
}
