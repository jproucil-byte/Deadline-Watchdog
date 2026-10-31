#!/usr/bin/env python3
# Deadline Watchdog – author: jproucil-byte – https://github.com/jproucil-byte/Deadline-Watchdog
"""Deadline Watchdog – tracks expiry dates of insurance, vehicle inspections, warranties, contracts, IDs and more.

Without a command it starts the web interface (on this computer only). Other commands:
  check     list what is expiring or already expired
  notify    show a desktop notification when a deadline is near (schedule it, see README)
  export    save a calendar file (.ics) for your phone
  backup    save a backup (database + files) to a zip file
  restore   restore data from a backup
  analyze   show what the program reads from one file (for trying things out)
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import docparse  # noqa: E402
import i18n  # noqa: E402
import store as S  # noqa: E402
import web  # noqa: E402

VERSION = "1.1"


def say(text: str = "") -> None:
    print(text)


# --------------------------------------------------------------------------
# Desktop notifications
# --------------------------------------------------------------------------
def desktop_notify(title: str, text: str) -> bool:
    """Shows a desktop notification. Returns False when this system can't."""
    system = platform.system()
    try:
        if system == "Darwin" and shutil.which("osascript"):
            subprocess.run(["osascript", "-e", "on run argv",
                            "-e", "display notification (item 1 of argv) with title (item 2 of argv)",
                            "-e", "end run", text, title],
                           check=True, timeout=15, capture_output=True)
            return True
        if system == "Windows" and shutil.which("powershell"):
            script = ("Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing;"
                      "$n=New-Object System.Windows.Forms.NotifyIcon;"
                      "$n.Icon=[System.Drawing.SystemIcons]::Information;$n.Visible=$true;"
                      "$n.ShowBalloonTip(15000,$env:WATCHDOG_TITLE,$env:WATCHDOG_TEXT,"
                      "[System.Windows.Forms.ToolTipIcon]::Info);Start-Sleep -Seconds 16;$n.Dispose()")
            env = dict(os.environ, WATCHDOG_TITLE=title, WATCHDOG_TEXT=text)
            subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
                             env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return True
        if shutil.which("notify-send"):
            subprocess.run(["notify-send", "--app-name=" + i18n.APP_NAME, "--", title, text],
                           check=True, timeout=15, capture_output=True)
            return True
    except (OSError, subprocess.SubprocessError):
        return False
    return False


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------
def cmd_serve(store: S.Store, args) -> int:
    web.serve(store, args.port, not args.no_browser)
    return 0


def cmd_check(store: S.Store, args) -> int:
    lang = store.get_lang()
    today = dt.date.today()
    groups = {"expired": [], "soon": [], "ok": [], "none": []}
    for r in store.list_documents():
        st = S.classify(r["expires"], S.parse_remind_days(r["remind_days"]), today)
        groups[st["key"]].append((r, st))
    total = sum(len(v) for v in groups.values())
    say(i18n.t(lang, "cli.title", app=i18n.APP_NAME, date=i18n.fmt_date(today, lang),
               docs=i18n.tn(lang, "cli.docs", total)))
    for key in ("expired", "soon", "ok", "none"):
        items = groups[key]
        if not items:
            continue
        label = i18n.t(lang, "cli.g." + key)
        if key in ("ok", "none") and not args.all:
            say("\n" + i18n.t(lang, "cli.more", label=label, n=len(items)))
            continue
        say("\n" + label)
        width = max(len(r["title"]) for r, _ in items)
        for r, st in items:
            when = (f"{i18n.fmt_date(r['expires'], lang)}  {i18n.days_phrase(lang, st['days'])}"
                    if r["expires"] else "")
            say(f"  {r['title']:<{width}}  {when}")
    if total == 0:
        say("\n" + i18n.t(lang, "cli.empty"))
    return 0


def cmd_notify(store: S.Store, args) -> int:
    lang = store.get_lang()
    if args.test:
        ok = desktop_notify(i18n.APP_NAME, i18n.t(lang, "cli.test_text"))
        say(i18n.t(lang, "cli.test_ok" if ok else "cli.test_fail"))
        return 0 if ok else 1
    items = store.due_notifications()
    if not items:
        if not args.quiet:
            say(i18n.t(lang, "cli.nothing_due"))
        return 0
    lines = [i18n.item_line(lang, i["doc"]["title"], i["doc"]["expires"], i["days"]) for i in items]
    for line in lines:
        say(line)
    if args.dry_run:
        say(i18n.t(lang, "cli.dry_run"))
        return 0
    n = len(items)
    title = (i18n.APP_NAME + ": " + items[0]["doc"]["title"]) if n == 1 \
        else i18n.tn(lang, "cli.notify_title", n, app=i18n.APP_NAME)
    body = lines[0] if n == 1 else "\n".join(lines[:5]) + ("\n" + i18n.t(lang, "cli.notify_more", n=n - 5) if n > 5 else "")
    if desktop_notify(title, body):
        store.mark_notified(items)
    else:
        say("\n" + i18n.t(lang, "cli.notify_unavailable"))
    return 0


def cmd_export(store: S.Store, args) -> int:
    lang = store.get_lang()
    out = Path(args.file or f"{i18n.APP_SLUG}.ics")
    out.write_bytes(S.build_ics(store.list_documents(), lang=lang).encode("utf-8"))
    say(i18n.t(lang, "cli.exported", path=out.resolve()))
    return 0


