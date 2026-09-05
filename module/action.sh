#!/system/bin/sh
# 管理器里点 action 时显示状态
D=/data/adb/alarmd
echo "== alarmd 状态 =="
p=$(cat "$D/run/alarmd.pid" 2>/dev/null)
if [ -n "$p" ] && kill -0 "$p" 2>/dev/null; then
    echo "守护: 运行中 (pid $p)"
else
    echo "守护: 未运行"
fi
rtc=$(cat /sys/class/rtc/rtc0/wakealarm 2>/dev/null)
echo "RTC wakealarm: ${rtc:-不可读} (0=未设)"
n=$(cat "$D/run/next" 2>/dev/null)
if [ -n "$n" ]; then
    echo "下一次: $n"
else
    echo "下一次: (无)"
fi
echo "-- 闹钟列表 --"
cat "$D/alarms" 2>/dev/null || echo "(空)"
echo "-- log 尾部 --"
tail -n 5 "$D/log" 2>/dev/null
