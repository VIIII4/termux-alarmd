#!/usr/bin/env python3
"""
Todo, Calendar & Alarm CLI for Termux
- Stores tasks and alarms in ~/.todo/tasks.json and ~/.todo/alarms.json
- Uses termux-notification for reminders and alarms
- Calendar view (monthly/weekly)
- CRUD for tasks: add, list, edit, done, delete, search
- Alarms: one-time or recurring at specific times with sound + vibration
- Auto-reminders via termux-job-scheduler
"""

import json
import os
import sys
import subprocess
import signal
import time
from datetime import datetime, date, timedelta
from pathlib import Path

CONFIG_DIR = Path.home() / ".todo"
TASKS_FILE = CONFIG_DIR / "tasks.json"
ALARMS_FILE = CONFIG_DIR / "alarms.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"

# ─── helpers ──────────────────────────────────────────────────────────────────

def load_json(path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, IOError):
            return []
    return []

def save_json(path, data):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

load_tasks   = lambda: load_json(TASKS_FILE)
save_tasks   = lambda d: save_json(TASKS_FILE, d)
load_alarms  = lambda: load_json(ALARMS_FILE)
save_alarms  = lambda d: save_json(ALARMS_FILE, d)

def load_settings():
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            return {}
    return {}

def save_settings(s):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False))

# ═══ alarmd 集成层（RTC root 守护，KernelSU 模块）═══
ALARMD_ALARMS = "/data/adb/alarmd/alarms"
DIGEST_LINE_ID = "xdigest"

def _alarmd_spec(a):
    """todo 闹钟 → alarmd dayspec（todo 周几 0=Mon..6=Sun → alarmd 1..7）"""
    r = a.get("repeat")
    if r == "daily":
        return "daily"
    if r == "weekdays":
        return "workdays"
    if r == "weekly" and a.get("days_of_week"):
        return ",".join(str(d + 1) for d in a["days_of_week"])
    return None  # one-time

def alarmd_build_lines():
    """由 alarms.json + settings 生成要推入 alarmd 的行"""
    lines = []
    for a in load_alarms():
        if not a.get("active", True):
            continue
        h, m = a.get("hour"), a.get("minute")
        if h is None or m is None:
            continue
        t = f"{h:02d}:{m:02d}"
        title = (a.get("title") or "").replace("|", "／")
        if a.get("target_date"):
            d = parse_date(a["target_date"])
            if d:
                try:
                    epoch = int(datetime(d.year, d.month, d.day, h, m).timestamp())
                    lines.append(f"t{a['id']}|{epoch}|once|{title}")
                    continue
                except Exception:
                    pass
        spec = _alarmd_spec(a) or "once"
        lines.append(f"t{a['id']}|{t}|{spec}|{title}")
    s = load_settings()
    if s.get("digest_enabled", True):
        dt = s.get("digest_time", "08:30")
        cmd = f"{sys.executable} {os.path.abspath(__file__)} --daemon-check"
        lines.append(f"{DIGEST_LINE_ID}|{dt}|xdaily|{cmd}")
    return lines

def alarmd_sync(quiet=False):
    """把 todo 闹钟（t*/xdigest 行）同步进 alarmd，其余行不动。需 su。"""
    lines = alarmd_build_lines()
    tmp = CONFIG_DIR / ".alarmd_lines"
    tmp.write_text(("\n".join(lines) + "\n") if lines else "")
    inner = (
        f'grep -vE "^t[0-9]|^{DIGEST_LINE_ID}\\|" {ALARMD_ALARMS} > {ALARMD_ALARMS}.new 2>/dev/null; '
        f'cat "{tmp}" >> {ALARMD_ALARMS}.new; '
        f'mv {ALARMD_ALARMS}.new {ALARMD_ALARMS}'
    )
    r = subprocess.run(["su", "-c", inner], capture_output=True, text=True)
    if r.returncode != 0:
        if not quiet:
            print(f"⚠️ alarmd 同步失败（su 授权?）: {(r.stderr or '').strip()}")
        return False
    return True

def parse_date(s):
    if not s:
        return None
    formats = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y"]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    s_lower = s.strip().lower()
    today = date.today()
    if s_lower in ("today", "tod"):
        return today
    if s_lower in ("tomorrow", "tom", "tmr"):
        return today + timedelta(days=1)
    if s_lower in ("week",):
        return today + timedelta(days=7)
    return None