def cmd_backup(store: S.Store, args) -> int:
    lang = store.get_lang()
    out = Path(args.file or f"{i18n.APP_SLUG}-backup-{dt.date.today().isoformat()}.zip")
    store.backup_to(out)
    say(i18n.t(lang, "cli.backup", path=out.resolve(), kb=f"{out.stat().st_size / 1024:.0f}"))
    return 0


def cmd_restore(store: S.Store, args) -> int:
    lang = store.get_lang()
    src = Path(args.file)
    if not src.is_file():
        say(i18n.t(lang, "cli.no_file", path=src))
        return 1
    if not args.yes:
        say(i18n.t(lang, "cli.restore_warn1"))
        say(i18n.t(lang, "cli.restore_warn2"))
        return 1
    old = store.restore_from(src)
    say(i18n.t(lang, "cli.restored"))
    say(f"  {old}")
    return 0


def cmd_analyze(_store, args) -> int:
    lang = i18n.norm_lang(args.lang or i18n.env("LANG"))
    path = Path(args.file)
    if not path.is_file():
        say(i18n.t(lang, "cli.no_file", path=path))
        return 1
    res = docparse.analyze(str(path), path.name, lang=lang, date_order=args.date_order)
    if args.json:
        say(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    L = lambda key, **kw: i18n.t(lang, key, **kw)  # noqa: E731
    say(f"{L('cli.a.method'):<18}{res['method']}")
    say(f"{L('cli.a.title'):<18}{res['title']}")
    say(f"{L('cli.a.category'):<18}{i18n.category_label(lang, res['category'])}")
    if res["expires"]:
        say(f"{L('cli.a.expires'):<18}{i18n.fmt_date(res['expires'], lang)}  "
            f"({L('cli.a.conf')}: {i18n.conf_label(lang, res['confidence'])}; "
            f"{i18n.reason_text(lang, res['reason'])})")
    else:
        say(f"{L('cli.a.expires'):<18}{L('cli.a.none')}")
    for c in res["candidates"]:
        say(f"   {L('cli.a.cand')} {i18n.fmt_date(c['date'], lang):<14} {c['score']:>5.1f}  {c['why']}")
    for n in res["notes"]:
        say(f"{L('cli.a.note')} {i18n.note_text(lang, n)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="watchdog.py", description=f"{i18n.APP_NAME} – never miss an expiry date again. By {i18n.APP_AUTHOR}.",
        formatter_class=argparse.RawDescriptionHelpFormatter)       # keeps --version on one line (the URL must not wrap)
    p.add_argument("--data", help="data folder (default: the 'data' folder next to the program, or WATCHDOG_DATA)")
    p.add_argument("--lang", choices=sorted(i18n.LANGS), help="language for this run (the saved setting is used otherwise)")
    p.add_argument("--version", action="version", version=f"{i18n.APP_NAME} {VERSION} – by {i18n.APP_AUTHOR} ({i18n.APP_URL})")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="start the web interface (default)")
    s.add_argument("--port", type=int, default=web.DEFAULT_PORT)
    s.add_argument("--no-browser", action="store_true", help="don't open the browser")
    s.set_defaults(func=cmd_serve)
    c = sub.add_parser("check", help="print an overview of your deadlines")
    c.add_argument("--all", action="store_true", help="include documents that are fine")
    c.set_defaults(func=cmd_check)
    n = sub.add_parser("notify", help="announce approaching deadlines on the desktop")
    n.add_argument("--dry-run", action="store_true", help="only print, don't announce or mark anything")
    n.add_argument("--quiet", action="store_true", help="print nothing when there is nothing to report")
    n.add_argument("--test", action="store_true", help="send a test notification")
    n.set_defaults(func=cmd_notify)
    e = sub.add_parser("export", help="save a calendar file (.ics)")
    e.add_argument("file", nargs="?")
    e.set_defaults(func=cmd_export)
    b = sub.add_parser("backup", help="save a backup to a zip file")
    b.add_argument("file", nargs="?")
    b.set_defaults(func=cmd_backup)
    r = sub.add_parser("restore", help="restore data from a backup")
    r.add_argument("file")
    r.add_argument("--yes", action="store_true", help="confirm that the current data may be replaced")
    r.set_defaults(func=cmd_restore)
    a = sub.add_parser("analyze", help="show what the program reads from one file")
    a.add_argument("file")
    a.add_argument("--json", action="store_true")
    a.add_argument("--date-order", choices=list(i18n.DATE_ORDERS),
                   help="how to read 03/04/2027: mdy = March 4 (US), dmy = 3 April")
    a.set_defaults(func=cmd_analyze)
    return p


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(argv)
    if not args.cmd:                      # no command = serve (global options are already read)
        args = parser.parse_args(argv + ["serve"])
    data_dir = args.data or i18n.env("DATA") or str(HERE / "data")
    store = None
    try:
        store = None if args.cmd == "analyze" else S.Store(data_dir, lang=args.lang)
        return args.func(store, args)
    except BrokenPipeError:               # somebody closed the output (e.g. `| head`) – not an error
        with contextlib.suppress(OSError, ValueError):
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except S.ValidationError as e:
        lang = store.get_lang() if store else i18n.DEFAULT_LANG
        say(i18n.t(lang, "cli.error", msg=e.text(lang)))
        return 1
    except OSError as e:
        say(i18n.t(i18n.DEFAULT_LANG, "cli.error", msg=e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
