#!/system/bin/sh
# 模块卸载时：停守护、清 RTC/wakelock。数据 /data/adb/alarmd 保留（想删手动删）。
p=$(cat /data/adb/alarmd/run/alarmd.pid 2>/dev/null)
[ -n "$p" ] && kill "$p" 2>/dev/null
echo 0 >/sys/class/rtc/rtc0/wakealarm 2>/dev/null
echo alarmd >/sys/power/wake_unlock 2>/dev/null
exit 0