def parse_time(s):
    """Parse time like HH:MM or HHMM. Returns (hour, minute) or None."""
    if not s:
        return None
    s = s.strip()
    for fmt in ["%H:%M", "%H%M", "%H.%M"]:
        try:
            t = datetime.strptime(s, fmt).time()
            return (t.hour, t.minute)
        except ValueError:
            continue
    return None

def format_date(d):
    if d is None:
        return "no due date"
    return d.strftime("%a %d %b %Y")

def format_time(h, m):
    return f"{h:02d}:{m:02d}"

def notify(title, content, vibrate=False, sound=False, ongoing=False, alarm_mode=False, notify_id=None):
    """Send a Termux notification."""
    try:
        cmd = [
            "termux-notification",
            "-t", title,
            "-c", content,
            "--icon", "alarm" if alarm_mode else "event_note",
        ]
        if vibrate:
            cmd.extend(["--vibrate", "500,300,500,300,500"])
        if sound:
            cmd.append("--sound")
        if ongoing:
            cmd.append("--ongoing")
        if notify_id is not None:
            cmd.extend(["-i", str(notify_id)])
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def priority_char(p):
    p = p or 0
    if p >= 3: return "🔴"
    elif p >= 2: return "🟡"
    elif p >= 1: return "🟢"
    return "⚪"

def get_next_id(items):
    if not items: return 1
    return max(it.get("id", 0) for it in items) + 1

# ═══════════════════════════════════════════════════════════════════════════════
# TASK CRUD
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_add(args):
    tasks = load_tasks()
    title = " ".join(args) if args else None
    if not title:
        title = input("Title: ").strip()
    if not title:
        print("Error: title is required"); sys.exit(1)

    desc = input("Description (optional): ").strip()
    due_str = input("Due date (YYYY-MM-DD / today / tomorrow): ").strip()
    due = parse_date(due_str)

    prio_str = input("Priority [0=none, 1=low, 2=med, 3=high] (default 0): ").strip()
    try: priority = int(prio_str) if prio_str else 0
    except ValueError: priority = 0

    repeat_str = input("Repeat (daily/weekly/monthly/yearly, or leave empty): ").strip()
    repeat = repeat_str if repeat_str in ("daily", "weekly", "monthly", "yearly") else None

    task = {
        "id": get_next_id(tasks),
        "title": title,
        "description": desc,
        "due": due.isoformat() if due else (due_str if due_str else None),
        "due_raw": due_str if due_str and due is None else None,
        "due_parsed": due.isoformat() if due else None,
        "priority": priority,
        "repeat": repeat,
        "done": False,
        "created": date.today().isoformat(),
        "notified": None,
        "done_at": None,
    }
    tasks.append(task)
    save_tasks(tasks)
    print(f"✅ Added task #{task['id']}: {title}")
    if due: print(f"   Due: {format_date(due)}")

def cmd_list(args):
    tasks = load_tasks()
    today = date.today()
    mode = "pending"
    search_term = None
    show_all = False

    for a in args:
        if a in ("--all", "-a"): show_all = True
        elif a in ("--done", "-d"): mode = "done"
        elif a == "--overdue": mode = "overdue"
        elif a == "--today": mode = "today"
        elif a == "--week": mode = "week"
        elif a == "--month": mode = "month"
        elif not a.startswith("-"): search_term = a

    filter_map = {
        "done":    lambda t: t.get("done"),
        "overdue": lambda t: not t.get("done") and t.get("due_parsed") and t["due_parsed"] < today.isoformat(),
        "today":   lambda t: not t.get("done") and t.get("due_parsed") == today.isoformat(),
        "week":    lambda t: not t.get("done") and t.get("due_parsed") and today.isoformat() <= t["due_parsed"] <= (today + timedelta(days=7)).isoformat(),
        "month":   lambda t: not t.get("done") and t.get("due_parsed") and today.isoformat() <= t["due_parsed"] <= (today + timedelta(days=30)).isoformat(),
        "pending": lambda t: not t.get("done"),
    }

    if mode in filter_map:
        tasks = [t for t in tasks if filter_map[mode](t)]

    if search_term:
        st = search_term.lower()
        tasks = [t for t in tasks if st in t.get("title", "").lower() or st in t.get("description", "").lower()]

    def sort_key(t):
        due = t.get("due_parsed")
        return (0, due, -(t.get("priority", 0)), t.get("id", 0)) if due else (1, "9999", -(t.get("priority", 0)), t.get("id", 0))
    tasks.sort(key=sort_key)

    if not tasks:
        print("No tasks found."); return

    print()
    header = f"{'ID':>3} {'P':>2} {'Done':>4}  {'Title':<40} {'Due':<16}"
    print(header); print("-" * len(header))
    for t in tasks:
        due_str = format_date(parse_date(t.get("due_parsed"))) if t.get("due_parsed") else (t.get("due_raw") or "no due date")
        done_mark = "✅" if t.get("done") else "  "
        print(f"{t['id']:>3} {priority_char(t.get('priority')):>2} {done_mark:>4}  {t['title'][:38]:<40} {due_str:<16}")
    print(f"\n{tasks.__len__()} task(s)")

