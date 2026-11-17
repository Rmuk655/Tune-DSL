#!/usr/bin/env bash
# Setup for Ubuntu/WSL: g++ (C++ backend), optional MLIR toolchain, Python venv, test suite.
# Run:  bash setup.sh          (MLIR_TOOLS=0 bash setup.sh skips the optional MLIR packages)
# Then: source .venv/bin/activate && python tune.py ...   (see README.md / docs/development/BUILD.md)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

sudo apt-get update
sudo apt-get install -y build-essential python3 python3-venv python3-pip

# Optional backend 3 (MLIR) needs mlir-opt-21, mlir-translate-21, llc-21 (BUILD.md); package names vary by release.
if [ "${MLIR_TOOLS:-1}" = "1" ]; then
  sudo apt-get install -y llvm-21 mlir-21-tools \
    || echo "WARNING: llvm-21/mlir-21-tools not in your apt sources; MLIR backend tests will be skipped (see docs/development/BUILD.md)."
fi

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements-dev.txt   # includes requirements.txt + pytest

.venv/bin/python -m pytest -q || echo "NOTE: some tests failed or were skipped (missing optional tools)."
echo "Done. Activate with: source .venv/bin/activate"
