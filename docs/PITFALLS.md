# 开发踩坑记录

按"事故等级"排序。每一条都是实测血泪，修复方式已内建在代码里，这里留档给后来者。

## 1. mksh 模式里的 `|` 是 alternation（事故级）

Android `/system/bin/sh` 是 **mksh R59**。ksh 系 shell 的模式中裸 `|` 表示"或"：

```sh
x="a|b|c"
echo "${x%%|*}"    # → ""      （模式 = 空 或 任意串，匹配整串！）
echo "${x#*|}"     # → "a|b|c" （匹配空前缀，什么都没剥）
echo "${x%%"|"*}"  # → "a"     （引号包起来才是字面量）
```

解析 `id|HH:MM|days|label` 这种管道分隔格式时全灭：字段全空，
`[ "$now" -ge "$t" ]` 里 `t=""` 在 mksh 中等价 `now >= 0` → **恒真**，
守护每 2 秒 spawn 一个响铃循环，系统直接被几十个并发响铃拖死。

**修复**：mksh 跑的脚本里解析分隔字段一律用 `IFS='|'; set -- $line`，绝不写 `|` 模式展开。
bash 下验证过的代码在 mksh 下必须重验。

## 2. 子 shell 里的 `$$` 是父进程 pid（事故级）

`ring &` 后台函数里 `echo $$ > ring.pid` 写的是**守护自己的 pid**；
停止逻辑 `kill $(cat ring.pid)` → 杀死守护本身，闹钟系统整体罢工。

**修复**：由主循环 `ring ... & ; echo $! > ring.pid` 用 `$!` 记录真正的子进程 pid。

## 3. awk 双文件 `NR == FNR` + 空文件

`awk 'NR==FNR{...}' file1 file2` 在 file1 为**空**时，file2 的第一条记录同样满足
`NR==FNR`，被当作 file1 的内容吃掉。fired 标记文件首次创建必为空 → 所有闹钟被跳过。

**修复**：`FILENAME == f` 判断，或保证首文件非空。

## 4. Termux:API 客户端必须在 app 的 SELinux 域里跑

`termux-api-broadcast` 通过 **Unix socket** 回传结果；root/su 域创建的 socket，
Termux:API app（`untrusted_app_27` + MLAT categories）connect 时 `Permission denied` →
客户端死等（表面症状：termux-media-player 挂住，声音其实在响）。

**修复**：root 守护调效果层时 `run-as com.termux <termux-sh> -c "..."`，
得到 `runas_app:s0:c...` 与 app 同 categories。用户数据经 env 变量传入避免注入。
（Termux 为 debuggable 构建所以 run-as 可用。）

## 5. "严格未来"筛选导致触发窗口为 0 秒

调度器若只返回"下一个未来时刻"，`now >= t` 的判定窗口永远不存在 → 永不触发。
正确设计：**grace 窗口**（允许返回刚过去的 due，如 120s）+ **fired 标记**
（`id|due` 写盘防重复触发，主循环触发后追加，next_alarm 读取过滤）。

## 6. suspend 期间 CLOCK_MONOTONIC 停走

一次长 `sleep` 在休眠时"冻结"，醒来还要补足剩余的清醒时间。主循环必须**短轮询
（1s）+ 每轮 `date +%s` 对表**；同时到点前 10s 用 RTC strobe（每秒重设 now+2）
保证唤醒窗口收敛，ring 启动立即抓 wake_lock。

## 7. KSU su 的异步延迟（两连坑）

- `su -c "nohup X &"` 返回后进程可能要 1-2s 才真正起来：启动后**轮询确认**（10s），
  别 sleep 1 就判生死
- kill 的 su 调用可能 >1s 才落地：restart 里 start 检查时旧进程"还活着" → 直接退出。
  同样用轮询等待死亡

## 8. `pkill -f` 自杀式匹配

`pkill -f alarmd.sh` 会匹配到**自己这条命令行**（含该字符串的 bash）把自己杀了。
用 `pkill -f 'alarmd[.]sh'` 的字符类写法规避——正则匹配字面 `alarmd.sh`，
而自身命令行里是带方括号的 `alarmd[.]sh`，不匹配。

## 9. 其余小坑

- `termux-notification` 的参数是 `--on-delete`，不是 `--delete-action`
- `timeout su -c ...` 杀不掉内层 root 进程（只杀了 su 客户端）；timeout 要套在 su **里面**
- root 进程 rm 模块目录 ≠ 停止守护：进程仍在跑；模块卸载务必显式 kill + 清 RTC + 释放 wake_lock
- `cmd alarm` 只有 set-time/set-timezone，没有设闹钟的 shell 接口；
  `ACTION_SET_ALARM` intent 也没有系统级接收方（时钟 app 没装就无处落地）
- shell 里 `exit 0` 写进被 restart 复用的函数会把整个 CLI 带走