def cmd_calendar(args):
    tasks = load_tasks()
    today = date.today()
    year, month = today.year, today.month

    for a in (args or []):
        if a in ("prev", "last"):
            month -= 1
            if month == 0: month = 12; year -= 1
        elif a in ("next",):
            month += 1
            if month == 13: month = 1; year += 1
        else:
            try:
                parts = a.split("-")
                if len(parts) == 2: year, month = int(parts[0]), int(parts[1])
            except ValueError: pass

    due_map = {}
    for t in tasks:
        if t.get("done"): continue
        dp = t.get("due_parsed")
        if dp:
            try:
                d = parse_date(dp)
                if d and d.year == year and d.month == month:
                    due_map.setdefault(d.day, []).append(t["title"])
            except Exception: pass

    import calendar as cal_mod
    print(f"\n    {cal_mod.month_name[month]} {year}\n")
    print(" Mon  Tue  Wed  Thu  Fri  Sat  Sun ")
    print("---- ---- ---- ---- ---- ---- ----")

    c = cal_mod.Calendar(firstweekday=0)
    for week in c.monthdayscalendar(year, month):
        line = ""
        for day in week:
            if day == 0:
                line += "     "
            else:
                has_tasks = day in due_map
                marker = "●" if has_tasks else " "
                day_str = f"{day:>2}"
                if day == today.day and month == today.month and year == today.year:
                    if has_tasks:
                        line += f"\033[1;33m{marker}{day_str:>2}\033[0m "
                    else:
                        line += f"\033[1;37m[{day_str}]\033[0m "
                else:
                    line += f"{marker}{day_str:>2} "
        print(line)
    print("\n● = has tasks   [dd] = today")

    all_days = sorted(due_map.keys())
    print(f"\nTasks in {cal_mod.month_name[month]} {year}:")
    if not all_days:
        print("  (none)")
    else:
        for day in all_days:
            d = date(year, month, day)
            print(f"  {format_date(d)}:")
            for title in due_map[day][:5]:
                print(f"    - {title}")
            if len(due_map[day]) > 5:
                print(f"    ... and {len(due_map[day]) - 5} more")

def cmd_edit(args):
    if not args:
        print("Usage: todo edit <id>"); sys.exit(1)
    try: tid = int(args[0])
    except ValueError: print(f"Invalid id: {args[0]}"); sys.exit(1)

    tasks = load_tasks()
    for t in tasks:
        if t["id"] == tid:
            print(f"Editing task #{tid}: {t['title']}")
            print("(press Enter to keep current value)\n")
            new_title = input(f"Title [{t['title']}]: ").strip()
            if new_title: t["title"] = new_title
            new_desc = input(f"Description [{t.get('description', '')}]: ").strip()
            if new_desc: t["description"] = new_desc
            cur_due = t.get("due_parsed") or t.get("due_raw") or ""
            new_due_str = input(f"Due date [{cur_due}]: ").strip()
            if new_due_str:
                due = parse_date(new_due_str)
                if due:
                    t["due"] = due.isoformat(); t["due_parsed"] = due.isoformat(); t["due_raw"] = None
                else:
                    t["due"] = new_due_str; t["due_parsed"] = None; t["due_raw"] = new_due_str
            cur_prio = str(t.get("priority", 0))
            new_prio = input(f"Priority 0-3 [{cur_prio}]: ").strip()
            if new_prio:
                try: t["priority"] = int(new_prio)
                except ValueError: pass
            cur_repeat = t.get("repeat", "")
            new_repeat = input(f"Repeat [{cur_repeat}]: ").strip()
            if new_repeat:
                t["repeat"] = new_repeat if new_repeat in ("daily", "weekly", "monthly", "yearly") else None
            save_tasks(tasks)
            print(f"✅ Updated task #{tid}")
            return
    print(f"Task #{tid} not found")

