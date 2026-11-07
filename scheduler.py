# Deadline Watchdog – author: jproucil-byte – https://github.com/jproucil-byte/Deadline-Watchdog
"""Desktop notifications and setting up the daily reminder check (`watchdog.py notify`) on this computer.

    Windows  Task Scheduler: every day at 9:00 and at log on; a missed run (computer off) runs as soon
             as possible. Runs pythonw.exe, so no console window flashes.
    macOS    a LaunchAgent: every day at 9:00 and at log in.
    Linux    desktop autostart (~/.config/autostart): at every log in.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape as xml_escape

import i18n

HERE = Path(__file__).resolve().parent
TASK_NAME = i18n.APP_NAME                                   # Windows Task Scheduler
MAC_LABEL = "com.github.jproucil-byte." + i18n.APP_SLUG     # macOS LaunchAgent
LINUX_FILE = i18n.APP_SLUG + "-notify.desktop"              # Linux autostart entry
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ScheduleError(Exception):
    pass


# --------------------------------------------------------------------------
# Desktop notifications
# --------------------------------------------------------------------------
# A toast in the Windows 10/11 notification centre. It needs an app id that Windows knows; the one of
# Windows PowerShell is always registered.
_TOAST = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$x = New-Object Windows.Data.Xml.Dom.XmlDocument
$x.LoadXml('<toast><visual><binding template="ToastGeneric"><text></text><text></text></binding></visual></toast>')
$t = $x.GetElementsByTagName('text')
$t.Item(0).AppendChild($x.CreateTextNode($env:WATCHDOG_TITLE)) | Out-Null
$t.Item(1).AppendChild($x.CreateTextNode($env:WATCHDOG_TEXT)) | Out-Null
$n = [Windows.UI.Notifications.ToastNotification]::new($x)
$id = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($id).Show($n)
"""

