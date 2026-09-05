#!/data/data/com.termux/files/usr/bin/bash
# alarmd 一键安装（在 Termux 里执行，需要 su）
# 部署: KernelSU/Magisk 模块 + alarm CLI +（可选）todo 集成
set -e

ROOT=$(cd "$(dirname "$0")" && pwd)
PREFIX=${PREFIX:-/data/data/com.termux/files/usr}

[ "$(id -u)" = "0" ] && { echo "请在 Termux（非 root）里运行"; exit 1; }
su -c true 2>/dev/null || { echo "需要 su（KernelSU/Magisk）授权"; exit 1; }

echo "== 1. 部署模块 =="
su -c "mkdir -p /data/adb/modules/alarmd /data/adb/alarmd/run
cp $ROOT/module/module.prop $ROOT/module/alarmd.sh $ROOT/module/service.sh \
   $ROOT/module/action.sh $ROOT/module/uninstall.sh $ROOT/module/customize.sh \
   /data/adb/modules/alarmd/
chmod 755 /data/adb/modules/alarmd/*
[ -f /data/adb/alarmd/alarms ] || : > /data/adb/alarmd/alarms
[ -f /data/adb/alarmd/run/fired ] || : > /data/adb/alarmd/run/fired
[ -f /data/adb/alarmd/config ] || printf 'SOUND=/system/media/audio/alarms/Awoken.ogg\nRING_MAX=120\nVOL_ALARM=8\nVOL_MUSIC=6\nVIBRATE=0\n' > /data/adb/alarmd/config"

echo "== 2. 安装 CLI =="
install -m 755 "$ROOT/termux/alarm" "$PREFIX/bin/alarm"

echo "== 3. Termux 属性（通知按钮需要） =="
mkdir -p ~/.termux
if ! grep -q '^allow-external-apps' ~/.termux/termux.properties 2>/dev/null; then
    echo 'allow-external-apps=true' >> ~/.termux/termux.properties
    echo "  已写入 allow-external-apps=true（若 Termux 已在运行，重启 Termux 后生效）"
fi
command -v termux-reload-settings >/dev/null && termux-reload-settings 2>/dev/null || true

echo "== 4. todo 集成（可选） =="
if [ -f "$HOME/.todo/todo.py" ]; then
    cp "$HOME/.todo/todo.py" "$HOME/.todo/todo.py.bak.$(date +%s)"
    install -m 755 "$ROOT/todo-integration/todo.py" "$HOME/.todo/todo.py"
    echo "  已安装集成版 todo.py（原文件已备份）"
    todo alarm sync 2>/dev/null || true
else
    echo "  跳过（未发现 ~/.todo/todo.py，可手动安装 todo-integration/todo.py）"
fi

echo "== 5. 启动守护 =="
alarm daemon start
alarm status
echo
echo "完成。开机自启随模块（下次重启生效）；建议跑一次 alarm test 验证。"