def cmd_done(args):
    if not args:
        print("Usage: todo done <id> [id...]"); sys.exit(1)
    tasks = load_tasks()
    today_str = date.today().isoformat()
    found = 0
    for tid_str in args:
        try: tid = int(tid_str)
        except ValueError: print(f"Invalid id: {tid_str}"); continue
        for t in tasks:
            if t["id"] == tid:
                t["done"] = True; t["done_at"] = today_str
                print(f"✅ Done: #{tid} {t['title']}")
                if t.get("repeat"):
                    new_due = None
                    cur_due = parse_date(t.get("due_parsed")) if t.get("due_parsed") else None
                    if cur_due:
                        delta_map = {"daily": 1, "weekly": 7, "monthly": 30, "yearly": 365}
                        new_due = cur_due + timedelta(days=delta_map.get(t["repeat"], 0))
                    new_task = {
                        "id": get_next_id(tasks), "title": t["title"],
                        "description": t.get("description", ""),
                        "due": new_due.isoformat() if new_due else t.get("due"),
                        "due_raw": None,
                        "due_parsed": new_due.isoformat() if new_due else t.get("due_parsed"),
                        "priority": t.get("priority", 0), "repeat": t.get("repeat"),
                        "done": False, "created": today_str,
                        "notified": None, "done_at": None,
                    }
                    tasks.append(new_task)
                    print(f"   ↻ Repeated: new task #{new_task['id']} due {format_date(new_due) if new_due else '?'}")
                found += 1
                break
        else:
            print(f"Task #{tid} not found")
    if found: save_tasks(tasks)

def cmd_undone(args):
    if not args:
        print("Usage: todo undone <id>"); sys.exit(1)
    tasks = load_tasks()
    for tid_str in args:
        try: tid = int(tid_str)
        except ValueError: print(f"Invalid id: {tid_str}"); continue
        for t in tasks:
            if t["id"] == tid:
                t["done"] = False; t["done_at"] = None
                print(f"↩️  Undone: #{tid} {t['title']}")
                break
    save_tasks(tasks)

def cmd_delete(args):
    if not args:
        print("Usage: todo delete <id> [id...]"); sys.exit(1)
    tasks = load_tasks()
    for tid_str in args:
        try: tid = int(tid_str)
        except ValueError: print(f"Invalid id: {tid_str}"); continue
        for i, t in enumerate(tasks):
            if t["id"] == tid:
                confirm = input(f"Delete #{tid} '{t['title']}'? [y/N]: ").strip().lower()
                if confirm in ("y", "yes"):
                    del tasks[i]; print(f"🗑️  Deleted #{tid}")
                else: print("Cancelled.")
                break
        else:
            print(f"Task #{tid} not found")
    save_tasks(tasks)

def cmd_search(args):
    cmd_list(list(args) + ["--all"])

def cmd_stats(_args):
    tasks = load_tasks()
    alarms = load_alarms()
    total = len(tasks)
    done = sum(1 for t in tasks if t.get("done"))
    pending = total - done
    today = date.today()
    overdue = sum(1 for t in tasks if not t.get("done") and t.get("due_parsed") and t["due_parsed"] < today.isoformat())
    due_today = sum(1 for t in tasks if not t.get("done") and t.get("due_parsed") == today.isoformat())
    high_prio = sum(1 for t in tasks if not t.get("done") and t.get("priority", 0) >= 3)
    active_alarms = sum(1 for a in alarms if a.get("active", True))
    rate = done / total * 100 if total > 0 else 0

    print(f"""
📊 Task Statistics
─────────────────
  Total:       {total}
  Pending:     {pending}
  Done:        {done}
  Overdue:     {overdue}
  Due today:   {due_today}
  High priority: {high_prio}
  Active alarms: {active_alarms}

  Completion rate: {rate:.0f}%  {'🎉' if rate == 100 else '📈'}
""")

def cmd_clear(_args):
    confirm = input("Delete all completed tasks? [y/N]: ").strip().lower()
    if confirm in ("y", "yes"):
        tasks = load_tasks()
        tasks = [t for t in tasks if not t.get("done")]
        save_tasks(tasks)
        print("🗑️  Cleared all done tasks.")
    else:
        print("Cancelled.")

def cmd_export(_args):
    import csv, io
    tasks = load_tasks()
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "id", "title", "description", "due_parsed", "priority", "repeat", "done", "created", "done_at"
    ])
    writer.writeheader()
    for t in tasks:
        writer.writerow({k: t.get(k, "") for k in writer.fieldnames})
    path = CONFIG_DIR / "tasks_export.csv"
    path.write_text(output.getvalue())
    print(f"Exported {len(tasks)} tasks to {path}")

