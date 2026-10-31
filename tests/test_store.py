# Deadline Watchdog – author: jproucil-byte – https://github.com/jproucil-byte/Deadline-Watchdog
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import i18n  # noqa: E402
import store as S  # noqa: E402

TODAY = dt.date(2026, 10, 28)

LEGACY_SCHEMA = """
CREATE TABLE documents(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'ostatni', expires TEXT, remind_days TEXT NOT NULL DEFAULT '30,14,7,1',
  note TEXT NOT NULL DEFAULT '', body TEXT NOT NULL DEFAULT '', search TEXT NOT NULL DEFAULT '',
  created TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE attachments(id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE, filename TEXT NOT NULL,
  stored TEXT NOT NULL UNIQUE, size INTEGER NOT NULL, mime TEXT NOT NULL, added TEXT NOT NULL);
CREATE TABLE notified(doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  expires TEXT NOT NULL, threshold INTEGER NOT NULL, at TEXT NOT NULL, PRIMARY KEY(doc_id, expires, threshold));
"""


def make_legacy_db(path):
    con = sqlite3.connect(path)
    con.executescript(LEGACY_SCHEMA)
    now = "2025-01-01 10:00:00"
    for title, cat, exp in (("Povinné ručení", "pojisteni", "2027-03-01"), ("STK Octavia", "stk", "2026-12-01"),
                            ("Záruka pračka", "zaruka", "2027-05-12"), ("Něco", "ostatni", None)):
        con.execute("INSERT INTO documents(title,category,expires,remind_days,note,body,search,created,updated)"
                    " VALUES(?,?,?,?,?,?,?,?,?)", (title, cat, exp, "30,14,7,1", "", "", title.lower(), now, now))
    con.commit()
    con.close()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        os.environ.pop("WATCHDOG_LANG", None)
        self.s = S.Store(self.root / "data")


class Validation(unittest.TestCase):
    def test_user_dates(self):
        self.assertEqual(S.parse_user_date("2027-03-04"), dt.date(2027, 3, 4))
        self.assertEqual(S.parse_user_date(" 4. 3. 2027 "), dt.date(2027, 3, 4))
        for bad in ("", "31.2.2027", "03/04/2027", "tomorrow", "2027-13-01"):
            with self.assertRaises(S.ValidationError, msg=bad):
                S.parse_user_date(bad)

    def test_remind_days(self):
        self.assertEqual(S.parse_remind_days("7, 30 14;30"), [30, 14, 7])
        self.assertEqual(S.parse_remind_days(""), [])
        for bad in ("a", "7,-1", "7.5", "4000", ",".join(str(i) for i in range(1, 14))):
            with self.assertRaises(S.ValidationError, msg=bad):
                S.parse_remind_days(bad)

    def test_errors_are_translated(self):
        with self.assertRaises(S.ValidationError) as cm:
            S.validate_fields("", "other", "", "7", "")
        self.assertEqual(cm.exception.text("en"), "Enter a title for the document.")
        self.assertEqual(cm.exception.text("cs"), "Vyplň název dokumentu.")
        self.assertEqual(str(cm.exception), "Enter a title for the document.")

    def test_every_validation_error_exists_in_both_languages(self):
        for fn, args in ((S.validate_fields, ("", "other", "", "", "")),
                         (S.validate_fields, ("x" * 201, "other", "", "", "")),
                         (S.validate_fields, ("x", "nope", "", "", "")),
                         (S.validate_fields, ("x", "other", "", "", "n" * 5001)),
                         (S.validate_fields, ("x", "other", "31.2.2027", "", "")),
                         (S.validate_fields, ("x", "other", "", "abc", "")),
                         (S.Store.check_upload, ("virus.exe", 5)),
                         (S.Store.check_upload, ("a.pdf", 0)),
                         (S.Store.check_upload, ("a.pdf", S.MAX_UPLOAD + 1))):
            with self.assertRaises(S.ValidationError) as cm:
                fn(*args)
            for lang in ("en", "cs"):
                self.assertNotEqual(cm.exception.text(lang), cm.exception.key, (cm.exception.key, lang))

    def test_fields_are_cleaned_and_legacy_categories_mapped(self):
        f = S.validate_fields("  Policy ", "pojisteni", "2027-03-04", "7, 30", "  note ")
        self.assertEqual(f, {"title": "Policy", "category": "insurance", "expires": "2027-03-04",
                             "remind_days": "30,7", "note": "note"})
        self.assertIsNone(S.validate_fields("x", "", "", "", "")["expires"])
        self.assertEqual(S.validate_fields("x", "", "", "", "")["category"], "other")

    def test_status(self):
        today = TODAY
        iso = lambda n: (today + dt.timedelta(days=n)).isoformat()  # noqa: E731
        self.assertEqual(S.classify(None, [30], today), {"key": "none", "days": None})
        self.assertEqual(S.classify(iso(-1), [30], today), {"key": "expired", "days": -1})
        self.assertEqual(S.classify(iso(0), [], today), {"key": "soon", "days": 0})
        self.assertEqual(S.classify(iso(30), [30, 7], today)["key"], "soon")
        self.assertEqual(S.classify(iso(31), [30, 7], today)["key"], "ok")
        self.assertEqual(S.classify(iso(1), [], today)["key"], "ok")

    def test_clean_name(self):
        self.assertEqual(S._clean_name("../../etc/passwd"), "passwd")
        self.assertEqual(S._clean_name("C:\\Users\\me\\scan.pdf"), "scan.pdf")
        self.assertEqual(S._clean_name("a\x00b\n.pdf"), "ab.pdf")
        self.assertEqual(S._clean_name(""), "file")
        self.assertLessEqual(len(S._clean_name("x" * 500 + ".pdf")), 120)


