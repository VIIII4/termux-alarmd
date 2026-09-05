#!/system/bin/sh
# alarmd — kernel-RTC alarm daemon (root, KernelSU/Magisk module)
#
# 原理：
#   /sys/class/rtc/rtc0/wakealarm  一次性内核定时唤醒（设备可正常深度休眠，零功耗）
#   /sys/power/wake_lock  响铃期间持有 wakelock，防止系统半路又睡过去
#   run-as com.termux       效果层（放歌/通知/震动）必须在 app 自己的 SELinux 域里跑，
#                           否则 Termux:API 的 socket 回传会 Permission denied
#
# 闹钟行格式（/data/adb/alarmd/alarms，字段分隔 |，label 里不许有 |）：
#   id|HH:MM|days|label    days: once|daily|workdays|weekend|1,3,5 (1=周一..7=周日)
#   id|EPOCH|once|label    绝对时间（贪睡用），过期 120s 后清理
#
# 注意：suspend 期间 CLOCK_MONOTONIC 停走，所以主循环用 1s 短轮询、每轮用 date 对表，
# 到点前 10s 用 "RTC strobe"（每秒重设 now+2）保证唤醒窗口，详见主循环注释。

DATA=/data/adb/alarmd
ALARMS=$DATA/alarms
RUN=$DATA/run
LOG=$DATA/log
WAKE=/sys/class/rtc/rtc0/wakealarm
WL=/sys/power/wake_lock
WUL=/sys/power/wake_unlock
TP=/data/data/com.termux/files/usr
TH=/data/data/com.termux/files/home

# boot 环境无 /system/bin/awk（toybox 不带），自举 PATH 保证 awk 可用
if ! command -v awk >/dev/null 2>&1; then
    export PATH="/data/adb/ksu/bin:$TP/bin:/system/bin:/system/xbin:$PATH"
fi

[ -f "$DATA/config" ] && . "$DATA/config"

log() {
    echo "$(date '+%m-%d %H:%M:%S') $*" >>"$LOG"
    if [ "$(wc -c <"$LOG")" -gt 262144 ]; then
        tail -n 400 "$LOG" >"$LOG.t" && mv "$LOG.t" "$LOG"
    fi
}

# ---- 单实例 ---------------------------------------------------------------
if [ -f "$RUN/alarmd.pid" ]; then
    p=$(cat "$RUN/alarmd.pid" 2>/dev/null)
    if [ -n "$p" ] && [ -d "/proc/$p" ] && grep -q alarmd "/proc/$p/cmdline" 2>/dev/null; then
        exit 0
    fi
fi
mkdir -p "$RUN"
[ -f "$RUN/fired" ] || : >"$RUN/fired"
echo $$ >"$RUN/alarmd.pid"
log "alarmd started: pid $$ ctx=$(cat /proc/self/attr/current 2>/dev/null)"

# ---- 在 Termux app 的 uid/SELinux 域里执行效果命令 ------------------------
# 用户数据（label 等）只通过 LABEL/AID/SND/NID 环境变量传入，避免任何注入
runapp() {
    LABEL="$LABEL" AID="$AID" SND="$SND" NID="$NID" \
    run-as com.termux "$TP/bin/sh" -c "
        export PATH='$TP/bin:/system/bin' HOME='$TH' TMPDIR='$TP/tmp'
        unset LD_LIBRARY_PATH LD_PRELOAD
        $1"
}