# ═══════════════════════════════════════════════════════════════════════════════
# ALARM FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_alarm(args):
    """Manage alarms. Subcommands: add, list, delete, stop, snooze."""
    if not args:
        cmd_alarm_list([])
        return

    subcmd = args[0]
    sub_args = args[1:]

    subcommands = {
        "add":    cmd_alarm_add,
        "list":   cmd_alarm_list,
        "ls":     cmd_alarm_list,
        "delete": cmd_alarm_delete,
        "del":    cmd_alarm_delete,
        "rm":     cmd_alarm_delete,
        "stop":   cmd_alarm_stop,
        "off":    cmd_alarm_stop,
        "sync":   cmd_alarm_sync,
        "digest": cmd_alarm_digest,
    }

    if subcmd in subcommands:
        subcommands[subcmd](sub_args)
    else:
        print(f"Unknown alarm command: {subcmd}")
        print("Usage: todo alarm [add|list|delete|stop]")

def cmd_alarm_add(args):
    """Add a new alarm."""
    alarms = load_alarms()

    title = " ".join(args) if args else None
    if not title:
        title = input("Alarm title: ").strip()
    if not title:
        print("Error: title is required"); sys.exit(1)

    time_str = input("Time (HH:MM, e.g. 07:30): ").strip()
    parsed = parse_time(time_str)
    if parsed is None:
        print("Error: invalid time format. Use HH:MM (e.g. 07:30)")
        sys.exit(1)
    hour, minute = parsed

    print("Repeat mode:")
    print("  1) One-time (today if time is in the future, otherwise tomorrow)")
    print("  2) Daily")
    print("  3) Weekdays (Mon-Fri)")
    print("  4) Weekly on specific day")
    print("  5) Custom (specific date)")
    mode_str = input("Choice [1-5] (default 1): ").strip() or "1"

    repeat = None
    target_date = None
    days_of_week = None

    if mode_str == "2":
        repeat = "daily"
    elif mode_str == "3":
        repeat = "weekdays"
        days_of_week = [0, 1, 2, 3, 4]  # Mon-Fri
    elif mode_str == "4":
        print("  0=Mon 1=Tue 2=Wed 3=Thu 4=Fri 5=Sat 6=Sun")
        day_str = input("Day number: ").strip()
        try:
            dow = int(day_str)
            if 0 <= dow <= 6:
                repeat = "weekly"
                days_of_week = [dow]
            else:
                print("Invalid day number, using one-time mode.")
        except ValueError:
            print("Invalid input, using one-time mode.")
    elif mode_str == "5":
        date_str = input("Date (YYYY-MM-DD): ").strip()
        target_date = parse_date(date_str)
        if target_date is None:
            print("Invalid date, using one-time (today/tomorrow auto).")

    alarm = {
        "id": get_next_id(alarms),
        "title": title,
        "time": format_time(hour, minute),
        "hour": hour,
        "minute": minute,
        "repeat": repeat,
        "days_of_week": days_of_week,
        "target_date": target_date.isoformat() if target_date else None,
        "active": True,
        "sound": True,
        "vibrate": True,
        "created": date.today().isoformat(),
        "last_fired": None,
    }
    alarms.append(alarm)
    save_alarms(alarms)

    desc = f"every day" if repeat == "daily" else \
           f"weekdays" if repeat == "weekdays" else \
           f"every {'Mon Tue Wed Thu Fri Sat Sun'[days_of_week[0]*4:].split()[0]}" if repeat == "weekly" and days_of_week else \
           f"on {target_date}" if target_date else \
           "one-time"
    print(f"⏰ Alarm #{alarm['id']}: {title} at {format_time(hour, minute)} {desc}")
    if alarmd_sync():
        print("   ↳ 已同步到 alarmd（RTC 唤醒，Termux 关闭也不影响）")

def cmd_alarm_list(_args):
    """List all alarms."""
    alarms = load_alarms()
    if not alarms:
        print("No alarms set.")
        return

    print(f"\n{'ID':>3}  {'Active':>6}  {'Time':>7}  {'Repeat':<12}  {'Title'}")
    print("-" * 55)
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for a in alarms:
        active = "🟢 ON" if a.get("active", True) else "🔴 OFF"
        repeat_display = a.get("repeat") or "one-time"
        if a.get("days_of_week"):
            repeat_display = ", ".join(day_names[d] for d in a["days_of_week"])
        if a.get("target_date"):
            repeat_display = a["target_date"]
        print(f"{a['id']:>3}  {active:>6}  {a['time']:>7}  {repeat_display:<12}  {a['title'][:30]}")
    print(f"\n{alarms.__len__()} alarm(s)")