class Documents(Base):
    def test_crud(self):
        i = self.s.add_document("Home insurance", "insurance", "2027-03-01", "30,7", "note", "body text")
        d = self.s.get_document(i)
        self.assertEqual((d["title"], d["category"], d["expires"], d["remind_days"]),
                         ("Home insurance", "insurance", "2027-03-01", "30,7"))
        self.s.update_document(i, "Home insurance 2", "insurance", "2028-03-01", "14", "n2")
        self.assertEqual(self.s.get_document(i)["expires"], "2028-03-01")
        self.assertEqual(self.s.get_document(i)["body"], "body text")          # the read text is preserved
        self.s.set_expiry(i, "2029-01-01")
        self.assertEqual(self.s.get_document(i)["expires"], "2029-01-01")
        self.s.delete_document(i)
        self.assertIsNone(self.s.get_document(i))
        for fn in (lambda: self.s.delete_document(i), lambda: self.s.set_expiry(i, "2029-01-01"),
                   lambda: self.s.update_document(i, "x", "other", "", "", "")):
            with self.assertRaises(KeyError):
                fn()

    def test_default_values_and_no_date(self):
        i = self.s.add_document("No date")
        d = self.s.get_document(i)
        self.assertEqual((d["category"], d["expires"], d["remind_days"]), ("other", None, "30,14,7,1"))

    def test_ordering(self):
        self.s.add_document("B", expires="2027-02-01")
        self.s.add_document("no date")
        self.s.add_document("A", expires="2026-12-01")
        self.assertEqual([r["title"] for r in self.s.list_documents()], ["A", "B", "no date"])

    def test_search_ignores_case_and_diacritics_and_matches_text_and_notes(self):
        self.s.add_document("Pojišťovna Kooperativa", "insurance", "2027-01-01", note="Škoda Octavia")
        self.s.add_document("Lease", "contract", "2027-01-02", body="Landlord: Jane Smith")
        self.assertEqual([r["title"] for r in self.s.list_documents("POJISTOVNA")], ["Pojišťovna Kooperativa"])
        self.assertEqual(len(self.s.list_documents("skoda")), 1)
        self.assertEqual([r["title"] for r in self.s.list_documents("jane smith")], ["Lease"])
        self.assertEqual(len(self.s.list_documents("lease jane")), 1)       # all words must match
        self.assertEqual(len(self.s.list_documents("lease nobody")), 0)
        self.assertEqual(len(self.s.list_documents("insurance", "contract")), 0)
        self.assertEqual(len(self.s.list_documents("", "contract")), 1)

    def test_search_treats_wildcards_literally(self):
        self.s.add_document("100% cotton")
        self.s.add_document("plain")
        self.assertEqual(len(self.s.list_documents("%")), 1)
        self.assertEqual(len(self.s.list_documents("_")), 0)
        self.assertEqual(len(self.s.list_documents("' OR 1=1 --")), 0)

    def test_long_body_is_cut(self):
        i = self.s.add_document("x", body="a" * (S.MAX_BODY + 500))
        self.assertEqual(len(self.s.get_document(i)["body"]), S.MAX_BODY)


