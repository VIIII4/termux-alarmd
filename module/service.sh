#!/system/bin/sh
# KernelSU/Magisk: 开机自启（late_start service 阶段）
MODDIR=${0%/*}
D=/data/adb/alarmd

mkdir -p "$D/run"
[ -f "$D/alarms" ] || : >"$D/alarms"
[ -f "$D/config" ] || printf 'SOUND=/system/media/audio/alarms/Awoken.ogg\nRING_MAX=120\nVOL_ALARM=8\nVOL_MUSIC=6\nVIBRATE=0\n' >"$D/config"

nohup /system/bin/sh "$MODDIR/alarmd.sh" >/dev/null 2>&1 &