# ---- 计算下一次应触发的闹钟 -------------------------------------------
# 输出 "id|due|spec|label"。due 允许是过去但在 grace 窗口内（刚到点）,
# 由主循环触发后写入 fired 文件（"id|due"）防止重复触发。
# 语义陷阱：不能用 "严格未来" 筛选，否则触发窗口永远为 0 秒。
GRACE=${GRACE:-120}
next_alarm() {
    now=$(date +%s)
    z=$(date +%z 2>/dev/null)
    case "$z" in
        [+-][0-9][0-9][0-9][0-9]) ;;
        *) z="${TZOFF:-+0800}" ;;
    esac
    day0=$(awk -v n="$now" -v z="$z" 'BEGIN{
        s = (substr(z,1,1) == "-") ? -1 : 1
        print n - ((n + s*(substr(z,2,2)*3600 + substr(z,4,2)*60)) % 86400)
    }')
    awk -F'|' -v now="$now" -v day0="$day0" -v grace="$GRACE" -v f="$RUN/fired" '
        FILENAME == f { fired[$1 "|" $2] = 1; next }
        NF >= 4 {
            id = $1; t = $2; spec = $3
            best = ""
            if (t ~ /^[0-9]+$/) {
                key = id "|" (t + 0)
                if (!(key in fired) && t + 0 > now - grace) best = t + 0
            } else {
                split(t, a, ":"); sod = a[1]*3600 + a[2]*60
                for (off = 0; off < 8; off++) {
                    wd = (int(day0/86400) + 3 + off) % 7 + 1
                    ok = 0
                    if (spec == "daily" || spec == "once" || spec == "xdaily" || spec == "xonce") ok = 1
                    else if (spec == "workdays") ok = (wd <= 5)
                    else if (spec == "weekend") ok = (wd >= 6)
                    else if (spec ~ /^[0-9,]+$/) {
                        m = split(spec, L, ",")
                        for (i = 1; i <= m; i++) if (L[i]+0 == wd) ok = 1
                    }
                    if (!ok) continue
                    cand = day0 + off*86400 + sod
                    key = id "|" cand
                    if (key in fired) continue
                    if (cand > now - grace) { best = cand; break }
                }
            }
            if (best != "" && (min == "" || best < min)) {
                min = best; out = id "|" best "|" spec "|" $4
            }
        }
        END { if (min != "") print out }
    ' "$RUN/fired" "$ALARMS" 2>/dev/null
}

purge_stale() {
    now=$(date +%s)
    awk -F'|' -v now="$now" \
        'NF >= 4 && ($2 !~ /^[0-9]+$/ || $2+0 > now - 120)' \
        "$ALARMS" >"$ALARMS.t" 2>/dev/null && mv "$ALARMS.t" "$ALARMS"
    [ -f "$RUN/fired" ] && awk -F'|' -v now="$now" 'NF == 2 && $2+0 > now - 86400' \
        "$RUN/fired" >"$RUN/fired.t" 2>/dev/null && mv "$RUN/fired.t" "$RUN/fired"
}

remove_id() {
    sed -i "/^$1|/d" "$ALARMS" 2>/dev/null
}

# ---- 到点执行命令（不响铃），以 Termux 用户身份 ------------------------
# 行格式：id|HH:MM|xdaily|命令（todo 每日 digest 用）
exec_alarm() {
    id=$1; cmd=$2
    echo alarmd >"$WL" 2>/dev/null
    log "EXEC start [$id]"
    CMD="$cmd" run-as com.termux "$TP/bin/sh" -c "
        export PATH='$TP/bin:/system/bin' HOME='$TH' TMPDIR='$TP/tmp'
        unset LD_LIBRARY_PATH LD_PRELOAD
        \$CMD" >/dev/null 2>&1
    echo alarmd >"$WUL" 2>/dev/null
    log "EXEC end [$id]"
}

# ---- 响铃（daemon 的子进程，root） ----------------------------------------
ring() {
    id=$1; label=$2
    . "$DATA/config" 2>/dev/null
    SND=${SOUND:-/system/media/audio/alarms/Awoken.ogg}
    MAX=${RING_MAX:-120}
    VA=${VOL_ALARM:-8}
    VM=${VOL_MUSIC:-6}
    VIB=${VIBRATE:-0}
    AID=$id; LABEL=$label; NID=alarm-$id
    # ring.pid 由主循环用 $! 写入（子 shell 里 $$ 是父 pid，不能用来标识 ring）
    echo alarmd >"$WL" 2>/dev/null
    rm -f "$RUN/stop"
    echo "$id" >"$RUN/firing"
    log "RING start [$id] $label"
    # 音量设置 + 通知只发一次（ongoing）；循环里只剩 play，减少 run-as 调用
    VIBARG=""
    [ "$VIB" = "1" ] && VIBARG='--vibrate 800,300,800 '
    notify_cmd='termux-volume alarm '"$VA"' >/dev/null 2>&1; termux-volume music '"$VM"' >/dev/null 2>&1; termux-notification --id "$NID" --title "⏰ $LABEL" --content "alarm stop 停止 · alarm snooze 贪睡" --priority max --ongoing '"$VIBARG"'--button1 停止 --button1-action "alarm stop" --button2 贪睡10分 --button2-action "alarm snooze 10" --on-delete "alarm stop" >/dev/null 2>&1'
    runapp "$notify_cmd"
    end=$(( $(date +%s) + MAX ))
    while [ "$(date +%s)" -lt "$end" ]; do
        [ -f "$RUN/stop" ] && break
        runapp 'termux-media-player play "$SND" >/dev/null 2>&1'
        # 曲目时长（拿不到就用 20s）
        d=20
        i=$(runapp 'sleep 1; termux-media-player info 2>/dev/null' | sed -n 's|.*/  *\([0-9:]*\)$|\1|p')
        case "$i" in
            [0-9]*:*)
                n=$(echo "$i" | awk -F: '{n=0; for (j=1; j<=NF; j++) n=n*60+$j; print n}')
                [ "$n" -gt 2 ] && [ "$n" -lt 7200 ] && d=$((n - 2))
                ;;
        esac
        slept=0
        while [ "$slept" -lt "$d" ]; do
            [ -f "$RUN/stop" ] && break
            sleep 1
            slept=$((slept + 1))
        done
    done
    runapp 'termux-media-player stop >/dev/null 2>&1; termux-notification-remove "$NID" >/dev/null 2>&1'
    echo alarmd >"$WUL" 2>/dev/null
    rm -f "$RUN/firing" "$RUN/ring.pid"
    log "RING end [$id]"
}