class Attachments(Base):
    def test_add_read_delete(self):
        i = self.s.add_document("Doc")
        a = self.s.add_attachment(i, "scan.PDF", b"%PDF-1.4 data")
        att = self.s.get_attachment(a)
        self.assertEqual((att["filename"], att["mime"], att["size"]), ("scan.PDF", "application/pdf", 13))
        self.assertTrue(att["stored"].endswith(".pdf"))
        path = self.s.attachment_path(att)
        self.assertEqual(path.read_bytes(), b"%PDF-1.4 data")
        self.assertEqual(path.parent, self.s.files.resolve())
        self.assertEqual(self.s.delete_attachment(a), i)
        self.assertFalse(path.exists())

    def test_delete_document_removes_files(self):
        i = self.s.add_document("Doc")
        paths = [self.s.attachment_path(self.s.get_attachment(self.s.add_attachment(i, f"{n}.txt", b"x")))
                 for n in "ab"]
        self.s.delete_document(i)
        self.assertFalse(any(p.exists() for p in paths))
        with self.s.conn() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM attachments").fetchone()[0], 0)

    def test_rejects_bad_uploads(self):
        i = self.s.add_document("Doc")
        for name, data in (("a.exe", b"x"), ("a.html", b"x"), ("a.svg", b"x"), ("noext", b"x"), ("a.pdf", b"")):
            with self.assertRaises(S.ValidationError, msg=name):
                self.s.add_attachment(i, name, data)
        with self.assertRaises(KeyError):
            self.s.add_attachment(999, "a.pdf", b"x")
        self.assertEqual(list(self.s.files.iterdir()), [])

    def test_file_name_with_path_is_neutralised_and_stored_name_is_random(self):
        i = self.s.add_document("Doc")
        att = self.s.get_attachment(self.s.add_attachment(i, "../../evil.pdf", b"x"))
        self.assertEqual(att["filename"], "evil.pdf")
        self.assertRegex(att["stored"], r"^[0-9a-f]{32}\.pdf$")

    def test_path_guard(self):
        with self.assertRaises(ValueError):
            self.s.attachment_path({"stored": "../watchdog.db"})
        with self.assertRaises(ValueError):
            self.s.attachment_path({"stored": "/etc/passwd"})

    def test_temp_upload_flow(self):
        token = self.s.save_temp("lease.txt", b"Expires 2027-01-01")
        path, name, text = self.s.temp_info(token)
        self.assertEqual((name, text, path.read_bytes()), ("lease.txt", "", b"Expires 2027-01-01"))
        self.s.set_temp_text(token, "text read")
        self.assertEqual(self.s.temp_info(token)[2], "text read")
        i = self.s.add_document("Lease")
        att = self.s.temp_to_attachment(token, i)
        self.assertEqual(self.s.get_attachment(att)["filename"], "lease.txt")
        self.assertFalse(path.exists())
        self.assertIsNone(self.s.temp_info(token))
        with self.assertRaises(S.ValidationError) as cm:
            self.s.temp_to_attachment(token, i)
        self.assertEqual(cm.exception.key, "err.upload_gone")

    def test_bad_tokens_are_ignored(self):
        for token in ("../../etc/passwd", "", "x" * 32, None, "a" * 31):
            self.assertIsNone(self.s.temp_info(token))
            self.s.discard_temp(token)                    # must not raise or touch other files

    def test_discard_and_cleanup(self):
        token = self.s.save_temp("a.txt", b"x")
        self.s.discard_temp(token)
        self.assertIsNone(self.s.temp_info(token))
        old = self.s.save_temp("b.txt", b"x")
        new = self.s.save_temp("c.txt", b"x")
        then = time.time() - 30 * 3600
        for ext in (".bin", ".json"):
            os.utime(self.s.tmp / f"{old}{ext}", (then, then))
        self.s.cleanup_temp()
        self.assertIsNone(self.s.temp_info(old))
        self.assertIsNotNone(self.s.temp_info(new))


