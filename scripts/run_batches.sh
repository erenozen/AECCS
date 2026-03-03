#!/usr/bin/env bash
#
# AECCS 1000-Site Batch Workflow
#
# Usage:
#   ./scripts/run_batches.sh 0              # Run batch 0 only (websites_1.csv → real_0/)
#   ./scripts/run_batches.sh 3              # Run batch 3 only (websites_4.csv → real_3/)
#   ./scripts/run_batches.sh 0 9            # Run batches 0 through 9
#   ./scripts/run_batches.sh all            # Run all batches 0-9
#   ./scripts/run_batches.sh merge          # Merge all batches + run global analysis
#
set -euo pipefail
cd "$(dirname "$0")/.."

# Mapping: batch N uses websites_(N+1).csv
csv_for_batch() {
    echo "data/websites_$(( $1 + 1 )).csv"
}

run_batch() {
    local N=$1
    local CSV
    CSV=$(csv_for_batch "$N")
    if [ ! -f "$CSV" ]; then
        echo "[ERROR] Missing $CSV for batch $N — skipping"
        return 1
    fi
    echo ""
    echo "================================================================"
    echo "  BATCH $N: $CSV → data/real_${N}/"
    echo "================================================================"
    python -m scripts.run_pipeline \
        --source-mode "real_${N}" \
        --websites-csv "$CSV" \
        --steps crawl,classify,dark_patterns,score,pets \
        --force \
        --run-id "batch-${N}" \
        --continue-on-error
}

run_merge() {
    echo ""
    echo "================================================================"
    echo "  MERGING BATCHES 0-9 → data/real_combined/"
    echo "================================================================"
    python -m scripts.merge_batches \
        --batch-range 0 9 \
        --output real_combined

    echo ""
    echo "================================================================"
    echo "  GLOBAL ANALYSIS ON COMBINED DATA"
    echo "================================================================"
    python -m scripts.run_pipeline \
        --source-mode real_combined \
        --websites-csv data/websites_combined.csv \
        --steps metrics,dp,cmp,comparison,visualize,report \
        --run-id combined-1000 \
        --continue-on-error

    echo ""
    echo "================================================================"
    echo "  ALL DONE — Results in data/real_combined/"
    echo "================================================================"
}

# ── Parse arguments ──────────────────────────────────────────────────────────
case "${1:-all}" in
    merge)
        run_merge
        ;;
    all)
        for N in $(seq 0 9); do
            run_batch "$N"
        done
        run_merge
        ;;
    *)
        BATCH_START=$1
        BATCH_END=${2:-$1}  # If only one arg, run just that batch
        for N in $(seq "$BATCH_START" "$BATCH_END"); do
            run_batch "$N"
        done
        ;;
esac
