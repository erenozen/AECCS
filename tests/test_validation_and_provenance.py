from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pandas as pd
import pytest
from bs4 import BeautifulSoup

from analysis.classifier import classify_cookie
from analysis.scoring import compute_compliance_score, run_scoring
from dark_patterns.detector import (
    detect_asymmetric_buttons,
    detect_confusing_language,
    detect_forced_action,
    detect_hidden_reject,
    detect_missing_reject,
    detect_multi_layer_rejection,
    detect_preselected_checkboxes,
)
from pets_evaluation.browser_pets import run_pet_evaluation
from pets_evaluation.cmp_analysis import run_cmp_analysis
from pets_evaluation.comparison import run_comparison
from reporting.report_generator import generate_html_report


def test_classify_cookie_marks_known_tracker_from_tracker_map() -> None:
    filter_data = {
        "tracker_domain_map": {
            "doubleclick.net": {"vendor": "Google", "category": "Advertising"},
        },
        "easyprivacy_domains": set(),
        "easylist_domains": set(),
    }
    cookie = {
        "name": "IDE",
        "domain": ".doubleclick.net",
        "expires": 9_999_999_999,
    }

    result = classify_cookie(cookie, filter_data, "example.com")

    assert result["is_tracker"] is True
    assert result["vendor"] == "Google"
    assert result["category"] == "Advertising"
    assert result["is_third_party"] is True


def test_dark_pattern_detectors_flag_expected_patterns() -> None:
    soup = BeautifulSoup(
        """
        <div class="cookie-wall" role="dialog" style="position: fixed; width: 100%; height: 100%;">
          <p>Keep the site free. Continue for the best experience.</p>
          <input type="checkbox" checked>
          <button>Continue</button>
        </div>
        """,
        "html.parser",
    )
    site_data = {
        "consent_banner": {
            "has_reject_button": False,
            "accept_clicks_required": 1,
            "reject_clicks_required": 3,
            "buttons": [
                {
                    "type": "accept",
                    "text": "Accept All",
                    "computed_styles": {
                        "width": "240px",
                        "height": "48px",
                        "font_size": "16px",
                        "font_weight": "700",
                        "background_color": "#00ff00",
                        "color": "#ffffff",
                        "display": "block",
                        "visibility": "visible",
                    },
                },
                {
                    "type": "reject",
                    "text": "Reject All",
                    "computed_styles": {
                        "width": "100px",
                        "height": "24px",
                        "font_size": "10px",
                        "font_weight": "300",
                        "background_color": "#f0f0f0",
                        "color": "#f5f5f5",
                        "display": "none",
                        "visibility": "hidden",
                    },
                },
            ],
        }
    }

    assert detect_asymmetric_buttons(soup, site_data)["detected"] is True
    assert detect_hidden_reject(soup, site_data)["detected"] is True
    assert detect_missing_reject(site_data)["detected"] is True
    assert detect_preselected_checkboxes(soup)["detected"] is True
    assert detect_forced_action(soup, site_data)["detected"] is True
    assert detect_multi_layer_rejection(site_data)["detected"] is True
    assert detect_confusing_language(soup)["detected"] is True


