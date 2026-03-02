"""
Run the AECCS pipeline end-to-end with a shared run identifier.

This script provides one reproducible entrypoint for either the mock/demo
dataset or the real study. It writes a run manifest so interrupted runs can
be resumed without guessing which stages already completed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from config import DEFAULT_SOURCE_MODE, PROJECT_ROOT, generate_run_id, get_dataset_layout

STEP_ORDER = [
    "crawl",
    "classify",
    "dark_patterns",
    "score",
    "metrics",
    "pets",
    "dp",
    "cmp",
    "comparison",
    "visualize",
    "report",
]

STEP_DESCRIPTIONS = {
    "crawl": "Populate raw crawl artifacts",
    "classify": "Classify cookies and trackers",
    "dark_patterns": "Detect banner dark patterns",
    "score": "Compute per-site compliance scores",
    "metrics": "Compute aggregate metrics",
    "pets": "Run PET evaluation",
    "dp": "Generate differential privacy report",
    "cmp": "Generate CMP comparison",
    "comparison": "Generate unified PET summary",
    "visualize": "Generate figures",
    "report": "Generate HTML report",
}


def utc_now_iso() -> str:
    """Return a UTC timestamp suitable for the manifest."""
    return datetime.now(timezone.utc).isoformat()


def _module_command(module: str, *extra_args: str) -> list[str]:
    """Build a Python module invocation."""
    return [sys.executable, "-m", module, *extra_args]


def build_step_commands(
    *,
    source_mode: str,
    run_id: str,
    websites_csv: str | None = None,
    headless: bool = True,
    force: bool = False,
    max_sites: int | None = None,
    open_report: bool = False,
) -> dict[str, list[str]]:
    """Build all pipeline commands for the requested source mode."""
    commands: dict[str, list[str]] = {}

    if source_mode == "mock":
        commands["crawl"] = _module_command("tests.generate_mock_data", "--run-id", run_id)
        commands["pets"] = _module_command("tests.generate_mock_pets_data", "--run-id", run_id)
    else:
        crawl_args = ["--source-mode", source_mode, "--run-id", run_id]
        if websites_csv:
            crawl_args.extend(["--csv", websites_csv])
        if not headless:
            crawl_args.append("--no-headless")
        if force:
            crawl_args.append("--force")
        commands["crawl"] = _module_command("scraper.crawler", *crawl_args)

        pet_args = ["--source-mode", source_mode, "--run-id", run_id]
        if websites_csv:
            pet_args.extend(["--websites-csv", websites_csv])
        if max_sites is not None:
            pet_args.extend(["--max-sites", str(max_sites)])
        commands["pets"] = _module_command("pets_evaluation.browser_pets", *pet_args)

    for step, module in (
        ("classify", "analysis.classifier"),
        ("dark_patterns", "dark_patterns.detector"),
        ("score", "analysis.scoring"),
        ("metrics", "analysis.metrics"),
        ("dp", "pets_evaluation.dp_reporting"),
        ("cmp", "pets_evaluation.cmp_analysis"),
        ("comparison", "pets_evaluation.comparison"),
    ):
        commands[step] = _module_command(
            module,
            "--source-mode",
            source_mode,
            "--run-id",
            run_id,
        )

    commands["visualize"] = _module_command(
        "reporting.visualize",
        "--source-mode",
        source_mode,
    )
    report_args = ["--source-mode", source_mode]
    if open_report:
        report_args.append("--open")
    commands["report"] = _module_command("reporting.report_generator", *report_args)

    return commands


def select_steps(
    *,
    step_list: str | None = None,
    from_step: str | None = None,
    to_step: str | None = None,
) -> list[str]:
    """Resolve the ordered list of steps to run."""
    if step_list:
        requested = [step.strip() for step in step_list.split(",") if step.strip()]
        unknown = [step for step in requested if step not in STEP_ORDER]
        if unknown:
            raise ValueError(f"Unknown steps: {', '.join(unknown)}")
        return requested

    start = STEP_ORDER.index(from_step) if from_step else 0
    end = STEP_ORDER.index(to_step) if to_step else len(STEP_ORDER) - 1
    if start > end:
        raise ValueError("--from-step must come before --to-step")
    return STEP_ORDER[start : end + 1]


def _manifest_path(source_mode: str, path_override: str | None = None) -> Path:
    """Return the manifest location for the selected dataset."""
    if path_override:
        return Path(path_override)
    layout = get_dataset_layout(source_mode)
    return layout.processed_dir / "run_manifest.json"


def _load_or_init_manifest(
    *,
    manifest_path: Path,
    source_mode: str,
    run_id: str,
    selected_steps: list[str],
) -> dict:
    """Load an existing manifest or create a new one."""
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("source_mode") != source_mode:
            raise ValueError(
                f"Manifest {manifest_path} is for source_mode={manifest.get('source_mode')!r}, "
                f"not {source_mode!r}"
            )
        if manifest.get("run_id") != run_id:
            raise ValueError(
                f"Manifest {manifest_path} is for run_id={manifest.get('run_id')!r}, not {run_id!r}"
            )
    else:
        manifest = {
            "source_mode": source_mode,
            "run_id": run_id,
            "created_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
            "selected_steps": selected_steps,
            "steps": {},
        }

    for step in selected_steps:
        manifest["steps"].setdefault(
            step,
            {
                "description": STEP_DESCRIPTIONS[step],
                "status": "pending",
                "attempts": 0,
                "command": None,
                "started_at": None,
                "finished_at": None,
                "returncode": None,
                "last_error": None,
            },
        )

    manifest["selected_steps"] = selected_steps
    manifest["updated_at"] = utc_now_iso()
    return manifest


def _write_manifest(manifest_path: Path, manifest: dict) -> None:
    """Persist the manifest to disk."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest["updated_at"] = utc_now_iso()
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def run_pipeline(args: argparse.Namespace) -> int:
    """Execute the requested pipeline run."""
    manifest_path = _manifest_path(args.source_mode, args.manifest_path)

    if args.resume and manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        effective_run_id = args.run_id or existing.get("run_id")
        if effective_run_id is None:
            raise ValueError("Existing manifest has no run_id; pass --run-id explicitly.")
    else:
        prefix = f"{args.source_mode}-pipeline"
        effective_run_id = args.run_id or generate_run_id(prefix)

    selected_steps = select_steps(
        step_list=args.steps,
        from_step=args.from_step,
        to_step=args.to_step,
    )
    commands = build_step_commands(
        source_mode=args.source_mode,
        run_id=effective_run_id,
        websites_csv=args.websites_csv,
        headless=args.headless,
        force=args.force,
        max_sites=args.max_sites,
        open_report=args.open_report,
    )

    manifest = _load_or_init_manifest(
        manifest_path=manifest_path,
        source_mode=args.source_mode,
        run_id=effective_run_id,
        selected_steps=selected_steps,
    )

    if args.dry_run:
        print(f"Run ID: {effective_run_id}")
        print(f"Manifest: {manifest_path}")
        for step in selected_steps:
            print(f"[{step}] {' '.join(commands[step])}")
        return 0

    _write_manifest(manifest_path, manifest)

    for step in selected_steps:
        entry = manifest["steps"][step]
        if args.resume and entry.get("status") == "completed":
            print(f"[SKIP] {step}: already completed in {manifest_path.name}")
            continue

        command = commands[step]
        entry["command"] = command
        entry["status"] = "running"
        entry["started_at"] = utc_now_iso()
        _write_manifest(manifest_path, manifest)

        attempts = 0
        success = False
        last_error = None
        for attempt in range(args.retries + 1):
            attempts += 1
            print(f"\n[{step}] attempt {attempt + 1}/{args.retries + 1}")
            print(" ".join(command))
            result = subprocess.run(command, cwd=str(PROJECT_ROOT), check=False)
            entry["returncode"] = result.returncode
            if result.returncode == 0:
                success = True
                last_error = None
                break
            last_error = f"Command exited with return code {result.returncode}"
            if attempt < args.retries:
                print(f"[RETRY] {step}: {last_error}")

        entry["attempts"] = attempts
        entry["finished_at"] = utc_now_iso()
        entry["last_error"] = last_error
        entry["status"] = "completed" if success else "failed"
        _write_manifest(manifest_path, manifest)

        if not success and not args.continue_on_error:
            print(f"[FAIL] {step}: {last_error}")
            return 1

    print(f"\nPipeline finished. Manifest: {manifest_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(description="Run the AECCS pipeline end-to-end")
    parser.add_argument(
        "--source-mode",
        type=str,
        default=DEFAULT_SOURCE_MODE,
        help="Dataset/output mode to run (default: real). Accepts 'real_N' for batch workflows.",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Shared run identifier to stamp onto all supported stages",
    )
    parser.add_argument(
        "--steps",
        type=str,
        default=None,
        help="Comma-separated subset of steps to run",
    )
    parser.add_argument(
        "--from-step",
        choices=STEP_ORDER,
        default=None,
        help="Start execution from this step",
    )
    parser.add_argument(
        "--to-step",
        choices=STEP_ORDER,
        default=None,
        help="Stop execution after this step",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from the existing manifest and skip already completed steps",
    )
    parser.add_argument(
        "--manifest-path",
        type=str,
        default=None,
        help="Override the default run manifest path",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=0,
        help="Retry each failed stage this many additional times",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue to later stages even if an earlier stage fails",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned commands without executing them",
    )
    parser.add_argument(
        "--websites-csv",
        type=str,
        default=None,
        help="Override the websites CSV for crawl and PET stages",
    )
    parser.add_argument(
        "--max-sites",
        type=int,
        default=None,
        help="Limit the PET evaluation to the first N sites in real mode",
    )
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Pass headless mode through to the real crawler",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force the real crawler to overwrite existing raw outputs",
    )
    parser.add_argument(
        "--open-report",
        action="store_true",
        help="Open the generated report after the final report stage",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(run_pipeline(args))


if __name__ == "__main__":
    main()
