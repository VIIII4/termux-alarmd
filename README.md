# alarmd — Android 内核级 RTC 闹钟（Termux + KernelSU/Magisk 模块）

没有时钟 app 也能用的闹钟：**内核 RTC wakealarm 定时唤醒 + root 守护 + Termux 效果层**。
深度休眠零功耗、秒级精度；Termux 被杀、设备重启、灭屏休眠都不影响响铃。

```
~/.todo/alarms.json (可选, todo 集成)          Termux CLI: alarm set 07:30 daily
        │                                            │
        ▼ (单向同步, t<id> 行)                        ▼
┌─────────────────────────────────────────────────────────────┐
│  /data/adb/alarmd/alarms  ←──────────────  /data/adb/modules/alarmd/  │
│         数据目录（升级不丢）                      KernelSU/Magisk 模块  │
│                                    service.sh 开机自启 root 守护       │
│  守护循环: 计算 next → arm RTC wakealarm → 1s 对表轮询                 │
│     ├─ 普通闹钟 → run-as com.termux 放铃+通知(停止/贪睡按钮)           │
│     └─ xdaily/xonce → 到点静默执行命令(todo 每日任务提醒)              │
└─────────────────────────────────────────────────────────────┘
```

## 特性

- **RTC 唤醒**：`/sys/class/rtc/rtc0/wakealarm` 内核级定时，设备睡着也到点即醒（实测休眠唤醒后 1 秒内触发）
- **不依赖任何 app 存活**：守护是 root 进程，随 KernelSU/Magisk service.sh 自启；Termux 只是"效果层"
- **SELinux 正确**：放铃/通知通过 `run-as com.termux` 在 app 自己的域里执行（绕开 Termux:API socket 回传的 `Permission denied`）
- **防呆设计**：grace 窗口 + fired 标记防重复触发；到点前 10s RTC strobe 保证唤醒窗口；响铃期间持 wake_lock
- **exec 型闹钟**：`xdaily/xonce` 到点不响铃、以 Termux 用户身份执行任意命令（内置 todo 每日提醒钩子）
- **todo 集成**：`~/.todo/todo.py`（Todo/Calendar/Alarm CLI）的闹钟后端无缝切到 alarmd，任务到期/逾期提醒也由本守护投递
- 响铃通知带 **停止 / 贪睡** 按钮，CLI/通知/上划三种停止路径，`alarm kill` 一键核爆

## 环境要求

| 组件 | 说明 |
|---|---|
| root（KernelSU / Magisk） | 模块自启 + sysfs 读写 |
| Termux | 效果层宿主 |
| Termux:API | `termux-media-player` / `termux-notification` |
| 通知使用权（可选） | `termux-notification-list` 兜底清通知 / CLI 查看用 |

## 安装

### 方式一：刷入 zip（推荐）
```sh
./build.sh                 # 生成 alarmd-<ver>.zip
# KernelSU/Magisk 管理器 → 从存储安装 → 选择该 zip → 重启
```

### 方式二：仓库内一键安装（Termux 里执行）
```sh
git clone https://github.com/VIIII4/termux-alarmd && cd termux-alarmd
bash install.sh            # 部署模块 + alarm CLI（+ todo 集成，装前自动备份）
alarm daemon start         # 不重启立即启用
```

> 已授予 Termux 的 su 授权会被复用；通知按钮需要 Termux 属性 `allow-external-apps=true`（install.sh 会自动加并提示）。

## 快速开始

```sh
alarm set 07:30 daily 上班          # daily | workdays | weekend | 1,3,5 | once(默认)
alarm set 21:00 喝水                 # 单次，下一次 21:00
alarm list                          # ← 标记下一次触发
alarm snooze 10                     # 贪睡 10 分钟
alarm stop                          # 停铃（任意路径可用）
alarm test                          # 试铃（低音量）
alarm sound /system/media/audio/alarms/Ding.ogg
alarm status                        # 守护/RTC/下一次/log
alarm daemon start|stop|restart
alarm kill                          # 紧急全停：进程/RTC/wakelock/声音/通知
```

## todo 集成

`todo-integration/todo.py` 在原 [todo 工具](todo-integration/README.md) 基础上把闹钟后端换成 alarmd：

```sh
todo alarm add                      # 照旧交互，自动同步（RTC 级，Termux 关闭也响）
todo alarm digest                   # 每日任务提醒状态（默认 08:30）
todo alarm digest 09:00             # 改时间 / off 关闭
todo alarm sync                     # 手动重推
```

数据流单向：`alarms.json` 是唯一事实源 → 同步为 `t<id>|` 行；两边 id 互查（`todo alarm 5` ↔ `alarm list` 的 `t5`）。

## 配置 `/data/adb/alarmd/config`

| 键 | 默认 | 说明 |
|---|---|---|
| `SOUND` | `/system/media/audio/alarms/Awoken.ogg` | 铃声（系统自带 9 首在 `/system/media/audio/alarms/`） |
| `RING_MAX` | `120` | 最长响铃秒数 |
| `VOL_ALARM` / `VOL_MUSIC` | `8` / `6` | 触发时设置的两路音量（0-15） |
| `VIBRATE` | `0` | `1` = 响铃通知带震动 |
| `TZOFF` | `+0800` | 仅当 `date +%z` 读取失败时的时区兜底 |

闹钟时间按**设备本地时区**动态解释。数据目录 `/data/adb/alarmd/`（含 `alarms`、`run/fired` 触发标记、`log`）不随模块升级/卸载删除。

## 语义备注

- `once` 错过超过 120 秒（如关机）不补响，顺延到下个周期；重复闹钟每周期一次（fired 标记）
- DST 国家跨夏令时切换日会偏 1 小时（按 86400s 等分天，中国无影响）
- 响铃通知为 ongoing，点「停止」/「贪睡」或 `alarm stop` 均会移除

## 踩坑记录（对二次开发很有价值）

开发过程中实打实踩过的坑全部记录在 [docs/PITFALLS.md](docs/PITFALLS.md)：mksh 的 `|` alternation、`$$` 与子 shell、awk 空文件 `NR==FNR`、Termux:API 在非 app 域的 socket 回传失败、`pkill -f` 自杀式匹配、KSU su 的延迟等。

## 卸载

管理器卸载模块，或：
```sh
su -c 'sh /data/adb/modules/alarmd/uninstall.sh'
su -c 'rm -rf /data/adb/modules/alarmd /data/adb/alarmd'   # 数据一并删
```

## License

MIT — 见 [LICENSE](LICENSE)
