#!/bin/bash
# Verify each layout preset by running Isaac Sim against its test config,
# then collecting the spawn-count log line and a representative screenshot.
#
# Usage:
#   scripts/verify_layouts.sh                     # all 14 layouts, 20 frames
#   scripts/verify_layouts.sh --frames 40         # all layouts, 40 frames
#   scripts/verify_layouts.sh narrow_aisle storage_yard
#   scripts/verify_layouts.sh --out /tmp/runs
#
# Output structure:
#   <OUT>/
#     summary.csv                  one row per layout with spawn counts
#     <layout>.log                 full stdout/stderr from the Isaac run
#     <layout>_first.png           first rendered frame
#     <layout>_dataset/            full /tmp/dataset copy (frames + COCO)
#
# Each Isaac Sim run loads the warehouse, generates the layout, captures
# `--frames` frames, then exits. Runs are sequential (Isaac Sim doesn't
# parallelize cleanly inside one container).

set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ISAAC_PY="/isaac-sim/python.sh"
DEFAULT_FRAMES=20
DEFAULT_OUT="$PROJECT_ROOT/verify_results/$(date +%Y%m%d_%H%M%S)"

ALL_LAYOUTS=(
    standard_warehouse
    narrow_aisle
    open_floor
    cross_dock
    cold_storage
    loading_dock
    maintenance_bay
    storage_yard
    emergency_egress
    hazmat_storage
    high_density_storage
    pedestrian_crossing
    receiving_dock
)

frames="$DEFAULT_FRAMES"
out_dir="$DEFAULT_OUT"
layouts=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --frames) frames="$2"; shift 2 ;;
        --out)    out_dir="$2"; shift 2 ;;
        -h|--help)
            grep -E '^# ' "$0" | sed 's/^# //'
            exit 0
            ;;
        *) layouts+=("$1"); shift ;;
    esac
done

if [[ ${#layouts[@]} -eq 0 ]]; then
    layouts=("${ALL_LAYOUTS[@]}")
fi

if [[ ! -x "$ISAAC_PY" ]]; then
    echo "[ERROR] Isaac Sim launcher not found at $ISAAC_PY"
    exit 1
fi

mkdir -p "$out_dir"
summary="$out_dir/summary.csv"
echo "layout,exit_code,racks,shelf_items,pallets,clutter,dock_items,bulk,stripes,guards,charge,rack_extras,wall_extras,realism,wear,main_aisle,marshal,human,mid_fork,doors,polish,floor_fill,realism_layer,realism_layer_2,atmosphere,crosswalk,first_frame" > "$summary"

# Extract numeric values from the canonical spawn-summary line, e.g.:
#   [INFO] Spawned 12 racks, 84 shelf items, 0 pallets, 50 clutter props, ...
extract_field() {
    local log="$1"; local field="$2"
    grep -E '^\[INFO\] Spawned' "$log" | tail -1 \
        | grep -oE "[0-9]+ ${field}" | head -1 | awk '{print $1}'
}

for layout in "${layouts[@]}"; do
    cfg="$PROJECT_ROOT/configs/test_layouts/${layout}.json"
    if [[ ! -f "$cfg" ]]; then
        echo "[SKIP] No test config for $layout (expected $cfg)"
        continue
    fi

    echo "================================================================"
    echo "[$(date +%H:%M:%S)] Running $layout (frames=$frames)"
    echo "================================================================"

    rm -rf /tmp/dataset
    log_file="$out_dir/${layout}.log"

    "$ISAAC_PY" "$PROJECT_ROOT/isaac_backend/main.py" \
        --config "$cfg" \
        --library "$PROJECT_ROOT/assets/library.json" \
        --frames "$frames" \
        > "$log_file" 2>&1
    exit_code=$?

    racks=$(extract_field "$log_file" "racks")
    shelf=$(extract_field "$log_file" "shelf items")
    pallets=$(extract_field "$log_file" "pallets")
    clutter=$(extract_field "$log_file" "clutter props")
    dock=$(extract_field "$log_file" "dock items")
    bulk=$(extract_field "$log_file" "bulk-stock items")
    stripes=$(extract_field "$log_file" "floor stripes")
    guards=$(extract_field "$log_file" "column guards")
    charge=$(extract_field "$log_file" "charge-bay items")
    rext=$(extract_field "$log_file" "rack-end details")
    wext=$(extract_field "$log_file" "wall details")
    realism=$(extract_field "$log_file" "realism extras")
    wear=$(extract_field "$log_file" "aisle wear")
    main_aisle=$(extract_field "$log_file" "main-aisle treatment")
    marshal=$(extract_field "$log_file" "marshalling-band items")
    human=$(extract_field "$log_file" "human-imperfection items")
    mid_fork=$(extract_field "$log_file" "mid-aisle forklift")
    doors=$(extract_field "$log_file" "dock doors")
    polish=$(extract_field "$log_file" "polish-pass items")
    floor_fill=$(extract_field "$log_file" "floor-fill staging items")
    rl1=$(extract_field "$log_file" "realism-layer items")
    rl2=$(extract_field "$log_file" "realism-layer-2 items")
    atmo=$(extract_field "$log_file" "atmosphere-clutter items")
    crosswalk=$(extract_field "$log_file" "crosswalk-paint stripes")

    first_frame=""
    first_src=$(ls /tmp/dataset/Replicator/rgb_*.png 2>/dev/null | head -1)
    if [[ -n "$first_src" ]]; then
        first_frame="${layout}_first.png"
        cp "$first_src" "$out_dir/$first_frame"
    fi

    if [[ -d /tmp/dataset ]]; then
        cp -r /tmp/dataset "$out_dir/${layout}_dataset"
    fi

    echo "$layout,$exit_code,${racks:-},${shelf:-},${pallets:-},${clutter:-},${dock:-},${bulk:-},${stripes:-},${guards:-},${charge:-},${rext:-},${wext:-},${realism:-},${wear:-},${main_aisle:-},${marshal:-},${human:-},${mid_fork:-},${doors:-},${polish:-},${floor_fill:-},${rl1:-},${rl2:-},${atmo:-},${crosswalk:-},$first_frame" >> "$summary"

    echo "[DONE] $layout exit=$exit_code  racks=${racks:-?}  realism=${realism:-?}  rl1=${rl1:-?}  rl2=${rl2:-?}  atmo=${atmo:-?}"
done

echo
echo "================================================================"
echo "Summary: $summary"
echo "================================================================"
column -ts, -L "$summary" 2>/dev/null || cat "$summary"
