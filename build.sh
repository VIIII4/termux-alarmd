#!/data/data/com.termux/files/usr/bin/bash
# 打包 KernelSU/Magisk 可刷入的 release zip
set -e
cd "$(dirname "$0")"
VER=$(sed -n 's/^version=//p' module/module.prop)
ZIP="alarmd-$VER.zip"
rm -f "$ZIP"
( cd module && zip -qr "../$ZIP" . )
echo "→ $(pwd)/$ZIP（管理器 → 从存储安装 → 重启）"
