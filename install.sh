#!/bin/sh
# skx installer — 一条命令装好
#   curl -fsSL https://raw.githubusercontent.com/coikexxx/skx/main/install.sh | sh
#
# 环境变量:
#   SKX_BIN_DIR   安装位置 (默认 ~/.local/bin)
#   SKX_REPO      GitHub 仓库 (默认 coikexxx/skx, 发布时改成你的)
set -eu

BIN_DIR="${SKX_BIN_DIR:-$HOME/.local/bin}"
REPO="${SKX_REPO:-coikexxx/skx}"

mkdir -p "$BIN_DIR"
curl -fsSL "https://raw.githubusercontent.com/$REPO/main/skx.py" -o "$BIN_DIR/skx"
chmod +x "$BIN_DIR/skx"

echo "skx 已安装到 $BIN_DIR/skx"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "⚠️  $BIN_DIR 不在 PATH 里,加一行到你的 shell 配置:"
     echo "   export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac

echo
echo "开始体检:  skx audit"
