"""Regression tests for failed writes, restore validation and concurrent backups."""
import contextlib
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import docparse
import store


class StorageReliability(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.s = store.Store(self.root / "data")
        self.doc = self.s.add_document("Original")
        self.att = self.s.add_attachment(self.doc, "original.txt", b"original")

    def assert_original(self):
        self.assertEqual([d["title"] for d in self.s.list_documents()], ["Original"])
        att = self.s.get_attachment(self.att)
        self.assertEqual(self.s.attachment_path(att).read_bytes(), b"original")

    def test_wrong_columns_do_not_replace_live_data(self):
        db = self.root / "invalid.db"
        with contextlib.closing(sqlite3.connect(db)) as c:
            c.executescript("CREATE TABLE documents(id); CREATE TABLE attachments(id);")
        archive = self.root / "invalid.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.write(db, store.DB_NAME)
        with self.assertRaises(store.ValidationError):
            self.s.restore_from(archive)
        self.assert_original()
        self.assertEqual(list(self.root.glob("data-before-restore-*")), [])

    def test_missing_attachment_rejects_restore(self):
        good, bad = self.root / "good.zip", self.root / "bad.zip"
        self.s.backup_to(good)
        with zipfile.ZipFile(good) as source, zipfile.ZipFile(bad, "w") as target:
            target.writestr(store.DB_NAME, source.read(store.DB_NAME))
        with self.assertRaises(store.ValidationError):
            self.s.restore_from(bad)
        self.assert_original()

    def test_failed_swap_restores_original_database_and_files(self):
        archive = self.root / "backup.zip"
        self.s.backup_to(archive)
        self.s.add_document("Added later")
        replace = store.os.replace

        def fail_new_files(source, target):
            if Path(source).parent.name.startswith("restore-") and Path(source).name == "files":
                raise OSError("simulated disk failure")
            return replace(source, target)

        with patch("store.os.replace", side_effect=fail_new_files):
            with self.assertRaises(OSError):
                self.s.restore_from(archive)
        self.assertEqual({d["title"] for d in self.s.list_documents()}, {"Original", "Added later"})
        self.assertEqual(self.s.attachment_path(self.s.get_attachment(self.att)).read_bytes(), b"original")

    def test_failed_upload_rolls_back_and_can_be_retried(self):
        token = self.s.save_temp("new.txt", b"new document")

        def partial_copy(source, dest):
            Path(dest).write_bytes(b"partial")
            raise OSError("disk full")

        with patch("store.shutil.copyfile", side_effect=partial_copy):
            with self.assertRaises(OSError):
                self.s.add_document("New", upload_token=token)
        self.assert_original()
        self.assertEqual(len(list(self.s.files.iterdir())), 1)
        self.assertEqual(self.s.temp_info(token)[0].read_bytes(), b"new document")
        doc = self.s.add_document("New", upload_token=token)
        self.assertEqual(len(self.s.list_attachments(doc)), 1)
        self.assertIsNone(self.s.temp_info(token))

    def test_database_failure_preserves_temporary_upload(self):
        token = self.s.save_temp("new.txt", b"new")
        with self.assertRaises(sqlite3.IntegrityError):
            self.s.temp_to_attachment(token, 99999)
        self.assertEqual(self.s.temp_info(token)[0].read_bytes(), b"new")
        self.assertEqual(len(list(self.s.files.iterdir())), 1)

    def test_attachment_insert_failure_rolls_back_new_document(self):
        token = self.s.save_temp("new.txt", b"new")
        with self.s.conn() as c:
            c.execute("CREATE TRIGGER reject_attachment BEFORE INSERT ON attachments "
                      "BEGIN SELECT RAISE(ABORT, 'simulated failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.s.add_document("New", upload_token=token)
        self.assert_original()
        self.assertEqual(len(list(self.s.files.iterdir())), 1)
        self.assertIsNotNone(self.s.temp_info(token))

    def test_failed_backup_does_not_overwrite_previous_archive(self):
        archive = self.root / "backup.zip"
        self.s.backup_to(archive)
        previous = archive.read_bytes()
        self.s.attachment_path(self.s.get_attachment(self.att)).unlink()
        with self.assertRaises(OSError):
            self.s.backup_to(archive)
        self.assertEqual(archive.read_bytes(), previous)
        self.assertEqual(list(self.root.glob("*.part")), [])

    def test_delete_waits_for_complete_backup(self):
        other = store.Store(self.s.dir)
        started, finished = threading.Event(), threading.Event()
        errors = []

        def delete():
            started.set()
            try:
                other.delete_attachment(self.att)
            except BaseException as exc:
                errors.append(exc)
            finally:
                finished.set()

        worker = threading.Thread(target=delete)
        write = zipfile.ZipFile.write

        def during_snapshot(z, filename, arcname=None, *args, **kwargs):
            if arcname == store.DB_NAME:
                worker.start()
                self.assertTrue(started.wait(5))
                self.assertFalse(finished.wait(0.1))
            return write(z, filename, arcname, *args, **kwargs)

        archive = self.root / "backup.zip"
        try:
            with patch.object(zipfile.ZipFile, "write", during_snapshot):
                self.s.backup_to(archive)
        finally:
            if worker.ident is not None:
                worker.join(5)
        self.assertTrue(finished.is_set())
        self.assertEqual(errors, [])
        restored = store.Store(self.root / "restored")
        restored.restore_from(archive)
        att = restored.list_attachments(self.doc)[0]
        self.assertEqual(restored.attachment_path(att).read_bytes(), b"original")

    def test_lock_is_shared_with_other_processes(self):
        script = (
            "import sys; from pathlib import Path; import store; "
            "s=store.Store(sys.argv[1]); print('ready', flush=True); "
            "sys.stdin.readline(); s.add_document('Child'); print('done', flush=True)"
        )
        with subprocess.Popen([sys.executable, "-c", script, str(self.s.dir)],
                              cwd=Path(store.__file__).parent, stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as child:
            self.assertEqual(child.stdout.readline().strip(), "ready")
            with self.s.data_lock():
                child.stdin.write("go\n")
                child.stdin.flush()
                with self.assertRaises(subprocess.TimeoutExpired):
                    child.wait(timeout=0.2)
            out, err = child.communicate(timeout=10)
            self.assertEqual(child.returncode, 0, err)
            self.assertIn("done", out)
        self.assertIn("Child", [d["title"] for d in self.s.list_documents()])


class ExtractionReliability(unittest.TestCase):
    def test_external_tool_nonzero_exit_is_an_error(self):
        with self.assertRaises(subprocess.CalledProcessError):
            docparse._run([sys.executable, "-c", "raise SystemExit(2)"], 10)

    def test_failed_ocr_keeps_short_pdf_text(self):
        with patch("docparse._pdf_text_tool", return_value="Expires 2027-03-04"), \
                patch("docparse.find_tool", return_value="tool"), \
                patch("docparse._ocr_pdf", return_value=""):
            result = docparse.extract_text("example.pdf")
        self.assertEqual(result["text"], "Expires 2027-03-04")
        self.assertEqual(result["method"], "pdf")

    def test_failed_pdf_tool_reports_error(self):
        with patch("docparse.find_tool", return_value="tool"), \
                patch("docparse._run", side_effect=subprocess.CalledProcessError(1, "tool")), \
                patch("docparse.importlib.util.find_spec", return_value=None):
            notes = []
            self.assertEqual(docparse._pdf_text_tool("example.pdf", notes), "")
        self.assertIn({"code": "pdftotext_failed"}, notes)
