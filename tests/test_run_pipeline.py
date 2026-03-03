from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.run_pipeline import STEP_ORDER, build_step_commands, run_pipeline, select_steps


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


def _pipeline_args(manifest_path: Path, *, continue_on_error: bool) -> argparse.Namespace:
    return argparse.Namespace(
        source_mode="mock",
        run_id="shared-run",
        steps="crawl,pets",
        from_step=None,
        to_step=None,
        resume=False,
        manifest_path=str(manifest_path),
        retries=0,
        continue_on_error=continue_on_error,
        dry_run=False,
        websites_csv=None,
        max_sites=None,
        headless=True,
        force=False,
        open_report=False,
    )


def test_run_pipeline_returns_nonzero_when_any_step_fails_with_continue_on_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "run_manifest.json"

    def fake_run(command: list[str], cwd: str, check: bool) -> subprocess.CompletedProcess[str]:
        module = command[2]
        return subprocess.CompletedProcess(command, 1 if module == "tests.generate_mock_data" else 0)

    monkeypatch.setattr("scripts.run_pipeline.subprocess.run", fake_run)

    result = run_pipeline(_pipeline_args(manifest_path, continue_on_error=True))

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result == 1
    assert manifest["steps"]["crawl"]["status"] == "failed"
    assert manifest["steps"]["pets"]["status"] == "completed"


def test_run_pipeline_returns_zero_when_all_steps_succeed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "run_manifest.json"

    def fake_run(command: list[str], cwd: str, check: bool) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("scripts.run_pipeline.subprocess.run", fake_run)

    result = run_pipeline(_pipeline_args(manifest_path, continue_on_error=True))

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result == 0
    assert manifest["steps"]["crawl"]["status"] == "completed"
    assert manifest["steps"]["pets"]["status"] == "completed"