class Settings(Base):
    def test_defaults(self):
        self.assertEqual(self.s.get_lang(), "en")
        self.assertEqual(self.s.get_date_order(), "mdy")

    def test_saved_values(self):
        self.s.set_lang("cs")
        self.assertEqual(self.s.get_lang(), "cs")
        self.assertEqual(self.s.get_date_order(), "dmy")                 # follows the language until chosen
        self.s.set_date_order("mdy")
        self.assertEqual(self.s.get_date_order(), "mdy")
        self.s.set_lang("xx")                                            # unknown -> English
        self.assertEqual(self.s.get_lang(), "en")
        with self.assertRaises(S.ValidationError):
            self.s.set_date_order("ymd")
        self.assertEqual(S.Store(self.s.dir).get_setting("date_order"), "mdy")      # persisted

    def test_override_and_environment(self):
        self.s.set_lang("cs")
        self.assertEqual(S.Store(self.s.dir, lang="en").get_lang(), "en")
        os.environ["WATCHDOG_LANG"] = "en"
        self.addCleanup(os.environ.pop, "WATCHDOG_LANG", None)
        self.assertEqual(S.Store(self.s.dir).get_lang(), "en")
        self.assertEqual(S.Store(self.s.dir, lang="cs").get_lang(), "cs")     # explicit option beats the variable


class Notifications(Base):
    def add(self, days, remind="30,7", title="X"):
        return self.s.add_document(title, "other", (TODAY + dt.timedelta(days=days)).isoformat(), remind)

    def test_announced_once_per_reminder_point(self):
        self.add(25)
        first = self.s.due_notifications(TODAY)
        self.assertEqual([(i["days"], i["threshold"]) for i in first], [(25, 30)])
        self.s.mark_notified(first)
        self.assertEqual(self.s.due_notifications(TODAY), [])
        self.assertEqual(self.s.due_notifications(TODAY + dt.timedelta(days=10)), [])
        later = self.s.due_notifications(TODAY + dt.timedelta(days=19))        # 6 days left -> point 7
        self.assertEqual([i["threshold"] for i in later], [7])

    def test_a_skipped_point_does_not_repeat_older_ones(self):
        i = self.add(3)
        got = self.s.due_notifications(TODAY)
        self.assertEqual(got[0]["threshold"], 7)
        self.s.mark_notified(got)
        self.assertEqual(self.s.due_notifications(TODAY), [])
        self.assertEqual(self.s.get_document(i)["id"], i)

    def test_expiry_day_and_expired(self):
        self.add(0, remind="")
        self.assertEqual(len(self.s.due_notifications(TODAY)), 1)
        self.s.mark_notified(self.s.due_notifications(TODAY))
        self.assertEqual(self.s.due_notifications(TODAY), [])
        got = self.s.due_notifications(TODAY + dt.timedelta(days=2))
        self.assertEqual((got[0]["days"], got[0]["threshold"]), (-2, -1))

    def test_renewal_starts_over(self):
        i = self.add(3)
        self.s.mark_notified(self.s.due_notifications(TODAY))
        self.s.set_expiry(i, (TODAY + dt.timedelta(days=5)).isoformat())
        self.assertEqual(len(self.s.due_notifications(TODAY)), 1)

    def test_no_date_never_notifies(self):
        self.s.add_document("no date")
        self.assertEqual(self.s.due_notifications(TODAY), [])


class Calendar(Base):
    def docs(self):
        self.s.add_document("Home insurance; fire, theft", "insurance", "2027-03-04", "60,7,1,0", "Policy no. 5\nCall Jim")
        self.s.add_document("No date")
        return self.s.list_documents()

    def test_english_calendar(self):
        ics = S.build_ics(self.docs(), now=dt.datetime(2026, 10, 28, 12, tzinfo=dt.timezone.utc), lang="en")
        self.assertTrue(ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n"))
        self.assertEqual(ics.count("BEGIN:VEVENT"), 1)                 # the document without a date is skipped
        self.assertIn("DTSTART;VALUE=DATE:20270304", ics)
        self.assertIn("DTEND;VALUE=DATE:20270305", ics)
        self.assertIn("SUMMARY:Expires: Home insurance\\; fire\\, theft", ics.replace("\r\n ", ""))
        self.assertIn("Policy no. 5\\nCall Jim", ics.replace("\r\n ", ""))
        self.assertIn("UID:deadline-watchdog-1@localhost", ics)
        self.assertIn("DTSTAMP:20261028T120000Z", ics)
        self.assertIn("CATEGORIES:Insurance", ics)
        for trigger in ("-P59DT15H", "-P6DT15H", "-PT15H", "PT9H"):
            self.assertIn("TRIGGER:" + trigger, ics)
        self.assertIn("March 4", ics.replace("\r\n ", "").replace("Mar 4", "March 4"))

    def test_czech_calendar(self):
        ics = S.build_ics(self.docs(), lang="cs").replace("\r\n ", "")
        self.assertIn("SUMMARY:Konec platnosti: Home insurance", ics)
        self.assertIn("CATEGORIES:Pojištění", ics)
        self.assertIn("4. 3. 2027", ics)

    def test_lines_are_folded_and_use_crlf(self):
        self.s.add_document("Ž" * 120, "other", "2027-03-04")
        ics = S.build_ics(self.s.list_documents())
        for line in ics.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75, line)
        self.assertNotIn("\n", ics.replace("\r\n", ""))
        self.assertIn("Ž" * 120, ics.replace("\r\n ", ""))                # unfolding gives the original text back

    def test_alarm_triggers(self):
        self.assertEqual([S._alarm_trigger(n) for n in (0, 1, 2, 30)], ["PT9H", "-PT15H", "-P1DT15H", "-P29DT15H"])


