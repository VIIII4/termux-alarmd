# Changelog

## v1.2.0 (2026-09-08)
- `alarm stop <id>`：跳过指定闹钟的下一次触发（写 fired 标记，守护自动重排；once 直接取消）
- `alarm stop`（无参）如实报告——不再无铃也打“已停止”
- CLI 审计日志：set/rm/skip/snooze/stop/kill 全部以 `[CLI]` 前缀写入 /data/adb/alarmd/log，与守护日志同文件可对账

## v1.1.0 (2026-09-05)
- exec 型闹钟：`xdaily`/`xonce` 到点不响铃，以 Termux 用户身份执行命令
- todo 工具集成：alarms.json 单向同步为 `t<id>` 行；每日任务提醒钩子（digest）
- 修复：alarm stop 竞态导致 ongoing 通知残留（先取 firing 再 kill + tag 兜底扫尾）
- 修复：守护重启后 next 快照残留；CLI start/stop 轮询等待 su 延迟
- ring 单实例互斥（ring.pid 由主循环 $! 写入）

## v1.0.0 (2026-09-04)
- 首个可用版本：RTC wakealarm 调度、wake_lock 保持、run-as 效果层、
  grace+fired 防重、RTC strobe、alarm CLI、KernelSU/Magisk 模块化
