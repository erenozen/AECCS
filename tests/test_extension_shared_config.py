from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from tests._consent_cases import CONSENT_ACTION_CASES
from dark_patterns.detector import detect_confusing_language, detect_preselected_checkboxes
from scraper.crawler import _classify_button_text
from scripts.build_extension_shared_config import build_payload, emit_js
from shared_constants import classify_consent_action


ROOT = Path(__file__).resolve().parents[1]
SHARED_CONFIG = ROOT / "extension" / "lib" / "shared-config.js"


def test_generated_shared_config_matches_python_truth() -> None:
    assert SHARED_CONFIG.read_text(encoding="utf-8") == emit_js(build_payload())


@pytest.mark.parametrize(("language", "label", "expected"), CONSENT_ACTION_CASES)
def test_shared_python_consent_classifier_covers_production_labels(
    language: str, label: str, expected: str
) -> None:
    assert classify_consent_action(label) == expected


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Accept and continue", "accept"),
        ("Reject Optional Cookies", "reject"),
        ("Manage Preferences", "settings"),
        ("Çerez ayarları", "settings"),
        ("Προβολή επιλογών", "settings"),
    ],
)
def test_crawler_button_classifier_uses_shared_vocabulary(label: str, expected: str) -> None:
    assert _classify_button_text(label) == expected


def test_dark_pattern_detector_uses_shared_dismiss_vocabulary() -> None:
    soup = BeautifulSoup(
        """
        <div id="banner">
          <p>We use cookies to improve the site.</p>
          <button type="button">Not now</button>
        </div>
        """,
        "lxml",
    )

    result = detect_confusing_language(soup)

    assert result["detected"] is True
    assert "ambiguous-button: 'not now'" in result["suspicious_phrases"]


def test_dark_pattern_detector_ignores_preselected_necessary_checkbox() -> None:
    soup = BeautifulSoup(
        """
        <form>
          <label for="necessary">Necessary cookies</label>
          <input id="necessary" type="checkbox" checked>
        </form>
        """,
        "lxml",
    )

    result = detect_preselected_checkboxes(soup)

    assert result["checkbox_count"] == 1
    assert result["preselected_count"] == 0
    assert result["detected"] is False
