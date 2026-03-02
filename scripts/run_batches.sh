#!/usr/bin/env bash
#
# AECCS 1000-Site Batch Workflow
#
# Runs 10 batches of 100 websites each, merges results, and runs global analysis.
#
# Usage:
#   ./scripts/run_batches.sh              # Run all batches 0-9
#   ./scripts/run_batches.sh 0 2          # Run batches 0, 1, 2 only
#   ./scripts/run_batches.sh merge        # Only merge + global analysis
#
set -euo pipefail
cd "$(dirname "$0")/.."

BATCH_START=${1:-0}
BATCH_END=${2:-9}

# Mapping: batch N uses websites_(N+1).csv
csv_for_batch() {
    echo "data/websites_$(( $1 + 1 )).csv"
}

# ── Phase 1: Per-batch crawl + analysis ──────────────────────────────────────
if [ "${1:-}" != "merge" ]; then
    for N in $(seq "$BATCH_START" "$BATCH_END"); do
        CSV=$(csv_for_batch "$N")
        if [ ! -f "$CSV" ]; then
            echo "[ERROR] Missing $CSV for batch $N — skipping"
            continue
        fi
        echo ""
        echo "================================================================"
        echo "  BATCH $N: $CSV → data/real_${N}/"
        echo "================================================================"
        python -m scripts.run_pipeline \
            --source-mode "real_${N}" \
            --websites-csv "$CSV" \
            --steps crawl,classify,dark_patterns,score \
            --force \
            --run-id "batch-${N}" \
            --continue-on-error
    done
fi

# ── Phase 2: Merge all batches ───────────────────────────────────────────────
echo ""
echo "================================================================"
echo "  MERGING BATCHES → data/real_combined/"
echo "================================================================"
python -m scripts.merge_batches \
    --batch-range "$BATCH_START" "$BATCH_END" \
    --output real_combined

# ── Phase 3: Global analysis on combined data ────────────────────────────────
echo ""
echo "================================================================"
echo "  GLOBAL ANALYSIS ON COMBINED DATA"
echo "================================================================"
python -m scripts.run_pipeline \
    --source-mode real_combined \
    --websites-csv data/websites_combined.csv \
    --steps metrics,pets,dp,cmp,comparison,visualize,report \
    --run-id combined-1000 \
    --continue-on-error

echo ""
echo "================================================================"
echo "  ALL DONE — Results in data/real_combined/"
echo "================================================================"