def test_compute_compliance_score_handles_compliant_and_no_banner_cases() -> None:
    compliant_site = {
        "domain": "good.example",
        "category": "Government",
        "pre_consent": {"cookies": [], "third_party_domains": [], "total_cookies": 0},
        "post_consent_accept": {"third_party_domains": ["doubleclick.net"]},
        "post_consent_reject": {
            "third_party_domains": [],
            "new_third_party_domains_after_interaction": [],
            "new_cookies_after_interaction": [],
            "reject_successful": True,
            "reject_button_found": True,
        },
        "consent_banner": {
            "found": True,
            "has_reject_button": True,
            "accept_clicks_required": 1,
            "reject_clicks_required": 1,
            "text_content": "Analytics cookies. Google vendor. Privacy policy.",
            "html": "<a>privacy policy</a>",
        },
    }
    compliant_dp = {"dark_pattern_count": 0, "dark_patterns_detected": []}

    result = compute_compliance_score(compliant_site, compliant_dp, [])
    assert result["grade"] == "A"
    assert result["criterion_scores"]["no_pre_consent_trackers"]["score"] == 100
    assert result["criterion_scores"]["reject_option_available"]["score"] == 100

    no_banner_site = {
        "domain": "nobanner.example",
        "category": "News",
        "pre_consent": {"cookies": [], "third_party_domains": [], "total_cookies": 0},
        "consent_banner": None,
    }
    no_banner_result = compute_compliance_score(no_banner_site, compliant_dp, [])
    assert no_banner_result["criterion_scores"]["reject_option_available"]["score"] == 0
    assert no_banner_result["criterion_scores"]["post_reject_compliance"]["score"] == 0


def test_run_scoring_skips_failed_crawl_fixture(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    raw_dir.mkdir()
    processed_dir.mkdir()

    failed_site = {
        "domain": "failed.example",
        "category": "News",
        "region": "EU",
        "rank": 1,
        "success": False,
        "error": "navigation failed",
        "source_mode": "real",
        "run_id": "testrun",
    }
    (raw_dir / "failed.example.json").write_text(json.dumps(failed_site), encoding="utf-8")

    run_scoring(
        raw_dir=str(raw_dir),
        processed_dir=str(processed_dir),
        source_mode="real",
        output_path=str(processed_dir / "scores.csv"),
    )

    assert not (processed_dir / "scores.csv").exists()


def test_pet_runner_marks_unavailable_extension_as_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_csv = tmp_path / "pets_effectiveness.csv"
    monkeypatch.setattr(
        "pets_evaluation.browser_pets.setup_pet_extensions",
        lambda: {
            "ublock-origin": None,
            "privacy-badger": None,
            "consent-o-matic": None,
        },
    )

    asyncio.run(
        run_pet_evaluation(
            domain="example.com",
            pets=["ublock_origin"],
            output_path=str(output_csv),
            source_mode="mock",
            run_id="pet-test",
        )
    )

    df = pd.read_csv(output_csv)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["pet_name"] == "ublock_origin"
    assert bool(row["success"]) is False
    assert "SKIPPED" in row["error"]
    assert row["source_mode"] == "mock"
    assert row["run_id"] == "pet-test"


def test_report_generator_rejects_mixed_source_modes(tmp_path: Path) -> None:
    processed_dir = tmp_path / "processed"
    figures_dir = tmp_path / "figures"
    processed_dir.mkdir()
    figures_dir.mkdir()

    (processed_dir / "aggregate_metrics.json").write_text(
        json.dumps({"source_mode": "mock", "summary": {}}),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "domain": "example.com",
                "source_mode": "real",
                "run_id": "run-1",
                "overall_score": 50,
                "grade": "C",
            }
        ]
    ).to_csv(processed_dir / "compliance_scores.csv", index=False)

    with pytest.raises(ValueError, match="Mixed processed inputs detected"):
        generate_html_report(
            processed_dir=str(processed_dir),
            figures_dir=str(figures_dir),
            output_path=str(tmp_path / "report.html"),
            source_mode="real",
        )