# The old-style balloon, for systems where the toast fails.
_BALLOON = ("Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing;"
            "$n=New-Object System.Windows.Forms.NotifyIcon;"
            "$n.Icon=[System.Drawing.SystemIcons]::Information;$n.Visible=$true;"
            "$n.ShowBalloonTip(15000,$env:WATCHDOG_TITLE,$env:WATCHDOG_TEXT,"
            "[System.Windows.Forms.ToolTipIcon]::Info);Start-Sleep -Seconds 16;$n.Dispose()")


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
            env = dict(os.environ, WATCHDOG_TITLE=title, WATCHDOG_TEXT=text)
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command"]
            try:
                subprocess.run(cmd + [_TOAST], env=env, check=True, timeout=30, capture_output=True,
                               creationflags=_NO_WINDOW)
                return True
            except (OSError, subprocess.SubprocessError):
                pass
            # the balloon has to stay alive while it is shown, so it isn't waited for
            subprocess.Popen(cmd + [_BALLOON], env=env, creationflags=_NO_WINDOW,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        if shutil.which("notify-send"):
            subprocess.run(["notify-send", "--app-name=" + i18n.APP_NAME, "--", title, text],
                           check=True, timeout=15, capture_output=True)
            return True
    except (OSError, subprocess.SubprocessError):
        return False
    return False


# --------------------------------------------------------------------------
# The command that is scheduled
# --------------------------------------------------------------------------
def kind() -> Optional[str]:
    """'windows', 'mac', 'linux' or None when reminders can't be scheduled from the app here."""
    return {"Windows": "windows", "Darwin": "mac", "Linux": "linux"}.get(platform.system())


def _python(windowless: bool) -> str:
    exe = Path(sys.executable)
    if windowless and os.name == "nt":
        w = exe.with_name("pythonw.exe")
        if w.exists():
            return str(w)
    return str(exe)


def command(data_dir, windowless: bool = True) -> list:
    return [_python(windowless), str(HERE / "watchdog.py"), "--data", str(data_dir), "notify", "--quiet"]


def cli_prefix(data_dir) -> str:
    """How to run the program in a terminal on this computer (shown in the app)."""
    args = [_python(False), str(HERE / "watchdog.py")]
    if Path(data_dir).resolve() != (HERE / "data").resolve():
        args += ["--data", str(data_dir)]
    return _quote(args)


def command_line(data_dir) -> str:
    return _quote(command(data_dir, windowless=False))


def _quote(args: list) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(args)
    import shlex
    return " ".join(shlex.quote(a) for a in args)


def suggested_backup_dir() -> str:
    """A cloud-synced folder for automatic backups, if this computer has one."""
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        base = os.environ.get(var)
        if base and Path(base).is_dir():
            return str(Path(base) / (i18n.APP_NAME + " backups"))
    for name in ("Dropbox", "Google Drive", "iCloud Drive"):
        base = Path.home() / name
        if base.is_dir():
            return str(base / (i18n.APP_NAME + " backups"))
    return ""


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------
def _schtasks(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, timeout=30, creationflags=_NO_WINDOW)


def _decode(data: bytes) -> str:
    for enc in ("utf-8", "mbcs" if os.name == "nt" else "latin-1", "latin-1"):
        try:
            return data.decode(enc).strip()
        except (UnicodeDecodeError, LookupError):
            continue
    return ""


def _task_xml(data_dir, with_logon: bool) -> str:
    user = os.environ.get("USERNAME", "")
    domain = os.environ.get("USERDOMAIN", "")
    who = xml_escape(f"{domain}\\{user}" if domain else user)
    cmd = command(data_dir)
    logon = (f"<LogonTrigger><Enabled>true</Enabled><UserId>{who}</UserId><Delay>PT2M</Delay></LogonTrigger>"
             if with_logon else "")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Author>{xml_escape(i18n.APP_NAME)}</Author>
    <Description>{xml_escape(i18n.APP_NAME)}: daily check of expiry dates ({xml_escape(i18n.APP_URL)})</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger><StartBoundary>2020-01-01T09:00:00</StartBoundary><Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger>
    {logon}
  </Triggers>
  <Principals><Principal id="Author"><UserId>{who}</UserId><LogonType>InteractiveToken</LogonType>
    <RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT15M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author"><Exec>
    <Command>{xml_escape(cmd[0])}</Command>
    <Arguments>{xml_escape(subprocess.list2cmdline(cmd[1:]))}</Arguments>
    <WorkingDirectory>{xml_escape(str(HERE))}</WorkingDirectory>
  </Exec></Actions>
</Task>
"""


def _win_install(data_dir, name: str) -> None:
    last = ""
    for with_logon in (True, False):        # a log-on trigger may need rights the user doesn't have
        fd, path = tempfile.mkstemp(suffix=".xml")
        os.close(fd)
        try:
            Path(path).write_text(_task_xml(data_dir, with_logon), encoding="utf-16")
            r = _schtasks("/Create", "/TN", name, "/XML", path, "/F")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        if r.returncode == 0:
            return
        last = _decode(r.stderr) or _decode(r.stdout)
    raise ScheduleError(last or "schtasks failed")


# --------------------------------------------------------------------------
# macOS and Linux
# --------------------------------------------------------------------------
def _mac_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{MAC_LABEL}.plist"


def _linux_file() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "autostart" / LINUX_FILE


def _plist(data_dir) -> str:
    args = "".join(f"<string>{xml_escape(a)}</string>" for a in command(data_dir))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{MAC_LABEL}</string>
  <key>ProgramArguments</key><array>{args}</array>
  <key>WorkingDirectory</key><string>{xml_escape(str(HERE))}</string>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
  <key>RunAtLoad</key><true/>
</dict></plist>
"""


def _desktop_entry(data_dir) -> str:
    def q(a: str) -> str:                   # quoting rules of the desktop entry specification
        return '"' + "".join("\\" + ch if ch in '"`$\\' else ch for ch in a) + '"'
    return ("[Desktop Entry]\nType=Application\n"
            f"Name={i18n.APP_NAME} reminders\n"
            f"Exec={' '.join(q(a) for a in command(data_dir))}\n"
            "NoDisplay=true\nX-GNOME-Autostart-enabled=true\n")


# --------------------------------------------------------------------------
# Public interface
# --------------------------------------------------------------------------
def status(data_dir=None, name: str = TASK_NAME) -> bool:
    """True when the reminder check is scheduled."""
    k = kind()
    try:
        if k == "windows":
            return _schtasks("/Query", "/TN", name).returncode == 0
        if k == "mac":
            return _mac_plist().exists()
        if k == "linux":
            return _linux_file().exists()
    except (OSError, subprocess.SubprocessError):
        return False
    return False


def install(data_dir, name: str = TASK_NAME) -> str:
    """Schedules `watchdog.py notify` for this data folder. Returns kind(). Raises ScheduleError."""
    k = kind()
    try:
        if k == "windows":
            _win_install(data_dir, name)
        elif k == "mac":
            plist = _mac_plist()
            plist.parent.mkdir(parents=True, exist_ok=True)
            if plist.exists():
                subprocess.run(["launchctl", "unload", str(plist)], capture_output=True, timeout=30)
            plist.write_text(_plist(data_dir), encoding="utf-8")
            r = subprocess.run(["launchctl", "load", "-w", str(plist)], capture_output=True, timeout=30)
            if r.returncode != 0:
                raise ScheduleError(_decode(r.stderr) or "launchctl failed")
        elif k == "linux":
            f = _linux_file()
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(_desktop_entry(data_dir), encoding="utf-8")
        else:
            raise ScheduleError(platform.system())
    except (OSError, subprocess.SubprocessError) as e:
        raise ScheduleError(str(e))
    return k


def remove(name: str = TASK_NAME) -> bool:
    """Removes the scheduled check. Returns False when there was nothing to remove."""
    k = kind()
    try:
        if k == "windows":
            if not status(name=name):
                return False
            r = _schtasks("/Delete", "/TN", name, "/F")
            if r.returncode != 0:
                raise ScheduleError(_decode(r.stderr) or "schtasks failed")
            return True
        if k == "mac":
            plist = _mac_plist()
            if not plist.exists():
                return False
            subprocess.run(["launchctl", "unload", "-w", str(plist)], capture_output=True, timeout=30)
            plist.unlink()
            return True
        if k == "linux":
            f = _linux_file()
            if not f.exists():
                return False
            f.unlink()
            return True
    except (OSError, subprocess.SubprocessError) as e:
        raise ScheduleError(str(e))
    return False