class LegacyData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "data"
        self.dir.mkdir()

    def test_old_database_and_categories_are_migrated(self):
        make_legacy_db(self.dir / "hlidac.db")
        s = S.Store(self.dir)
        self.assertTrue((self.dir / "watchdog.db").exists())
        self.assertFalse((self.dir / "hlidac.db").exists())
        cats = {r["title"]: r["category"] for r in s.list_documents()}
        self.assertEqual(cats, {"Povinné ručení": "insurance", "STK Octavia": "vehicle",
                                "Záruka pračka": "warranty", "Něco": "other"})
        self.assertEqual(s.get_lang(), "en")                       # the settings table was added
        self.assertEqual(len(S.Store(self.dir).list_documents()), 4)    # opening it again changes nothing

    def test_database_of_the_previous_english_version_is_picked_up(self):
        first = S.Store(self.dir)
        first.add_document("Kept", "contract", "2030-01-01", "7")
        (self.dir / "watchdog.db").rename(self.dir / "keeper.db")       # what Expiry Keeper 1.0 left behind
        for suffix in ("-wal", "-shm"):
            if (self.dir / ("watchdog.db" + suffix)).exists():
                (self.dir / ("watchdog.db" + suffix)).rename(self.dir / ("keeper.db" + suffix))
        s = S.Store(self.dir)
        self.assertEqual([r["title"] for r in s.list_documents()], ["Kept"])
        self.assertTrue((self.dir / "watchdog.db").exists())
        self.assertFalse((self.dir / "keeper.db").exists())

    def test_current_db_wins_over_a_stale_legacy_file(self):
        make_legacy_db(self.dir / "hlidac.db")
        S.Store(self.dir).add_document("New")                       # migrates, then adds a document
        make_legacy_db(self.dir / "hlidac.db")                      # an old file reappears (e.g. from a restored copy)
        s = S.Store(self.dir)
        self.assertEqual(len(s.list_documents()), 5)
        self.assertTrue((self.dir / "hlidac.db").exists())          # not touched

    def test_unknown_category_in_old_data_still_renders_in_the_calendar(self):
        make_legacy_db(self.dir / "hlidac.db")
        s = S.Store(self.dir)
        ics = S.build_ics([{"id": 9, "title": "X", "category": "stk", "expires": "2027-01-01", "note": "",
                            "remind_days": "7", "updated": "2026-01-01 10:00:00"}], lang="en")
        self.assertIn("CATEGORIES:Vehicle", ics)
        self.assertIsNotNone(s)


