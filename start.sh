#!/usr/bin/env bash
# 重复文件检测清理工具 - Linux/macOS launcher

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Please install Python 3."
    exit 1
fi

# Check / install dependencies
if ! python3 -c "import flask" 2>/dev/null; then
    echo "Installing Flask..."
    # 优先使用 --user 安装，避免 PEP 668 externally-managed-environment 限制
    if ! python3 -m pip install --user flask 2>/dev/null; then
        echo "ERROR: Failed to install Flask."
        echo "  Try one of the following:"
        echo "    1) python3 -m pip install --user flask"
        echo "    2) python3 -m pip install --break-system-packages flask"
        echo "    3) Create a venv: python3 -m venv venv && source venv/bin/activate && pip install flask"
        exit 1
    fi
fi

# 从 app.py 读取版本号
VERSION=$(python3 -c "import re; m=re.search(r'__version__\s*=\s*[\"\\']([^\"\\' ]+)[\"\\']', open('app.py','r',encoding='utf-8').read()); print(m.group(1) if m else 'unknown')")

echo ""
echo "============================================"
echo "  重复文件检测清理工具 v${VERSION}"
echo "  Open: http://localhost:36901"
echo "  Press Ctrl+C to stop"
echo "============================================"
echo ""

# 捕获 Ctrl+C，避免 set -e 因非零退出码报错
trap 'echo ""; echo "服务已停止。"; exit 0' INT

python3 app.py