def cmd_alarm_delete(args):
    """Delete an alarm."""
    if not args:
        print("Usage: todo alarm delete <id>"); sys.exit(1)
    alarms = load_alarms()
    for tid_str in args:
        try: tid = int(tid_str)
        except ValueError: print(f"Invalid id: {tid_str}"); continue
        for i, a in enumerate(alarms):
            if a["id"] == tid:
                print(f"🗑️  Deleted alarm #{tid}: {a['title']} at {a['time']}")
                del alarms[i]
                break
        else:
            print(f"Alarm #{tid} not found")
    save_alarms(alarms)
    alarmd_sync(quiet=True)

def cmd_alarm_stop(args):
    """Stop/disable an alarm."""
    alarms = load_alarms()
    if args:
        try: tid = int(args[0])
        except ValueError: print(f"Invalid id: {args[0]}"); sys.exit(1)
        for a in alarms:
            if a["id"] == tid:
                a["active"] = not a.get("active", True)
                state = "OFF" if not a["active"] else "ON"
                print(f"🔕 Alarm #{tid} turned {state}: {a['title']}")
                break
        else:
            print(f"Alarm #{tid} not found")
    else:
        # stop all
        for a in alarms:
            a["active"] = False
        print(f"🔕 All {len(alarms)} alarm(s) turned OFF")
    save_alarms(alarms)
    alarmd_sync(quiet=True)

def cmd_alarm_sync(_args):
    """手动同步到 alarmd。"""
    if alarmd_sync():
        n = len(alarmd_build_lines())
        print(f"✅ 已同步 {n} 行到 alarmd（含每日 digest）")

def cmd_alarm_digest(args):
    """管理每日任务提醒：todo alarm digest [on|off|HH:MM]"""
    s = load_settings()
    if not args:
        state = "on" if s.get("digest_enabled", True) else "off"
        print(f"每日任务提醒: {state}，时间 {s.get('digest_time', '08:30')}")
        print("用法: todo alarm digest [on|off|HH:MM]")
        return
    a = args[0].lower()
    if a in ("on", "off"):
        s["digest_enabled"] = (a == "on")
    else:
        parsed = parse_time(a)
        if not parsed:
            print("无效时间，用 HH:MM"); sys.exit(1)
        s["digest_time"] = format_time(*parsed)
    save_settings(s)
    alarmd_sync()
    cmd_alarm_digest([])

# ═══════════════════════════════════════════════════════════════════════════════
# REMINDER / NOTIFICATION ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_notify(_args):
    """Manual check: send notifications for due tasks and firing alarms."""
    notified = check_and_notify(send=True)
    if notified:
        print(f"Sent {notified} notification(s)")
    else:
        print("No notifications needed right now.")

def check_and_notify(send=True):
    """Check tasks and alarms, return count of notifications sent."""
    now = datetime.now()
    today = date.today()
    notified = 0

    # ── Check alarms ──
    alarms = load_alarms()
    for a in alarms:
        if not a.get("active", True):
            continue
        h, m = a.get("hour"), a.get("minute")
        if h is None or m is None:
            continue

        # Check if alarm should fire now
        should_fire = False
        if a.get("repeat") == "daily":
            if now.hour == h and now.minute == m:
                last = a.get("last_fired")
                if last != today.isoformat():
                    should_fire = True
        elif a.get("repeat") == "weekdays" and a.get("days_of_week"):
            if now.weekday() in a["days_of_week"] and now.hour == h and now.minute == m:
                last = a.get("last_fired")
                if last != today.isoformat():
                    should_fire = True
        elif a.get("repeat") == "weekly" and a.get("days_of_week"):
            if now.weekday() in a["days_of_week"] and now.hour == h and now.minute == m:
                last = a.get("last_fired")
                if last != today.isoformat():
                    should_fire = True
        elif a.get("target_date"):
            target = parse_date(a["target_date"])
            if target and target == today and now.hour == h and now.minute == m:
                last = a.get("last_fired")
                if last != today.isoformat():
                    should_fire = True
        else:
            # one-time: fire at exact time today (or first occurrence after creation)
            if now.hour == h and now.minute == m:
                last = a.get("last_fired")
                if last != today.isoformat():
                    should_fire = True

        if should_fire and send:
            title = f"⏰ ALARM: {a['title']}"
            content = f"Time: {a['time']} — {'Tap to dismiss'}"
            notify(
                title, content,
                vibrate=a.get("vibrate", True),
                sound=a.get("sound", True),
                ongoing=True,
                alarm_mode=True,
                notify_id=90000 + a["id"],
            )
            a["last_fired"] = today.isoformat()
            notified += 1

    if notified and alarms:
        save_alarms(alarms)

    # ── Check tasks ──
    tasks = load_tasks()
    for t in tasks:
        if t.get("done"):
            continue
        dp = t.get("due_parsed")
        if not dp:
            continue
        try:
            due_date = parse_date(dp)
        except Exception:
            continue
        if due_date is None:
            continue

        # Due today
        if due_date == today:
            last = t.get("notified")
            if last != today.isoformat() and send:
                desc = t.get("description", "")
                prio = t.get("priority", 0)
                if prio >= 2:
                    notify(f"🔔 HIGH: {t['title']}", f"Due today! {desc}" if desc else "Due today!", vibrate=True)
                else:
                    notify(f"📋 Reminder: {t['title']}", f"Due today. {desc}" if desc else "Due today.")
                t["notified"] = today.isoformat()
                notified += 1
        # Overdue
        elif due_date < today:
            last = t.get("notified")
            if last != today.isoformat() and send:
                notify(f"⚠️ Overdue: {t['title']}", f"Was due {format_date(due_date)}", vibrate=True)
                t["notified"] = today.isoformat()
                notified += 1

    if notified and tasks:
        save_tasks(tasks)

    return notified

