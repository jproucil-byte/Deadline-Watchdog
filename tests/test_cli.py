# Deadline Watchdog – author: jproucil-byte – https://github.com/jproucil-byte/Deadline-Watchdog
import datetime as dt
import os
import re
import subprocess
import sys
import tempfile
import unittest
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import store as S  # noqa: E402


def iso(days):
    return (dt.date.today() + dt.timedelta(days=days)).isoformat()


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("WATCHDOG_", "KEEPER_", "HLIDAC_"))}
        self.env["PYTHONIOENCODING"] = "utf-8"

    def run_cli(self, *args, check=True, cwd=None):
        p = subprocess.run([sys.executable, str(ROOT / "watchdog.py"), "--data", str(self.data), *args],
                           capture_output=True, text=True, encoding="utf-8", env=self.env, cwd=cwd or self.root,
                           timeout=60)
        if check:
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def seed(self):
        s = S.Store(self.data)
        s.add_document("Car insurance", "insurance", iso(5), "30,7")
        s.add_document("Old passport", "id", iso(-10), "90")
        s.add_document("Fine one", "contract", iso(400), "30")
        s.add_document("Undated")
        return s

    def test_version_and_help(self):
        p = self.run_cli("--version")
        self.assertRegex(p.stdout, r"Deadline Watchdog \d+\.\d+")
        self.assertIn("jproucil-byte", p.stdout)
        self.assertIn("github.com/jproucil-byte/Deadline-Watchdog", p.stdout)
        self.assertIn("notify", self.run_cli("--help").stdout)

    def test_check_in_english_and_czech(self):
        self.seed()
        out = self.run_cli("check").stdout
        self.assertIn("EXPIRED", out.upper())
        self.assertIn("Old passport", out)
        self.assertIn("10 days ago", out)
        self.assertIn("in 5 days", out)
        self.assertNotIn("Fine one", out)                       # only listed with --all
        self.assertIn("Fine one", self.run_cli("check", "--all").stdout)
        cs = self.run_cli("--lang", "cs", "check").stdout
        self.assertIn("před 10 dny", cs)
        self.assertIn("za 5 dní", cs)
        self.assertNotIn("days ago", cs)

    def test_empty_check(self):
        out = self.run_cli("check").stdout
        self.assertIn("0 documents", out)
        self.assertIn("add", out.lower())

    def test_notify_dry_run_does_not_mark_anything(self):
        s = self.seed()
        first = self.run_cli("notify", "--dry-run").stdout
        self.assertIn("Car insurance", first)
        self.assertIn("Old passport", first)
        again = self.run_cli("notify", "--dry-run").stdout
        self.assertEqual(first, again)
        self.assertEqual(len(s.due_notifications()), 2)

    def test_notify_quiet_when_nothing_is_due(self):
        S.Store(self.data).add_document("Far away", "other", iso(900), "30")
        self.assertEqual(self.run_cli("notify", "--quiet").stdout.strip(), "")
        self.assertNotEqual(self.run_cli("notify").stdout.strip(), "")

    def test_export_backup_restore(self):
        s = self.seed()
        doc = s.list_documents()[0]["id"]
        s.add_attachment(doc, "a.txt", b"hello")
        ics = self.root / "out.ics"
        self.run_cli("export", str(ics))
        text = ics.read_bytes().decode("utf-8")
        self.assertEqual(text.count("BEGIN:VEVENT"), 3)
        self.assertIn("\r\n", text)
        zipf = self.root / "b.zip"
        self.run_cli("backup", str(zipf))
        with zipfile.ZipFile(zipf) as z:
            self.assertIn("watchdog.db", z.namelist())
        s.add_document("Added after the backup")
        refused = self.run_cli("restore", str(zipf), check=False)
        self.assertEqual(refused.returncode, 1)                   # needs --yes
        self.assertEqual(len(S.Store(self.data).list_documents()), 5)
        self.run_cli("restore", str(zipf), "--yes")
        self.assertEqual(len(S.Store(self.data).list_documents()), 4)
        self.assertTrue(any(p.name.startswith("data-before-restore-") for p in self.root.iterdir()))
        missing = self.run_cli("restore", str(self.root / "nope.zip"), "--yes", check=False)
        self.assertEqual(missing.returncode, 1)
        bad = self.root / "bad.zip"
        bad.write_bytes(b"not a zip")
        r = self.run_cli("restore", str(bad), "--yes", check=False)
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stdout + r.stderr)

    def test_analyze(self):
        f = self.root / "policy.txt"
        f.write_text("Insurance policy\nExpiration date: 03/04/2027\n", encoding="utf-8")
        out = self.run_cli("analyze", str(f)).stdout
        self.assertIn("Mar 4, 2027", out)
        self.assertIn("can be read two ways", out)
        self.assertIn("Apr 3, 2027", self.run_cli("analyze", "--date-order", "dmy", str(f)).stdout)
        import json
        data = json.loads(self.run_cli("analyze", "--json", "--date-order", "dmy", str(f)).stdout)
        self.assertEqual((data["expires"], data["category"]), ("2027-04-03", "insurance"))
        cs = self.run_cli("--lang", "cs", "analyze", str(f)).stdout
        self.assertIn("3. 4. 2027", cs)                           # Czech default reads 03/04/2027 as 3 April
        self.assertIn("nebo", cs)
        self.assertEqual(self.run_cli("analyze", str(self.root / "missing.pdf"), check=False).returncode, 1)

    def test_old_czech_data_folder_is_picked_up(self):
        legacy = self.data
        legacy.mkdir()
        import sqlite3
        con = sqlite3.connect(legacy / "hlidac.db")
        con.executescript("""
CREATE TABLE documents(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'ostatni',
 expires TEXT, remind_days TEXT NOT NULL DEFAULT '30,14,7,1', note TEXT NOT NULL DEFAULT '', body TEXT NOT NULL DEFAULT '',
 search TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE attachments(id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id INTEGER NOT NULL, filename TEXT NOT NULL,
 stored TEXT NOT NULL UNIQUE, size INTEGER NOT NULL, mime TEXT NOT NULL, added TEXT NOT NULL);
CREATE TABLE notified(doc_id INTEGER NOT NULL, expires TEXT NOT NULL, threshold INTEGER NOT NULL, at TEXT NOT NULL,
 PRIMARY KEY(doc_id, expires, threshold));""")
        con.execute("INSERT INTO documents(title,category,expires,created,updated) VALUES('Povinné ručení','pojisteni',?,'x','x')",
                    (iso(3),))
        con.commit()
        con.close()
        out = self.run_cli("--lang", "cs", "check").stdout
        self.assertIn("Povinné ručení", out)
        self.assertTrue((self.data / "watchdog.db").exists())

    def test_data_folder_can_come_from_the_environment(self):
        other = self.root / "elsewhere"
        self.env["WATCHDOG_DATA"] = str(other)
        p = subprocess.run([sys.executable, str(ROOT / "watchdog.py"), "check"], capture_output=True, text=True,
                           env=self.env, cwd=self.root, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((other / "watchdog.db").exists())

    @unittest.skipIf(sys.platform == "win32", "needs a POSIX shell with `head`")
    def test_closed_pipe_is_not_an_error(self):
        self.seed()
        p = subprocess.run(f'"{sys.executable}" "{ROOT / "watchdog.py"}" --data "{self.data}" check --all | head -n 1',
                           shell=True, capture_output=True, text=True, env=self.env, timeout=60)
        self.assertNotIn("Traceback", p.stderr)
        self.assertNotIn("BrokenPipe", p.stderr)


class RealServer(unittest.TestCase):
    """Starts `watchdog.py serve` as a real process and talks to it over HTTP."""

    def test_serve_and_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {k: v for k, v in os.environ.items() if not k.startswith(("WATCHDOG_", "KEEPER_", "HLIDAC_"))}
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            proc = subprocess.Popen([sys.executable, str(ROOT / "watchdog.py"), "--data", str(Path(tmp) / "d"),
                                     "serve", "--no-browser", "--port", "0"],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env)
            try:
                line = proc.stdout.readline()
                m = re.search(r"http://127\.0\.0\.1:(\d+)/", line)
                self.assertIsNotNone(m, line)
                url = m.group(0)
                with urllib.request.urlopen(url, timeout=10) as r:
                    body = r.read().decode("utf-8")
                    self.assertEqual(r.status, 200)
                    self.assertIn("Deadline Watchdog", body)
                    self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
            finally:
                proc.terminate()
                try:
                    proc.wait(10)
                except subprocess.TimeoutExpired:
                    proc.kill()
            self.assertNotIn("Traceback", proc.stderr.read())


if __name__ == "__main__":
    unittest.main()
