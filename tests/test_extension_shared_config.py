from __future__ import annotations

from pathlib import Path

import pytest

from scripts.build_extension_shared_config import build_payload, emit_js
from shared_constants import classify_consent_action


ROOT = Path(__file__).resolve().parents[1]
SHARED_CONFIG = ROOT / "extension" / "lib" / "shared-config.js"


def test_generated_shared_config_matches_python_truth() -> None:
    assert SHARED_CONFIG.read_text(encoding="utf-8") == emit_js(build_payload())


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Accept All", "accept"),
        ("Essential cookies only", "reject"),
        ("Necessary cookies only", "reject"),
        ("Continue without accepting", "reject"),
        ("View options", "settings"),
        ("Manage preferences", "settings"),
        ("Gerir preferências", "settings"),
        ("Tylko niezbędne pliki cookie", "reject"),
        ("Προβολή επιλογών", "settings"),
        ("Endast nödvändiga cookies", "reject"),
        ("Not now", "dismiss"),
    ],
)
def test_shared_python_consent_classifier_covers_production_labels(label: str, expected: str) -> None:
    assert classify_consent_action(label) == expected
