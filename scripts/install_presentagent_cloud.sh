#!/usr/bin/env bash
set -euo pipefail

DATA_ROOT="${DATA_ROOT:-/ai/data/textbook-to-video}"
TOOLS_ROOT="${TOOLS_ROOT:-/ai/data/tools}"
T2V_REPO="${T2V_REPO:-/ai/data/repos/Textbook-to-Video}"
PRESENTAGENT_REPO="${PRESENTAGENT_REPO:-/ai/data/repos/PresentAgent}"
PY_RUNTIME="${PY_RUNTIME:-$TOOLS_ROOT/envs/presentagent-py311-runtime}"
VENV="${VENV:-$TOOLS_ROOT/envs/presentagent}"
UPLOADS="${UPLOADS:-$DATA_ROOT/uploads}"

PYTHON_TAR="$UPLOADS/cpython-3.11.13+20250610-x86_64-unknown-linux-gnu-install_only.tar.gz"
TIKTOKEN_CACHE="$TOOLS_ROOT/tiktoken-cache"
WHEELHOUSE_ROOT="$TOOLS_ROOT/wheelhouse"

require_file() {
  if [ ! -f "$1" ]; then
    echo "Missing file: $1" >&2
    exit 1
  fi
}

require_dir() {
  if [ ! -d "$1" ]; then
    echo "Missing directory: $1" >&2
    exit 1
  fi
}

require_file "$PYTHON_TAR"
require_dir "$T2V_REPO"

if [ ! -d "$PRESENTAGENT_REPO" ] && [ -f "$UPLOADS/PresentAgent-repo-b9990e9.tar.gz" ]; then
  echo "Extracting PresentAgent repo..."
  mkdir -p "$(dirname "$PRESENTAGENT_REPO")"
  tmp_repo="$(mktemp -d)"
  tar -xzf "$UPLOADS/PresentAgent-repo-b9990e9.tar.gz" -C "$tmp_repo"
  extracted="$(find "$tmp_repo" -maxdepth 1 -type d -name 'presentagent-repo-build' -o -name 'PresentAgent' | head -n 1)"
  if [ -z "$extracted" ]; then
    echo "PresentAgent repo archive has unexpected layout." >&2
    exit 1
  fi
  rm -rf "$PRESENTAGENT_REPO"
  mv "$extracted" "$PRESENTAGENT_REPO"
  rm -rf "$tmp_repo"
fi

require_dir "$PRESENTAGENT_REPO"

mkdir -p "$TOOLS_ROOT/envs" "$WHEELHOUSE_ROOT" "$TIKTOKEN_CACHE"

if [ ! -x "$PY_RUNTIME/bin/python3.11" ]; then
  echo "Extracting Python 3.11 runtime..."
  rm -rf "$PY_RUNTIME"
  mkdir -p "$PY_RUNTIME"
  tar -xzf "$PYTHON_TAR" -C "$PY_RUNTIME" --strip-components=1
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "Creating PresentAgent venv..."
  "$PY_RUNTIME/bin/python3.11" -m venv "$VENV"
fi

extract_wheelhouse() {
  local tar_name="$1"
  local target_name="$2"
  local tar_path="$UPLOADS/$tar_name"
  local target="$WHEELHOUSE_ROOT/$target_name"
  if [ -f "$tar_path" ]; then
    rm -rf "$target"
    mkdir -p "$target"
    tar -xzf "$tar_path" -C "$target" --strip-components=1
  fi
}

extract_wheelhouse "PresentAgent-wheelhouse-core-py311-linux.tar.gz" "presentagent-core-py311"
extract_wheelhouse "PresentAgent-wheelhouse-torch-py311-linux.tar.gz" "presentagent-torch-py311"
extract_wheelhouse "PresentAgent-wheelhouse-marker-py311-linux.tar.gz" "presentagent-marker-py311"
extract_wheelhouse "PresentAgent-wheelhouse-remaining-py311-linux.tar.gz" "presentagent-remaining-py311"

if [ -f "$UPLOADS/PresentAgent-MegaTTS3-checkpoints.tar.gz" ]; then
  echo "Installing MegaTTS3 checkpoints..."
  megatts_ckpt="$PRESENTAGENT_REPO/presentagent/MegaTTS3/checkpoints"
  rm -rf "$megatts_ckpt"
  mkdir -p "$megatts_ckpt"
  tar -xzf "$UPLOADS/PresentAgent-MegaTTS3-checkpoints.tar.gz" -C "$megatts_ckpt" --strip-components=1
fi

