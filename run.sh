#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "============================================================"
echo " Fabric Business Documentation Agent"
echo "============================================================"
echo

# ── 1. Check uv ──────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    echo "[ERROR] uv not found. Install it from https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

# ── 2. Read provider and model from .env (defaults if not set) ──
LLM_PROVIDER="anthropic"
LLM_MODEL=""

if [[ -f ".env" ]]; then
    while IFS='=' read -r key value; do
        [[ "$key" == "LLM_PROVIDER" ]] && LLM_PROVIDER="$value"
        [[ "$key" == "LLM_MODEL" ]]    && LLM_MODEL="$value"
    done < <(grep -E "^LLM_PROVIDER=|^LLM_MODEL=" .env)
fi

echo " Provider : $LLM_PROVIDER"
echo " Model    : ${LLM_MODEL:-"(provider default)"}"
echo

# ── 3. Sync dependencies ──────────────────────────────────────
echo "[1/3] Syncing dependencies..."
uv sync -q
echo "      Done."
echo

# ── 4. Resolve source and output dirs ────────────────────────
SRC_DIR="${1:-src}"
OUT_DIR="${2:-output}"

if [[ ! -d "$SRC_DIR" ]]; then
    echo "[ERROR] Source directory \"$SRC_DIR\" does not exist."
    echo "        Usage: ./run.sh [src_dir] [output_dir]"
    exit 1
fi

# ── 5. Run the agent ─────────────────────────────────────────
echo "[2/3] Scanning \"$SRC_DIR\" for pipelines, notebooks, and dataflows..."
echo "      Output will be written to \"$OUT_DIR\""
echo

uv run agent --src "$SRC_DIR" --output "$OUT_DIR"

# ── 6. Open output folder (best-effort, platform-aware) ──────
echo
echo "[3/3] Opening output folder..."
if command -v xdg-open &>/dev/null; then
    xdg-open "$OUT_DIR" &
elif command -v open &>/dev/null; then
    open "$OUT_DIR"
fi

echo
echo "============================================================"
echo " Done. Documentation written to: $OUT_DIR"
echo "============================================================"