# ---- 主循环 ---------------------------------------------------------------
armed=0
ticks=0
lastnext="INIT"
log "entering main loop"
while :; do
    now=$(date +%s)
    line=$(next_alarm)

    # 给 CLI 读的状态快照（只在变化时写，减少 flash 磨损）
    if [ "$line" != "$lastnext" ]; then
        echo "$line" >"$RUN/next.t" 2>/dev/null && mv "$RUN/next.t" "$RUN/next"
        lastnext=$line
    fi

    if [ -n "$line" ]; then
        # !!! mksh 陷阱：/system/bin/sh 是 mksh，模式里裸 '|' 是 alternation，
        # ${line%%|*} 会匹配整串返回空。只能用 IFS 切分，绝不能用 | 做模式展开。
        oldifs=$IFS; IFS='|'; set -f; set -- $line; set +f; IFS=$oldifs
        id=$1; t=$2; spec=$3; shift 3; label=$*

        # t 必须是纯数字；空值会让 [ -ge ] 恒真（事故根因之二）
        case "$t" in
            ''|*[!0-9]*)
                log "SKIP bad line: [$line]"
                sleep 5
                continue
                ;;
        esac

        if [ "$now" -ge "$t" ]; then
            case "$spec" in
                xdaily|xonce)
                    exec_alarm "$id" "$label"
                    [ "$spec" = "xonce" ] && remove_id "$id"
                    echo "$id|$t" >>"$RUN/fired"
                    echo 0 >"$WAKE" 2>/dev/null
                    armed=0; lastnext="INIT"
                    sleep 2
                    continue
                    ;;
            esac
            # 同时只允许一个响铃循环
            if [ -f "$RUN/ring.pid" ] && kill -0 "$(cat "$RUN/ring.pid" 2>/dev/null)" 2>/dev/null; then
                : # 已在响，不叠加
            else
                ring "$id" "$label" &
                echo $! >"$RUN/ring.pid"
                log "spawn ring for [$id] pid=$!"
            fi
            [ "$spec" = "once" ] && remove_id "$id"
            echo "$id|$t" >>"$RUN/fired"
            echo 0 >"$WAKE" 2>/dev/null   # 清掉 strobe 可能留下的 T+1 残值
            armed=0
            lastnext="INIT"
            sleep 2
            continue
        fi

        if [ "$t" != "$armed" ]; then
            echo 0 >"$WAKE" 2>/dev/null
            echo "$t" >"$WAKE" 2>/dev/null && armed=$t
            log "RTC armed -> $t ($(date -d "@$t" '+%F %T' 2>/dev/null || echo '?')) [$id]"
        fi

        # RTC strobe：到点前 10 秒内，每秒把唤醒重设为 now+2。
        # 这样即使系统在 T-x 秒睡下去、又在 T 醒来后想立刻再睡，最多 2s 就会被
        # 再次强制唤醒，直到主循环跨过 T、ring() 拿住 wake_lock 为止。
        rem=$((t - now))
        if [ "$rem" -le 10 ]; then
            echo 0 >"$WAKE" 2>/dev/null
            echo $((now + 2)) >"$WAKE" 2>/dev/null
            armed=$t
        fi
        sleep 1
    else
        if [ "$armed" != "0" ]; then
            echo 0 >"$WAKE" 2>/dev/null
            armed=0
            log "RTC disarmed (no future alarms)"
        fi
        sleep 5
    fi

    ticks=$((ticks + 1))
    [ $((ticks % 120)) -eq 0 ] && purge_stale
done
