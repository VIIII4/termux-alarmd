#!/system/bin/sh
# zip 方式刷入时的初始化（数据目录只在首次创建，升级不覆盖）
D=/data/adb/alarmd
mkdir -p "$D/run"
[ -f "$D/alarms" ] || : >"$D/alarms"
[ -f "$D/config" ] || printf 'SOUND=/system/media/audio/alarms/Awoken.ogg\nRING_MAX=120\nVOL_ALARM=8\nVOL_MUSIC=6\nVIBRATE=0\n' >"$D/config"
ui_print "alarmd 已安装。在 Termux 里执行: alarm daemon start"