if [ -f "$UPLOADS/o200k_base_cache" ]; then
  cp "$UPLOADS/o200k_base_cache" "$TIKTOKEN_CACHE/fb374d419588a4632f3f557e76b4b70aebbca790"
fi

if [ -f "$UPLOADS/LibreOffice_25.8.7_Linux_x86-64_deb.tar.gz" ] && [ ! -x "$TOOLS_ROOT/libreoffice/program/soffice" ]; then
  echo "Installing LibreOffice under $TOOLS_ROOT/libreoffice ..."
  tmpdir="$(mktemp -d)"
  tar -xzf "$UPLOADS/LibreOffice_25.8.7_Linux_x86-64_deb.tar.gz" -C "$tmpdir"
  mkdir -p "$TOOLS_ROOT/libreoffice-debs" "$TOOLS_ROOT/libreoffice"
  find "$tmpdir" -name '*.deb' -exec dpkg-deb -x {} "$TOOLS_ROOT/libreoffice-debs" \;
  lo_dir="$(find "$TOOLS_ROOT/libreoffice-debs/opt" -maxdepth 1 -type d -name 'libreoffice*' | head -n 1)"
  if [ -z "$lo_dir" ]; then
    echo "LibreOffice extraction failed: no /opt/libreoffice* directory found." >&2
    exit 1
  fi
  rm -rf "$TOOLS_ROOT/libreoffice"
  mv "$lo_dir" "$TOOLS_ROOT/libreoffice"
  rm -rf "$tmpdir"
fi

FIND_LINKS=(
  "$WHEELHOUSE_ROOT/presentagent-core-py311"
  "$WHEELHOUSE_ROOT/presentagent-torch-py311"
  "$WHEELHOUSE_ROOT/presentagent-marker-py311"
  "$WHEELHOUSE_ROOT/presentagent-remaining-py311"
  "$WHEELHOUSE_ROOT/t2v-py311"
)

PIP_FIND_ARGS=()
for link in "${FIND_LINKS[@]}"; do
  [ -d "$link" ] && PIP_FIND_ARGS+=(--find-links "$link")
done

"$VENV/bin/pip" install --no-index "${PIP_FIND_ARGS[@]}" wheel
"$VENV/bin/pip" install --no-index "${PIP_FIND_ARGS[@]}" \
  "torch==2.6.0+cpu" "torchvision==0.21.0+cpu" \
  "numpy==1.26.4" "pillow==10.4.0" "regex==2024.11.6" \
  "tokenizers==0.21.4" "huggingface-hub==0.36.2" \
  "transformers==4.49.0" "peft==0.15.2" \
  "WeTextProcessing==1.0.3" "pynini==2.1.5"
"$VENV/bin/pip" install --no-index "${PIP_FIND_ARGS[@]}" -r "$T2V_REPO/presentagent-requirements-offline.txt" || true
"$VENV/bin/pip" install --no-index "${PIP_FIND_ARGS[@]}" numba llvmlite more-itertools triton || true
"$VENV/bin/pip" install --no-index --no-build-isolation --no-deps "${PIP_FIND_ARGS[@]}" openai-whisper || true
"$VENV/bin/pip" install --no-index --no-deps "${PIP_FIND_ARGS[@]}" marker-pdf peft timm uvicorn setproctitle librosa modelscope x-transformers torchdiffeq openai-whisper gradio WeTextProcessing || true
"$VENV/bin/pip" check || true

set -a
source "$T2V_REPO/.env"
set +a
export TIKTOKEN_CACHE_DIR="$TIKTOKEN_CACHE"
export PYTHONPATH="$PRESENTAGENT_REPO:${PYTHONPATH:-}"
export OPENAI_API_KEY="${ECNU_API_KEY:-${OPENAI_API_KEY:-}}"
export API_BASE="${ECNU_BASE_URL:-${API_BASE:-}}"
export LANGUAGE_MODEL="${ECNU_DEFAULT_MODEL:-ecnu-plus}"
export VISION_MODEL="${ECNU_DEFAULT_MODEL:-ecnu-plus}"
export TEXT_MODEL="${ECNU_DEFAULT_MODEL:-ecnu-plus}"
export PATH="$TOOLS_ROOT/libreoffice/program:$TOOLS_ROOT/bin:$PATH"

cd "$PRESENTAGENT_REPO"
"$VENV/bin/python" "$DATA_ROOT/experiments/presentagent-comparison-v1/check_presentagent_imports.py"

echo "soffice: $(command -v soffice || true)"
echo "ffmpeg: $(command -v ffmpeg || true)"
echo "PresentAgent install check finished."