def cmd_reminders(_args):
    """Set up periodic reminder checking via termux-job-scheduler."""
    script_path = os.path.abspath(__file__)
    job_id = 42001

    print("Setting up reminder & alarm scheduler...")
    subprocess.run(
        ["termux-job-scheduler", "--cancel", str(job_id)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    # Run every 1 minute for alarm precision (minimum allowed by Android N+ is 15 min, but we try)
    result = subprocess.run([
        "termux-job-scheduler",
        "-s", script_path,
        "--job-id", str(job_id),
        "--period-ms", str(60 * 1000),  # 1 minute for alarms
        "--persisted", "true",
        "--network", "any",
        "--battery-not-low", "false",
    ], capture_output=True, text=True)

    if result.returncode == 0:
        print("✅ Reminder job scheduled! Checks every minute for alarms & reminders.")
        print("   View pending jobs: termux-job-scheduler --pending")
    else:
        print(f"⚠️  Scheduling returned: {result.stderr}")
        print("   Note: Minimum period on modern Android is 15 minutes.")
        print("   For precise alarms, use 'todo alarm-daemon' in a separate session.")

    settings = load_settings()
    settings["job_scheduled"] = True
    settings["job_id"] = job_id
    save_settings(settings)

def cmd_reminders_stop(_args):
    settings = load_settings()
    job_id = settings.get("job_id", 42001)
    result = subprocess.run(
        ["termux-job-scheduler", "--cancel", str(job_id)],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print("✅ Reminder job cancelled.")
        settings["job_scheduled"] = False
        save_settings(settings)
    else:
        print(f"Could not cancel: {result.stderr}")

def cmd_reminders_status(_args):
    result = subprocess.run(
        ["termux-job-scheduler", "--pending"],
        capture_output=True, text=True,
    )
    print(result.stdout if result.stdout else "No pending jobs.")
    settings = load_settings()
    if settings.get("job_scheduled"):
        print(f"Todo reminder configured (ID: {settings.get('job_id', 42001)})")

# ═══════════════════════════════════════════════════════════════════════════════
# ALARM DAEMON - precise alarms via sleep-based polling
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_alarm_daemon(_args):
    """
    Run a daemon that polls every 30 seconds for precise alarm firing.
    This runs in the foreground - use in a tmux/screen session or with nohup.
    Notifies immediately when an alarm's minute matches.
    """
    print("⏰ Alarm daemon 已由 root 模块 alarmd 接管（RTC 唤醒，无需前台进程）。")
    print("   todo alarm add/delete/stop 自动同步；todo alarm sync 手动重同步。")
    return

    def handle_signal(sig, frame):
        print("\nAlarm daemon stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    last_check_date = None
    fired_this_minute = set()

    while True:
        now = datetime.now()
        today = date.today()

        # Reset fired tracking each new minute
        current_minute_key = (now.hour, now.minute)
        if last_check_date != today:
            fired_this_minute.clear()
            last_check_date = today

        # Check all active alarms
        alarms = load_alarms()
        for a in alarms:
            if not a.get("active", True):
                continue
            h, m = a.get("hour"), a.get("minute")
            if h is None or m is None:
                continue

            if now.hour != h or now.minute != m:
                continue

            # Already fired this minute?
            if a["id"] in fired_this_minute:
                continue

            # Determine if this alarm applies today
            should_fire = False
            if a.get("repeat") == "daily":
                should_fire = True
            elif a.get("repeat") == "weekdays" and a.get("days_of_week"):
                if now.weekday() in a["days_of_week"]:
                    should_fire = True
            elif a.get("repeat") == "weekly" and a.get("days_of_week"):
                if now.weekday() in a["days_of_week"]:
                    should_fire = True
            elif a.get("target_date"):
                target = parse_date(a["target_date"])
                if target and target == today:
                    should_fire = True
            else:
                # one-time: first occurrence
                should_fire = True

            if not should_fire:
                continue

            # Fire the alarm!
            title = f"⏰ ALARM: {a['title']}"
            content = f"Time: {a['time']}"
            notify(
                title, content,
                vibrate=a.get("vibrate", True),
                sound=a.get("sound", True),
                ongoing=True,
                alarm_mode=True,
                notify_id=90000 + a["id"],
            )
            print(f"[{now.strftime('%H:%M:%S')}] 🔔 Alarm: {a['title']}")
            a["last_fired"] = today.isoformat()
            fired_this_minute.add(a["id"])

        if fired_this_minute:
            save_alarms(alarms)

        # Also run task notifications every 5 minutes
        if now.minute % 5 == 0 and current_minute_key not in fired_this_minute:
            check_and_notify(send=True)

        time.sleep(30)

# ─── help ─────────────────────────────────────────────────────────────────────

def cmd_help(_args):
    print("""
📋 TODO & CALENDAR & ALARM CLI
═══════════════════════════════════════════════════════════════════

TASKS
  todo add                 Add a new task (interactive)
  todo list                List pending tasks
  todo list --all / -a     List all tasks (including done)
  todo list --today        Tasks due today
  todo list --week         Tasks due this week
  todo list --month        Tasks due this month
  todo list --overdue      Overdue tasks
  todo list --done / -d    Completed tasks
  todo list <keyword>      Search tasks
  todo calendar            Calendar view (current month)
  todo calendar prev/next  Previous/next month
  todo calendar YYYY-MM    Specific month
  todo edit <id>           Edit a task
  todo done <id>           Mark task as done
  todo undone <id>         Unmark done
  todo delete <id>         Delete a task
  todo stats               Task statistics
  todo clear               Delete all completed tasks
  todo export              Export tasks to CSV
  todo notify              Check & send notifications now

ALARMS ⏰（后端 = alarmd root 守护，RTC 级精度）
  todo alarm               List all alarms
  todo alarm add           Add a new alarm (interactive)
  todo alarm delete <id>   Delete an alarm
  todo alarm stop [id]     Turn alarm OFF (or all if no ID)
  todo alarm sync          手动重新同步到 alarmd
  todo alarm digest [on|off|HH:MM]  每日任务提醒（默认 08:30）

SCHEDULING
  todo reminders-setup     Set up automatic reminder checks
  todo reminders-stop      Stop automatic checks
  todo reminders-status    Check scheduling status

Data: ~/.todo/tasks.json  ~/.todo/alarms.json
""")

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

COMMANDS = {
    "add":              cmd_add,
    "list":             cmd_list,
    "ls":               cmd_list,
    "calendar":         cmd_calendar,
    "cal":              cmd_calendar,
    "edit":             cmd_edit,
    "done":             cmd_done,
    "undone":           cmd_undone,
    "delete":           cmd_delete,
    "del":              cmd_delete,
    "rm":               cmd_delete,
    "search":           cmd_search,
    "stats":            cmd_stats,
    "notify":           cmd_notify,
    "alarm":            cmd_alarm,
    "alarm-daemon":     cmd_alarm_daemon,
    "reminders-setup":  cmd_reminders,
    "reminders-stop":   cmd_reminders_stop,
    "reminders-status": cmd_reminders_status,
    "clear":            cmd_clear,
    "export":           cmd_export,
    "help":             cmd_help,
    "--help":           cmd_help,
    "-h":               cmd_help,
}

def main():
    # When invoked by termux-job-scheduler, run notification check silently and exit
    if len(sys.argv) > 1 and sys.argv[1] == "--daemon-check":
        check_and_notify(send=True)
        return

    if len(sys.argv) < 2:
        cmd_list([])
        return

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd in COMMANDS:
        COMMANDS[cmd](args)
    else:
        print(f"Unknown command: {cmd}")
        print("Run 'todo help' for available commands.")
        sys.exit(1)

if __name__ == "__main__":
    main()
