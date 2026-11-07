# Deadline Watchdog – author: jproucil-byte – https://github.com/jproucil-byte/Deadline-Watchdog
"""Features added in 1.2: repeating deadlines, archive, tags, own categories, automatic backup,
scheduled reminders, plus the fixes that came with them (exclusive port, stray files in backups)."""
import datetime as dt
import io
import os
import sqlite3
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import i18n  # noqa: E402
import scheduler  # noqa: E402
import store as S  # noqa: E402
import web  # noqa: E402
from test_web import WebCase, iso  # noqa: E402


class StoreCase(unittest.TestCase):
    def setUp(self):
        os.environ.pop("WATCHDOG_LANG", None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.s = S.Store(self.root / "data")


# ==========================================================================
class Tags(StoreCase):
    def test_tags_are_cleaned(self):
        self.assertEqual(S.parse_tags(" car, #Family ;CAR,, jane  smith "), ["car", "Family", "jane smith"])
        self.assertEqual(S.parse_tags(""), [])
        with self.assertRaises(S.ValidationError):
            S.parse_tags("x" * 41)
        with self.assertRaises(S.ValidationError):
            S.parse_tags(",".join(str(i) for i in range(11)))

    def test_filter_search_and_list_of_tags(self):
        a = self.s.add_document("Octavia insurance", "insurance", iso(50), "30", tags="car, Octavia")
        self.s.add_document("Passport", "id", iso(500), "90", tags="Jane")
        self.assertEqual([r["id"] for r in self.s.list_documents(tag="CAR")], [a])
        self.assertEqual([r["id"] for r in self.s.list_documents("octavia")], [a])
        self.assertEqual(self.s.all_tags(), [("car", 1), ("Jane", 1), ("Octavia", 1)])

    def test_update_without_tags_keeps_them(self):
        a = self.s.add_document("X", "other", "", "", tags="keep")
        self.s.update_document(a, "Y", "other", "", "", "")
        self.assertEqual(self.s.get_document(a)["tags"], "keep")
        self.s.update_document(a, "Y", "other", "", "", "", tags="")
        self.assertEqual(self.s.get_document(a)["tags"], "")


class Repeating(StoreCase):
    def test_renew_by_interval(self):
        today = dt.date(2026, 11, 7)
        a = self.s.add_document("Inspection", "vehicle", "2026-12-15", "30", recur="24")
        self.assertEqual(self.s.renew_by_interval(a, today), "2028-12-15")

    def test_long_expired_document_jumps_to_the_next_future_period(self):
        today = dt.date(2026, 11, 7)
        a = self.s.add_document("Gym", "contract", "2025-01-31", "7", recur="3")
        # Apr 30 comes in between, but the 31st stays the 31st: … Oct 31 2026 (past), then Jan 31 2027
        self.assertEqual(self.s.renew_by_interval(a, today), "2027-01-31")

    def test_renew_needs_an_interval(self):
        a = self.s.add_document("X", "other", iso(5), "1")
        with self.assertRaises(S.ValidationError):
            self.s.renew_by_interval(a)
        with self.assertRaises(S.ValidationError):
            self.s.add_document("X", "other", iso(5), "1", recur="121")

    def test_calendar_repeats(self):
        self.s.add_document("Yearly", "insurance", "2027-01-10", "30", recur="12")
        self.s.add_document("Quarterly", "contract", "2027-01-10", "7", recur="3")
        self.s.add_document("Once", "other", "2027-01-10", "7")
        ics = S.build_ics(self.s.list_documents())
        self.assertIn("RRULE:FREQ=YEARLY;INTERVAL=1", ics)
        self.assertIn("RRULE:FREQ=MONTHLY;INTERVAL=3", ics)
        self.assertEqual(ics.count("RRULE"), 2)


class Archive(StoreCase):
    def test_archived_documents_are_quiet(self):
        a = self.s.add_document("Old car", "vehicle", iso(-10), "30")
        b = self.s.add_document("New car", "vehicle", iso(5), "30")
        self.s.set_archived(a, True)
        self.assertEqual([r["id"] for r in self.s.list_documents()], [b])
        self.assertEqual([r["id"] for r in self.s.list_documents(archived=True)], [a])
        self.assertEqual(len(self.s.list_documents(archived=None)), 2)
        self.assertEqual([i["doc"]["id"] for i in self.s.due_notifications()], [b])
        self.assertEqual(self.s.count_archived(), 1)
        self.s.set_archived(a, False)
        self.assertEqual(self.s.count_archived(), 0)
        with self.assertRaises(KeyError):
            self.s.set_archived(999, True)


class OwnCategories(StoreCase):
    def test_add_use_and_delete(self):
        cid = self.s.add_category("  Pets  ", "14, 3")
        self.assertRegex(cid, r"^u_[0-9a-f]{8}$")
        self.assertEqual(self.s.categories()[cid], {"remind": "14,3", "label": "Pets"})
        self.assertEqual(self.s.category_labels("cs")[cid], "Pets")
        a = self.s.add_document("Rabies shot", cid, iso(30), "14")
        self.assertEqual(len(self.s.list_documents(category=cid)), 1)
        self.assertIn("CATEGORIES:Pets", S.build_ics(self.s.list_documents(), labels=self.s.category_labels("en")))
        self.assertEqual(self.s.delete_category(cid), 1)
        self.assertEqual(self.s.get_document(a)["category"], "other")
        with self.assertRaises(S.ValidationError):
            self.s.add_document("x", cid)

    def test_names_must_be_new(self):
        with self.assertRaises(S.ValidationError):
            self.s.add_category("insurance")              # the built-in one, in any language
        with self.assertRaises(S.ValidationError):
            self.s.add_category("Pojištění")
        with self.assertRaises(S.ValidationError):
            self.s.add_category("   ")
        self.s.add_category("Pets")
        with self.assertRaises(S.ValidationError):
            self.s.add_category("PETS")

    def test_only_own_categories_can_be_deleted(self):
        for bad in ("insurance", "u_zzzz", "u_00000000"):
            with self.assertRaises(KeyError):
                self.s.delete_category(bad)


class Migration(StoreCase):
    def test_database_of_version_1_1_gets_the_new_columns(self):
        d = self.root / "old"
        d.mkdir()
        c = sqlite3.connect(d / "watchdog.db")
        c.executescript("""CREATE TABLE documents(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'other', expires TEXT, remind_days TEXT NOT NULL DEFAULT '30,14,7,1',
            note TEXT NOT NULL DEFAULT '', body TEXT NOT NULL DEFAULT '', search TEXT NOT NULL DEFAULT '',
            created TEXT NOT NULL, updated TEXT NOT NULL);
            INSERT INTO documents(title,expires,created,updated) VALUES('Old','2027-01-01','x','x');""")
        c.commit()
        c.close()
        s = S.Store(d)
        row = s.list_documents()[0]
        self.assertEqual((row["title"], row["tags"], row["recur_months"], row["archived"]), ("Old", "", 0, 0))


class BackupFixes(StoreCase):
    def test_stray_files_are_left_out_and_skipped(self):
        a = self.s.add_document("Lease", "contract", iso(100), "30")
        self.s.add_attachment(a, "lease.pdf", b"%PDF-1")
        (self.s.files / "Thumbs.db").write_bytes(b"junk")
        (self.s.files / ".DS_Store").write_bytes(b"junk")
        z = self.root / "b.zip"
        self.s.backup_to(z)
        names = zipfile.ZipFile(z).namelist()
        self.assertFalse(any("Thumbs" in n or "DS_Store" in n for n in names))
        # a backup made by another tool, with stray system files inside, still restores
        buf = io.BytesIO()
        with zipfile.ZipFile(z) as src, zipfile.ZipFile(buf, "w") as dst:
            for n in src.namelist():
                dst.writestr(n, src.read(n))
            dst.writestr("files/", b"")
            dst.writestr("files/Thumbs.db", b"junk")
        z2 = self.root / "b2.zip"
        z2.write_bytes(buf.getvalue())
        other = S.Store(self.root / "other")
        other.restore_from(z2)
        self.assertEqual([r["title"] for r in other.list_documents()], ["Lease"])
        self.assertFalse((other.files / "Thumbs.db").exists())


class AutoBackup(StoreCase):
    def test_off_by_default(self):
        self.assertFalse(self.s.auto_backup_due())
        self.assertIsNone(self.s.run_auto_backup(force=True))

    def test_settings_are_checked(self):
        with self.assertRaises(S.ValidationError):
            self.s.set_auto_backup("relative/folder", 7, 5)
        with self.assertRaises(S.ValidationError):
            self.s.set_auto_backup(str(self.s.dir / "backups"), 7, 5)
        for days, keep in ((0, 5), (7, 0), ("x", 5), (400, 5)):
            with self.assertRaises(S.ValidationError):
                self.s.set_auto_backup(str(self.root / "bk"), days, keep)

    def test_due_backups_are_made_and_old_ones_pruned(self):
        self.s.add_document("Lease", "contract", iso(100), "30")
        folder = self.root / "cloud" / "bk"
        self.s.set_auto_backup(str(folder), 7, 2)
        t0 = dt.datetime(2026, 1, 1, 10, 0, 0)
        first = self.s.run_auto_backup(now=t0)
        self.assertTrue(first.exists())
        self.assertIsNone(self.s.run_auto_backup(now=t0 + dt.timedelta(days=6)))     # not due yet
        self.s.run_auto_backup(now=t0 + dt.timedelta(days=7))
        self.s.run_auto_backup(now=t0 + dt.timedelta(days=14))
        (folder / "my-own-file.zip").write_bytes(b"x")                                  # never touched
        files = sorted(p.name for p in folder.iterdir())
        self.assertEqual(files, ["deadline-watchdog-auto-2026-01-08-100000.zip",
                                 "deadline-watchdog-auto-2026-01-15-100000.zip", "my-own-file.zip"])
        with zipfile.ZipFile(folder / files[1]) as z:
            self.assertIn("watchdog.db", z.namelist())
        self.assertEqual(self.s.auto_backup_config()["last"], "2026-01-15 10:00:00")

    def test_failure_is_remembered(self):
        blocker = self.root / "file-not-folder"
        blocker.write_text("x")
        self.s.set_auto_backup(str(blocker / "sub"), 1, 1)
        with self.assertRaises(OSError):
            self.s.run_auto_backup()
        self.assertTrue(self.s.auto_backup_config()["error"])
        self.assertEqual(self.s.auto_backup_config()["last"], "")


# ==========================================================================
class Scheduler(unittest.TestCase):
    def test_task_definition(self):
        xml = scheduler._task_xml(r"C:\my data", with_logon=True)
        self.assertIn("<StartWhenAvailable>true</StartWhenAvailable>", xml)
        self.assertIn("<LogonTrigger>", xml)
        self.assertIn("notify --quiet", xml)
        self.assertIn('--data "C:\\my data" notify', xml)
        self.assertNotIn("<LogonTrigger>", scheduler._task_xml("x", with_logon=False))

    def test_command_and_autostart_entry(self):
        cmd = scheduler.command("/tmp/d a t a")
        self.assertEqual(cmd[-4:], ["--data", "/tmp/d a t a", "notify", "--quiet"])
        entry = scheduler._desktop_entry('/tmp/$x "y"')
        self.assertIn('"/tmp/\\$x \\"y\\""', entry)
        self.assertIn("NoDisplay=true", entry)


# ==========================================================================
class WebFeatures(WebCase):
    def test_save_with_tags_and_repeat(self):
        r = self.post("/save", {"title": "STK", "category": "vehicle", "expires": iso(20), "remind_days": "30",
                                "note": "", "tmp": "", "tags": "car, Octavia", "recur": "24"})
        self.assertEqual(r.status, 303)
        doc = self.store.list_documents()[0]
        self.assertEqual((doc["tags"], doc["recur_months"]), ("car,Octavia", 24))
        page = self.get(f"/doc/{doc['id']}").plain
        self.assertIn("every 2 years", page)
        self.assertIn("#Octavia", page)
        self.assertIn("Renew for the next period (every 2 years)", page)
        r = self.post(f"/doc/{doc['id']}/renew", {"mode": "recur"})
        self.assertEqual(r.status, 303)
        self.assertEqual(self.store.get_document(doc["id"])["expires"],
                         (dt.date.fromisoformat(iso(20)).replace(year=dt.date.fromisoformat(iso(20)).year + 2)
                          .isoformat()))

    def test_overview_tags_and_archive(self):
        a = self.store.add_document("Old car", "vehicle", iso(5), "30", tags="car")
        self.store.add_document("Passport", "id", iso(400), "90", tags="Jane")
        t = self.get("/?t=car").plain
        self.assertIn("Old car", t)
        self.assertNotIn("Passport", t)
        self.assertEqual(self.post(f"/doc/{a}/archive", {"archived": "1"}).status, 303)
        t = self.get("/").plain
        self.assertNotIn("Old car", t)
        self.assertIn("Archive (1 document)", t)
        self.assertIn("Old car", self.get("/?a=1").plain)
        self.assertIn("This document is archived", self.get(f"/doc/{a}").plain)
        self.post(f"/doc/{a}/archive", {"archived": "0"})
        self.assertIn("Old car", self.get("/").plain)

    def test_own_categories_on_the_settings_page(self):
        r = self.post("/settings/category", {"label": "Pets", "remind": "14,3"})
        self.assertEqual(r.status, 303)
        cid = self.store.custom_categories()[0]["id"]
        self.assertIn("Pets", self.get("/settings").plain)
        self.assertIn(f'value="{cid}"', self.get("/review").text)
        self.assertEqual(self.post("/settings/category", {"label": "Insurance"}).status, 400)
        self.assertEqual(self.post(f"/settings/category/{cid}/delete").status, 303)
        self.assertEqual(self.store.custom_categories(), [])
        self.assertEqual(self.post("/settings/category/u_00000000/delete").status, 404)

    def test_automatic_backup_settings(self):
        folder = Path(self.tmp.name) / "bk"
        self.assertEqual(self.post("/settings/backup", {"dir": "relative", "days": "7", "keep": "5"}).status, 400)
        self.assertEqual(self.post("/settings/backup", {"dir": str(folder), "days": "7", "keep": "3"}).status, 303)
        self.assertEqual(self.post("/settings/backup/run").status, 303)
        self.assertEqual(len(list(folder.glob("deadline-watchdog-auto-*.zip"))), 1)
        self.assertIn("Last automatic backup", self.get("/settings").plain)

    def test_csrf_token_survives_a_restart(self):
        again = web.App(self.store)
        self.assertEqual(again.token, self.app.token)

    def test_non_ascii_token_is_a_clean_403(self):
        self.assertEqual(self.post("/settings", {"lang": "en", "csrf": "žluťoučký"}, csrf=False).status, 403)

    def test_second_start_finds_the_running_copy(self):
        self.assertTrue(web.running_copy(self.port, self.store.dir))
        self.assertFalse(web.running_copy(self.port, Path(self.tmp.name) / "other"))
        with self.assertRaises(web.AlreadyRunning):
            web.make_server(self.store, self.port, search=False, reuse_running=True)

    def test_port_in_use_is_not_shared(self):
        """On Windows SO_REUSEADDR used to let a second server take the same port."""
        other = S.Store(Path(self.tmp.name) / "other")
        with self.assertRaises(OSError):
            web.make_server(other, self.port, search=False)
        httpd, app = web.make_server(other, self.port, search=True)
        try:
            self.assertNotEqual(app.port, self.port)
        finally:
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