class BackupRestore(Base):
    def fill(self):
        i = self.s.add_document("Lease", "contract", "2027-06-01", "30,7", "n", "body")
        self.s.add_attachment(i, "lease.pdf", b"%PDF-lease")
        self.s.set_lang("cs")
        return i

    def test_backup_contains_database_and_files(self):
        self.fill()
        z = self.root / "b.zip"
        self.s.backup_to(z)
        with zipfile.ZipFile(z) as zf:
            names = zf.namelist()
        self.assertIn("watchdog.db", names)
        self.assertEqual(len([n for n in names if n.startswith("files/")]), 1)
        self.assertEqual(list(self.s.tmp.iterdir()), [])             # no leftovers

    def test_round_trip(self):
        self.fill()
        z = self.root / "b.zip"
        self.s.backup_to(z)
        other = S.Store(self.root / "other")
        other.add_document("Will be replaced")
        old = other.restore_from(z)
        self.assertEqual([r["title"] for r in other.list_documents()], ["Lease"])
        att = other.list_attachments(other.list_documents()[0]["id"])[0]
        self.assertEqual(other.attachment_path(att).read_bytes(), b"%PDF-lease")
        self.assertEqual(other.get_lang(), "cs")                      # settings are part of the database
        self.assertTrue(old.is_dir())
        self.assertTrue(any(old.glob("watchdog.db")))                   # the previous data was kept, not deleted
        other.add_document("Works after restore")

    def test_restore_of_a_backup_from_the_czech_version(self):
        legacy = self.root / "legacy"
        legacy.mkdir()
        make_legacy_db(legacy / "hlidac.db")
        stored = "0123456789abcdef0123456789abcdef.pdf"
        z = self.root / "old.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.write(legacy / "hlidac.db", "hlidac.db")
            zf.writestr("files/" + stored, b"%PDF-old")
        self.s.restore_from(z)
        self.assertEqual({r["category"] for r in self.s.list_documents()},
                         {"insurance", "vehicle", "warranty", "other"})
        self.assertEqual((self.s.files / stored).read_bytes(), b"%PDF-old")

    def test_restore_of_a_backup_from_the_previous_english_version(self):
        src = S.Store(self.root / "src")
        src.add_document("From keeper", "warranty", "2031-05-05", "30")
        stored = "fedcba9876543210fedcba9876543210.pdf"
        z = self.root / "keeper.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.write(src.db_path, "keeper.db")                          # the old name of the database inside the zip
            zf.writestr("files/" + stored, b"%PDF-keeper")
        self.s.restore_from(z)
        self.assertEqual([r["title"] for r in self.s.list_documents()], ["From keeper"])
        self.assertEqual((self.s.files / stored).read_bytes(), b"%PDF-keeper")
        self.assertTrue((self.s.dir / "watchdog.db").exists())

    _zips = 0

    def make_zip(self, entries):
        z = io.BytesIO()
        with zipfile.ZipFile(z, "w") as zf:
            for name, data in entries.items():
                zf.writestr(name, data)
        BackupRestore._zips += 1
        path = self.root / f"case{BackupRestore._zips}.zip"
        path.write_bytes(z.getvalue())
        return path

    def test_hostile_or_broken_backups_are_rejected_and_data_is_kept(self):
        self.fill()
        good = self.root / "good.zip"
        self.s.backup_to(good)
        db = zipfile.ZipFile(good).read("watchdog.db")
        cases = {
            "not a zip": (self.root / "n.zip", "err.restore_notzip"),
            "no database": (self.make_zip({"readme.txt": b"x"}), "err.restore_nodb"),
            "path traversal": (self.make_zip({"watchdog.db": db, "../evil.txt": b"x"}), "err.restore_unexpected"),
            "unexpected name": (self.make_zip({"watchdog.db": db, "files/not-a-hash.pdf": b"x"}),
                                "err.restore_unexpected"),
            "absolute path": (self.make_zip({"watchdog.db": db, "/etc/passwd": b"x"}), "err.restore_unexpected"),
            "corrupt db": (self.make_zip({"watchdog.db": b"this is not sqlite" * 100}), "err.restore_corrupt"),
            "wrong structure": (None, "err.restore_struct"),
        }
        (self.root / "n.zip").write_bytes(b"hello")
        other = sqlite3.connect(self.root / "other.db")
        other.execute("CREATE TABLE foo(a)")
        other.commit()
        other.close()
        cases["wrong structure"] = (self.make_zip({"watchdog.db": (self.root / "other.db").read_bytes()}),
                                    "err.restore_struct")
        for label, (path, key) in cases.items():
            with self.assertRaises(S.ValidationError, msg=label) as cm:
                self.s.restore_from(path)
            self.assertEqual(cm.exception.key, key, label)
            for lang in ("en", "cs"):
                self.assertNotEqual(cm.exception.text(lang), key)
        self.assertEqual([r["title"] for r in self.s.list_documents()], ["Lease"])      # nothing was touched
        self.assertFalse(any(p.name.startswith("data-before-restore") for p in self.root.iterdir()))
        self.assertFalse((self.root / "evil.txt").exists())


if __name__ == "__main__":
    unittest.main()
