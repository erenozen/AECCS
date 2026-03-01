from __future__ import annotations

import sys

from scripts.run_pipeline import STEP_ORDER, build_step_commands, select_steps


def test_build_step_commands_mock_uses_shared_run_id() -> None:
    commands = build_step_commands(source_mode="mock", run_id="shared-run")

    assert commands["crawl"] == [
        sys.executable,
        "-m",
        "tests.generate_mock_data",
        "--run-id",
        "shared-run",
    ]
    assert commands["pets"] == [
        sys.executable,
        "-m",
        "tests.generate_mock_pets_data",
        "--run-id",
        "shared-run",
    ]
    assert commands["classify"][-4:] == ["--source-mode", "mock", "--run-id", "shared-run"]
    assert commands["cmp"][-4:] == ["--source-mode", "mock", "--run-id", "shared-run"]


def test_build_step_commands_real_supports_overrides() -> None:
    commands = build_step_commands(
        source_mode="real",
        run_id="real-run",
        websites_csv="custom.csv",
        headless=False,
        force=True,
        max_sites=12,
    )

    crawl = commands["crawl"]
    pets = commands["pets"]

    assert crawl[:3] == [sys.executable, "-m", "scraper.crawler"]
    assert crawl[3:7] == ["--source-mode", "real", "--run-id", "real-run"]
    assert "--csv" in crawl
    assert "custom.csv" in crawl
    assert "--no-headless" in crawl
    assert "--force" in crawl

    assert pets[:3] == [sys.executable, "-m", "pets_evaluation.browser_pets"]
    assert pets[3:7] == ["--source-mode", "real", "--run-id", "real-run"]
    assert "--max-sites" in pets
    assert "--websites-csv" in pets
    assert pets[-4:] == ["--websites-csv", "custom.csv", "--max-sites", "12"]


def test_select_steps_supports_range_selection() -> None:
    selected = select_steps(from_step="metrics", to_step="report")
    assert selected == STEP_ORDER[4:]


def test_select_steps_supports_explicit_subset() -> None:
    assert select_steps(step_list="crawl,score,report") == ["crawl", "score", "report"]