def test_cmp_analysis_propagates_inferred_run_id(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    raw_dir.mkdir()
    processed_dir.mkdir()

    raw_doc = {
        "domain": "cmp.example",
        "success": True,
        "cmp_detected": "OneTrust",
        "source_mode": "mock",
        "run_id": "study-run",
        "site_list_source": "data/websites.csv",
        "pre_consent": {"third_party_domains": ["ads.example"]},
        "post_consent_reject": {"third_party_domains": []},
        "consent_banner": {"has_reject_button": True, "reject_clicks_required": 1},
    }
    (raw_dir / "cmp.example.json").write_text(json.dumps(raw_doc), encoding="utf-8")
    pd.DataFrame(
        [
            {
                "domain": "cmp.example",
                "source_mode": "mock",
                "run_id": "study-run",
                "overall_score": 77.5,
                "grade": "B",
            }
        ]
    ).to_csv(processed_dir / "compliance_scores.csv", index=False)

    run_cmp_analysis(
        raw_dir=str(raw_dir),
        processed_dir=str(processed_dir),
        source_mode="mock",
    )

    cmp_df = pd.read_csv(processed_dir / "cmp_comparison.csv")
    detailed = json.loads((processed_dir / "cmp_comparison_detailed.json").read_text(encoding="utf-8"))

    assert cmp_df["run_id"].tolist() == ["study-run"]
    assert detailed["run_id"] == "study-run"
    assert detailed["site_list_source"] == "data/websites.csv"


def test_comparison_propagates_upstream_provenance(tmp_path: Path) -> None:
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()

    pd.DataFrame(
        [
            {
                "domain": "example.com",
                "source_mode": "mock",
                "run_id": "study-run",
                "category": "News",
                "pet_name": "baseline",
                "measurement_mode": "real",
                "browser_name": "chromium",
                "browser_version": "1",
                "extension_name": "",
                "extension_version": "",
                "extension_path": "",
                "extension_enabled": False,
                "consent_banner_detected": True,
                "page_load_time_ms": 1000,
                "total_cookies": 5,
                "tracker_cookies": 2,
                "tracker_domains": 2,
                "total_third_party_domains": 2,
                "total_requests": 10,
                "blocked_requests": 0,
                "success": True,
                "error": "",
            },
            {
                "domain": "example.com",
                "source_mode": "mock",
                "run_id": "study-run",
                "category": "News",
                "pet_name": "brave_shields",
                "measurement_mode": "simulated",
                "browser_name": "chromium",
                "browser_version": "1",
                "extension_name": "",
                "extension_version": "",
                "extension_path": "",
                "extension_enabled": False,
                "consent_banner_detected": False,
                "page_load_time_ms": 900,
                "total_cookies": 1,
                "tracker_cookies": 0,
                "tracker_domains": 0,
                "total_third_party_domains": 0,
                "total_requests": 7,
                "blocked_requests": 3,
                "success": True,
                "error": "",
            },
        ]
    ).to_csv(processed_dir / "pets_effectiveness.csv", index=False)
    (processed_dir / "dp_aggregate_metrics.json").write_text(
        json.dumps(
            {
                "source_mode": "mock",
                "run_id": "study-run",
                "site_list_source": "data/websites.csv",
                "metadata": {"recommended_epsilon": 2.0, "epsilons_tested": [2.0], "trials_per_epsilon": 10},
                "privacy_utility_tradeoff": {},
            }
        ),
        encoding="utf-8",
    )
    (processed_dir / "cmp_comparison_detailed.json").write_text(
        json.dumps(
            {
                "source_mode": "mock",
                "run_id": "study-run",
                "site_list_source": "data/websites.csv",
                "rankings": [{"cmp": "OneTrust", "pet_score": 70.0, "rank": 1}],
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "source_mode": "mock",
                "run_id": "study-run",
                "cmp_name": "OneTrust",
                "site_count": 1,
                "avg_compliance_score": 70.0,
                "median_compliance_score": 70.0,
                "pct_with_reject_button": 100.0,
                "pct_reject_works": 100.0,
                "avg_tracker_reduction": 0.5,
                "pct_with_dark_patterns": 0.0,
                "pet_score": 70.0,
                "rank": 1,
            }
        ]
    ).to_csv(processed_dir / "cmp_comparison.csv", index=False)

    run_comparison(processed_dir=str(processed_dir), source_mode="mock")

    summary = json.loads((processed_dir / "pets_summary.json").read_text(encoding="utf-8"))
    assert summary["run_id"] == "study-run"
    assert summary["site_list_source"] == "data/websites.csv"
