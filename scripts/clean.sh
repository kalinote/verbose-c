#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "清理项目缓存: $PROJECT_ROOT"

find "$PROJECT_ROOT" -type d \( -name "__pycache__" -o -name "__vbccache__" \) -prune -exec rm -rf {} +

if [ -f "$PROJECT_ROOT/parser.py" ]; then
    rm -f "$PROJECT_ROOT/parser.py"
fi

if [ -d "$PROJECT_ROOT/dumps" ]; then
    rm -rf "$PROJECT_ROOT/dumps"
fi

echo "清理完成"
