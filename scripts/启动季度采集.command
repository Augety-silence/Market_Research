#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3,10), "需要Python 3.10以上，建议3.11"'
if [ ! -d .venv ]; then "$PYTHON_BIN" -m venv .venv; fi
.venv/bin/python -m pip install -e ".[quarter]"
.venv/bin/python -m playwright install chromium
if [ ! -f quarter.config.json ]; then cp examples/quarter.config.example.json quarter.config.json; fi
.venv/bin/python -m bili_research quarter login
.venv/bin/python -m bili_research quarter collect
read -r -p '已结束，按回车关闭终端。'
