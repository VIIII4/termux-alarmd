# todo 集成版说明

本目录的 `todo.py` 是原 [Todo, Calendar & Alarm CLI] 的完整版本，改动集中在：

1. **alarmd 集成层**（`alarmd_build_lines` / `alarmd_sync`）：
   `alarms.json` 仍是唯一数据源；`todo alarm add/delete/stop` 后自动把 active 闹钟
   同步成 alarmd 行（`t<id>|HH:MM|dayspec|标题`）。repeat 映射：
   `daily→daily`、`weekdays→workdays`、`weekly(周几)→数字列表`（0=Mon..6=Sun → 1..7）、
   `target_date→绝对 epoch 的 once 行`。
2. **每日任务提醒钩子**（`todo alarm digest [on|off|HH:MM]`，默认 08:30）：
   生成 `xdigest|HH:MM|xdaily|<python> todo.py --daemon-check` 行，
   到点由 alarmd 在 app 域静默执行，投递到期/逾期任务通知。
3. **退役旧后端**：`todo alarm-daemon` 只打印接管说明；
   `reminders-setup`（job-scheduler）保留但不再必要。

安装：仓库根目录 `bash install.sh`（自动备份原文件），或手动拷到 `~/.todo/todo.py`。
