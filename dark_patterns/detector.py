"""
Dark pattern detector for cookie consent banners.

Analyzes saved consent banner HTML to detect deceptive UI practices
that undermine user autonomy, including:

- Asymmetric buttons: The "Accept" button is visually dominant (larger,
  brighter colour, higher contrast) compared to the "Reject" button.
- Missing reject option: No "Reject All" button is present.
- Pre-selected checkboxes: Non-essential cookie categories are pre-checked.
- Confusing language: Double negatives, ambiguous wording, guilt-tripping.
- Hidden reject: The reject option is visually hidden.
- Forced action: Cookie walls blocking page content.
- Multi-layer rejection: Reject requires more clicks than accept.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

from config import (
    BANNERS_DIR,
    CONSENT_BUTTON_KEYWORDS,
    DEFAULT_SOURCE_MODE,
    PROCESSED_DIR,
    RAW_DIR,
    build_provenance,
    get_dataset_layout,
)

# ── Suspicious language patterns ──────────────────────────────────────────────

_GUILT_TRIP_PHRASES = [
    # English
    "keep the site free", "support our journalist", "help us improve",
    "you'll miss out", "you will miss out", "miss personalized",
    "enjoy a better experience", "support free journalism",
    "we need your support", "without your support",
    "fund our work", "keep this site running",
    "best experience", "optimal experience",
    # German
    "unterstützen sie uns", "helfen sie uns", "kostenlos halten",
    "bessere erfahrung", "optimale erfahrung",
    # French
    "soutenez-nous", "aidez-nous", "meilleure expérience",
    "garder le site gratuit", "expérience optimale",
    # Dutch
    "steun ons", "help ons", "beste ervaring",
]

_DOUBLE_NEGATIVE_PATTERNS = [
    re.compile(r"don'?t\s+(not|reject|refuse|decline)", re.I),
    re.compile(r"nicht\s+(ablehnen|verweigern)", re.I),
    re.compile(r"ne\s+pas\s+(refuser|rejeter)", re.I),
    re.compile(r"I\s+do\s+not\s+want\s+to\s+not", re.I),
]

_AMBIGUOUS_BUTTON_TEXTS = [
    "ok", "okay", "continue", "got it", "i understand", "understood",
    "close", "dismiss", "later", "not now", "remind me later",
    "weiter", "verstanden", "schliessen", "schließen",
    "continuer", "compris", "j'ai compris", "fermer",
    "doorgaan", "begrepen", "sluiten",
]

# Necessary-cookie checkbox label keywords (these are legitimately pre-checked)
_NECESSARY_KEYWORDS = [
    "necessary", "essential", "required", "strictly necessary",
    "erforderlich", "notwendig", "unbedingt erforderlich",
    "nécessaire", "strictement nécessaire",
    "noodzakelijk", "strikt noodzakelijk",
    "necesario", "estrictamente necesario",
    "necessario", "strettamente necessario",
    "gerekli", "zorunlu",
]


# ── CSS Parsing Helpers ──────────────────────────────────────────────────────


def _parse_px(value: str | None) -> float:
    """Extract numeric pixel value from strings like '200px', '16.5px'."""
    if not value:
        return 0.0
    m = re.search(r"([\d.]+)", str(value))
    return float(m.group(1)) if m else 0.0


def _parse_font_weight(value: str | None) -> int:
    """Parse font-weight: '700', 'bold', 'normal', etc."""
    if not value:
        return 400
    val = str(value).strip().lower()
    weight_map = {"bold": 700, "bolder": 800, "normal": 400, "lighter": 300}
    if val in weight_map:
        return weight_map[val]
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return 400


def _parse_rgb(color_str: str | None) -> tuple[int, int, int] | None:
    """Parse rgb/rgba/hex colour strings into (R, G, B) tuple."""
    if not color_str:
        return None
    s = str(color_str).strip().lower()

    # rgb(r, g, b) or rgba(r, g, b, a)
    m = re.match(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", s)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # Hex: #rrggbb or #rgb
    m = re.match(r"#([0-9a-f]{6})", s)
    if m:
        h = m.group(1)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    m = re.match(r"#([0-9a-f]{3})$", s)
    if m:
        h = m.group(1)
        return (int(h[0] * 2, 16), int(h[1] * 2, 16), int(h[2] * 2, 16))

    # Named colours (common ones)
    named = {
        "white": (255, 255, 255), "black": (0, 0, 0),
        "red": (255, 0, 0), "green": (0, 128, 0), "blue": (0, 0, 255),
        "gray": (128, 128, 128), "grey": (128, 128, 128),
        "transparent": (255, 255, 255),
    }
    return named.get(s)


def _relative_luminance(r: int, g: int, b: int) -> float:
    """Calculate relative luminance per WCAG formula."""
    def _linearize(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    return 0.2126 * _linearize(r) + 0.7152 * _linearize(g) + 0.0722 * _linearize(b)


def _contrast_ratio(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    """WCAG contrast ratio between two colours."""
    l1 = _relative_luminance(*fg) + 0.05
    l2 = _relative_luminance(*bg) + 0.05
    return max(l1, l2) / min(l1, l2)


# ── Individual Pattern Detectors ─────────────────────────────────────────────


def detect_asymmetric_buttons(soup: BeautifulSoup, site_data: dict | None = None) -> dict:
    """Check for visual asymmetry between accept and reject buttons."""
    result: dict = {
        "detected": False,
        "accept_button": None,
        "reject_button": None,
        "size_ratio": None,
        "font_size_ratio": None,
        "contrast_issue": False,
    }

    accept_btn = None
    reject_btn = None

    # Get button data from crawler output if available
    banner = (site_data or {}).get("consent_banner") or {}
    buttons = banner.get("buttons", [])

    for btn in buttons:
        if btn.get("type") == "accept" and accept_btn is None:
            accept_btn = btn
        elif btn.get("type") == "reject" and reject_btn is None:
            reject_btn = btn

    if not accept_btn or not reject_btn:
        return result

    a_styles = accept_btn.get("computed_styles", {})
    r_styles = reject_btn.get("computed_styles", {})

    a_w = _parse_px(a_styles.get("width"))
    a_h = _parse_px(a_styles.get("height"))
    r_w = _parse_px(r_styles.get("width"))
    r_h = _parse_px(r_styles.get("height"))

    a_fs = _parse_px(a_styles.get("font_size"))
    r_fs = _parse_px(r_styles.get("font_size"))

    a_fw = _parse_font_weight(a_styles.get("font_weight"))
    r_fw = _parse_font_weight(r_styles.get("font_weight"))

    accept_info = {
        "text": accept_btn.get("text", ""),
        "width": a_w, "height": a_h,
        "font_size": a_fs, "font_weight": a_fw,
        "bg_color": a_styles.get("background_color", ""),
    }
    reject_info = {
        "text": reject_btn.get("text", ""),
        "width": r_w, "height": r_h,
        "font_size": r_fs, "font_weight": r_fw,
        "bg_color": r_styles.get("background_color", ""),
    }

    result["accept_button"] = accept_info
    result["reject_button"] = reject_info

    # Size ratio
    a_area = a_w * a_h if a_w > 0 and a_h > 0 else 0
    r_area = r_w * r_h if r_w > 0 and r_h > 0 else 0
    if a_area > 0:
        size_ratio = r_area / a_area
        result["size_ratio"] = round(size_ratio, 3)
    else:
        size_ratio = 1.0

    # Font size ratio
    if a_fs > 0:
        fs_ratio = r_fs / a_fs
        result["font_size_ratio"] = round(fs_ratio, 3)
    else:
        fs_ratio = 1.0

    # Font weight diff
    fw_diff = a_fw - r_fw

    # Contrast check on reject button
    r_fg = _parse_rgb(r_styles.get("color"))
    r_bg = _parse_rgb(r_styles.get("background_color"))
    if r_fg and r_bg:
        cr = _contrast_ratio(r_fg, r_bg)
        if cr < 3.0:
            result["contrast_issue"] = True

    # Determine if asymmetric
    if size_ratio < 0.7 or fs_ratio < 0.85 or fw_diff > 200 or result["contrast_issue"]:
        result["detected"] = True

    return result


def detect_hidden_reject(soup: BeautifulSoup, site_data: dict | None = None) -> dict:
    """Check if the reject button exists but is visually hidden."""
    result: dict = {"detected": False, "description": None}

    banner = (site_data or {}).get("consent_banner") or {}
    buttons = banner.get("buttons", [])

    hidden_classes = {"hidden", "sr-only", "visually-hidden", "d-none", "invisible"}

    for btn in buttons:
        if btn.get("type") != "reject":
            continue
        styles = btn.get("computed_styles", {})
        reasons = []

        if styles.get("display") == "none":
            reasons.append("display:none")
        if styles.get("visibility") == "hidden":
            reasons.append("visibility:hidden")

        w = _parse_px(styles.get("width"))
        h = _parse_px(styles.get("height"))
        if w == 0 or h == 0:
            reasons.append("zero dimensions")

        # Check text blending with background
        fg = _parse_rgb(styles.get("color"))
        bg = _parse_rgb(styles.get("background_color"))
        if fg and bg and fg == bg:
            reasons.append("text matches background")

        if reasons:
            result["detected"] = True
            result["description"] = f"Reject button hidden: {', '.join(reasons)}"
            return result

    # Also check HTML for hidden-class patterns
    for btn_tag in soup.find_all(["button", "a", "input"]):
        text = btn_tag.get_text(strip=True).lower()
        reject_kws = [kw.lower() for kw in CONSENT_BUTTON_KEYWORDS["reject"]]
        if not any(kw in text for kw in reject_kws):
            continue
        classes = " ".join(btn_tag.get("class", []))
        style_attr = btn_tag.get("style", "")
        for hc in hidden_classes:
            if hc in classes.lower():
                result["detected"] = True
                result["description"] = f"Reject button has hidden class: {hc}"
                return result
        if "display:none" in style_attr.replace(" ", "") or "display: none" in style_attr:
            result["detected"] = True
            result["description"] = "Reject button has inline display:none"
            return result
        if "visibility:hidden" in style_attr.replace(" ", "") or "visibility: hidden" in style_attr:
            result["detected"] = True
            result["description"] = "Reject button has inline visibility:hidden"
            return result

    return result


def detect_missing_reject(site_data: dict | None = None) -> dict:
    """Check if the consent banner has no reject option at all."""
    result: dict = {"detected": False, "description": None}

    banner = (site_data or {}).get("consent_banner") or {}
    if not banner.get("found"):
        result["detected"] = True
        result["description"] = "No consent banner found"
        return result

    if not banner.get("has_reject_button", False):
        result["detected"] = True
        result["description"] = "No reject button in consent banner"
        return result

    if banner.get("reject_clicks_required", 0) == 999:
        result["detected"] = True
        result["description"] = "Reject path unreachable (999 clicks)"
        return result

    return result


def detect_preselected_checkboxes(soup: BeautifulSoup) -> dict:
    """Check for pre-selected non-essential consent checkboxes."""
    result: dict = {
        "detected": False,
        "checkbox_count": 0,
        "preselected_count": 0,
    }

    checkboxes = soup.find_all("input", {"type": "checkbox"})
    result["checkbox_count"] = len(checkboxes)

    preselected = 0
    for cb in checkboxes:
        if not cb.has_attr("checked"):
            continue
        # Check if label text indicates a "necessary" checkbox
        label_text = ""
        cb_id = cb.get("id", "")
        if cb_id:
            label = soup.find("label", {"for": cb_id})
            if label:
                label_text = label.get_text(strip=True).lower()
        if not label_text:
            parent = cb.parent
            if parent:
                label_text = parent.get_text(strip=True).lower()

        is_necessary = any(kw in label_text for kw in _NECESSARY_KEYWORDS)
        if not is_necessary:
            preselected += 1

    result["preselected_count"] = preselected
    if preselected > 0:
        result["detected"] = True

    return result


def detect_forced_action(soup: BeautifulSoup, site_data: dict | None = None) -> dict:
    """Detect cookie walls that block page content."""
    result: dict = {"detected": False, "is_cookie_wall": False}

    wall_indicators = ["wall", "blocker", "overlay", "modal", "blocking"]

    # Check all divs/sections for wall-like attributes
    for el in soup.find_all(["div", "section", "aside"]):
        classes = " ".join(el.get("class", [])).lower()
        el_id = (el.get("id") or "").lower()
        style = (el.get("style") or "").lower()

        has_indicator = any(w in classes or w in el_id for w in wall_indicators)
        has_fixed = "position:fixed" in style.replace(" ", "") or "position: fixed" in style
        has_full = ("width:100%" in style.replace(" ", "") or
                    "height:100%" in style.replace(" ", "") or
                    "width: 100%" in style or "height: 100%" in style)

        if has_indicator and (has_fixed or has_full):
            result["detected"] = True
            result["is_cookie_wall"] = True
            return result

    # Also check for a blur overlay or similar
    for el in soup.find_all(["div", "section"]):
        classes = " ".join(el.get("class", [])).lower()
        if "no-blur" not in classes and ("blur" in classes or "backdrop" in classes):
            style = (el.get("style") or "").lower()
            if "position:fixed" in style.replace(" ", "") or "position: fixed" in style:
                result["detected"] = True
                result["is_cookie_wall"] = True
                return result

    return result


def detect_multi_layer_rejection(site_data: dict | None = None) -> dict:
    """Check if rejecting requires more clicks than accepting."""
    result: dict = {
        "detected": False,
        "accept_clicks": None,
        "reject_clicks": None,
        "click_ratio": None,
    }

    banner = (site_data or {}).get("consent_banner") or {}
    a_clicks = banner.get("accept_clicks_required", 999)
    r_clicks = banner.get("reject_clicks_required", 999)

    result["accept_clicks"] = a_clicks
    result["reject_clicks"] = r_clicks

    if a_clicks > 0 and r_clicks > 0:
        result["click_ratio"] = round(r_clicks / a_clicks, 2) if a_clicks < 999 else None

    if r_clicks > a_clicks and a_clicks < 999:
        result["detected"] = True

    return result


def detect_confusing_language(soup: BeautifulSoup) -> dict:
    """Scan banner text for manipulative or confusing language patterns."""
    result: dict = {"detected": False, "suspicious_phrases": []}

    text = soup.get_text(separator=" ", strip=True).lower()
    phrases_found: list[str] = []

    # Guilt-tripping
    for phrase in _GUILT_TRIP_PHRASES:
        if phrase.lower() in text:
            phrases_found.append(f"guilt-trip: '{phrase}'")

    # Double negatives
    for pat in _DOUBLE_NEGATIVE_PATTERNS:
        m = pat.search(text)
        if m:
            phrases_found.append(f"double-negative: '{m.group(0)}'")

    # Ambiguous button texts
    for btn_tag in soup.find_all(["button", "a", "input"]):
        btn_text = btn_tag.get_text(strip=True).lower()
        if btn_text in _AMBIGUOUS_BUTTON_TEXTS:
            phrases_found.append(f"ambiguous-button: '{btn_text}'")

    result["suspicious_phrases"] = phrases_found
    if phrases_found:
        result["detected"] = True

    return result


# ── Main analysis function ───────────────────────────────────────────────────


def analyze_banner_html(
    html_path: str, site_data: dict | None = None
) -> dict:
    """Analyze a single consent banner's HTML for dark patterns.

    Args:
        html_path: Path to the saved banner HTML file.
        site_data: Optional full site JSON data for button styles and click counts.

    Returns:
        A dict with boolean flags for each dark pattern type and an
        overall dark_pattern_count.
    """
    path = Path(html_path)
    domain = path.stem  # e.g., "lemonde.fr"

    html = path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")

    # Run all detectors
    asymmetric = detect_asymmetric_buttons(soup, site_data)
    hidden = detect_hidden_reject(soup, site_data)
    missing = detect_missing_reject(site_data)
    preselected = detect_preselected_checkboxes(soup)
    forced = detect_forced_action(soup, site_data)
    multi_layer = detect_multi_layer_rejection(site_data)
    confusing = detect_confusing_language(soup)

    all_detections = {
        "asymmetric_buttons": asymmetric,
        "hidden_reject": hidden,
        "missing_reject": missing,
        "preselected_checkboxes": preselected,
        "forced_action": forced,
        "multi_layer_rejection": multi_layer,
        "confusing_language": confusing,
    }

    detected_names = [name for name, det in all_detections.items() if det.get("detected")]

    return {
        "domain": domain,
        "banner_found": True,
        "dark_patterns_detected": detected_names,
        "dark_pattern_count": len(detected_names),
        "details": all_detections,
    }


def _analyze_no_banner(domain: str) -> dict:
    """Return a result for a site with no banner HTML saved."""
    return {
        "domain": domain,
        "banner_found": False,
        "dark_patterns_detected": [],
        "dark_pattern_count": 0,
        "details": {
            "asymmetric_buttons": {"detected": False},
            "hidden_reject": {"detected": False, "description": None},
            "missing_reject": {"detected": False, "description": None},
            "preselected_checkboxes": {"detected": False, "checkbox_count": 0, "preselected_count": 0},
            "forced_action": {"detected": False, "is_cookie_wall": False},
            "multi_layer_rejection": {"detected": False, "accept_clicks": None, "reject_clicks": None, "click_ratio": None},
            "confusing_language": {"detected": False, "suspicious_phrases": []},
        },
    }


def run_dark_pattern_detection(
    banners_dir: str | None = None,
    raw_dir: str | None = None,
    output_dir: str | None = None,
    source_mode: str = DEFAULT_SOURCE_MODE,
    run_id: str | None = None,
) -> None:
    """Batch-analyze all saved consent banners for dark patterns."""
    layout = get_dataset_layout(source_mode)
    b_dir = Path(banners_dir) if banners_dir else layout.banners_dir
    r_dir = Path(raw_dir) if raw_dir else layout.raw_dir
    o_dir = Path(output_dir) if output_dir else layout.processed_dir
    o_dir.mkdir(parents=True, exist_ok=True)

    # Process banners that exist
    banner_files = sorted(b_dir.glob("*.html"))

    # Also check for sites that were crawled but have no banner file
    # (we still want missing_reject/multi_layer analyses from site_data)
    raw_files = sorted(r_dir.glob("*.json"))
    all_domains = set()
    for rf in raw_files:
        all_domains.add(rf.stem)
    banner_domains = {bf.stem for bf in banner_files}

    total = 0
    pattern_counter = {}

    for domain in sorted(all_domains):
        # Load site data
        site_json = r_dir / f"{domain}.json"
        site_data = None
        if site_json.exists():
            try:
                site_data = json.loads(site_json.read_text(encoding="utf-8"))
            except Exception:
                pass

        banner_path = b_dir / f"{domain}.html"
        if banner_path.exists():
            try:
                result = analyze_banner_html(str(banner_path), site_data)
            except Exception as exc:
                print(f"[ERROR] {domain}: {exc}")
                continue
        else:
            # No banner HTML -- use site_data for what we can
            result = _analyze_no_banner(domain)
            if site_data:
                result["details"]["missing_reject"] = detect_missing_reject(site_data)
                result["details"]["multi_layer_rejection"] = detect_multi_layer_rejection(site_data)
                detected = [
                    n for n, d in result["details"].items() if d.get("detected")
                ]
                result["dark_patterns_detected"] = detected
                result["dark_pattern_count"] = len(detected)

        out_path = o_dir / f"{domain}_dark_patterns.json"
        provenance = build_provenance(
            source_mode=(site_data or {}).get("source_mode", source_mode),
            run_id=(site_data or {}).get("run_id", run_id),
            proxy_used=(site_data or {}).get("proxy_used"),
            browser_name=(site_data or {}).get("browser_name"),
            browser_version=(site_data or {}).get("browser_version"),
            site_list_source=(site_data or {}).get("site_list_source"),
        )
        result.update(provenance)
        out_path.write_text(
            json.dumps(result, indent=2, default=str), encoding="utf-8"
        )
        total += 1

        for dp_name in result["dark_patterns_detected"]:
            pattern_counter[dp_name] = pattern_counter.get(dp_name, 0) + 1

        dp_str = ", ".join(result["dark_patterns_detected"]) or "none"
        print(f"[OK] {domain}: {result['dark_pattern_count']} patterns ({dp_str})")

    # Summary
    sites_with_dp = sum(1 for _ in [] if True)  # will count below
    print(f"\n{'=' * 60}")
    print(f"Dark pattern detection complete: {total} sites analyzed")
    if total > 0:
        print(f"\nPattern prevalence:")
        for name, count in sorted(pattern_counter.items(), key=lambda x: -x[1]):
            pct = count / total * 100
            print(f"  {name:30s} {count:>4d} ({pct:.1f}%)")
    print(f"{'=' * 60}")


# ── CLI Entry Point ──────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AECCS dark pattern detector for consent banners"
    )
    parser.add_argument(
        "--domain", type=str, default=None,
        help="Analyze a single domain only",
    )
    parser.add_argument(
        "--banners-dir", type=str, default=None,
        help=f"Directory with banner HTML files (default: {BANNERS_DIR})",
    )
    parser.add_argument(
        "--raw-dir", type=str, default=None,
        help=f"Directory with raw crawl JSON files (default: {RAW_DIR})",
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help=f"Output directory (default: {PROCESSED_DIR})",
    )
    parser.add_argument(
        "--source-mode",
        default=DEFAULT_SOURCE_MODE,
        help="Dataset/output mode to use (default: real)",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Optional run identifier to stamp onto generated artifacts",
    )
    args = parser.parse_args()

    if args.domain:
        layout = get_dataset_layout(args.source_mode)
        r_dir = Path(args.raw_dir) if args.raw_dir else layout.raw_dir
        o_dir = Path(args.output_dir) if args.output_dir else layout.processed_dir
        o_dir.mkdir(parents=True, exist_ok=True)
        b_dir = Path(args.banners_dir) if args.banners_dir else layout.banners_dir

        site_json = r_dir / f"{args.domain}.json"
        site_data = None
        if site_json.exists():
            site_data = json.loads(site_json.read_text(encoding="utf-8"))

        banner_path = b_dir / f"{args.domain}.html"
        if banner_path.exists():
            result = analyze_banner_html(str(banner_path), site_data)
        else:
            result = _analyze_no_banner(args.domain)
            if site_data:
                result["details"]["missing_reject"] = detect_missing_reject(site_data)
                result["details"]["multi_layer_rejection"] = detect_multi_layer_rejection(site_data)
                detected = [
                    n for n, d in result["details"].items() if d.get("detected")
                ]
                result["dark_patterns_detected"] = detected
                result["dark_pattern_count"] = len(detected)

        out_path = o_dir / f"{args.domain}_dark_patterns.json"
        provenance = build_provenance(
            source_mode=(site_data or {}).get("source_mode", args.source_mode),
            run_id=(site_data or {}).get("run_id", args.run_id),
            proxy_used=(site_data or {}).get("proxy_used"),
            browser_name=(site_data or {}).get("browser_name"),
            browser_version=(site_data or {}).get("browser_version"),
            site_list_source=(site_data or {}).get("site_list_source"),
        )
        result.update(provenance)
        out_path.write_text(
            json.dumps(result, indent=2, default=str), encoding="utf-8"
        )
        dp_str = ", ".join(result["dark_patterns_detected"]) or "none"
        print(f"[OK] {args.domain}: {result['dark_pattern_count']} patterns ({dp_str})")
        return

    run_dark_pattern_detection(
        banners_dir=args.banners_dir,
        raw_dir=args.raw_dir,
        output_dir=args.output_dir,
        source_mode=args.source_mode,
        run_id=args.run_id,
    )


if __name__ == "__main__":
    main()
