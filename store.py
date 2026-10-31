# Deadline Watchdog – author: jproucil-byte – https://github.com/jproucil-byte/Deadline-Watchdog
"""Storage (SQLite + a folder of files), reminders, calendar export, backup.

Everything lives in one folder (default: data/ next to the program):
    watchdog.db database
    files/      uploaded documents under random names
    tmp/        uploads waiting for confirmation (cleaned after 24 hours)
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import Optional

import i18n
from docparse import CATEGORIES

ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp", ".gif",
               ".heic", ".txt", ".md", ".csv", ".rtf", ".docx", ".doc", ".odt",
               ".xlsx", ".xls", ".ods"}
INLINE_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_UPLOAD = 40 * 1024 * 1024
MAX_BODY = 100_000
DB_NAME = "watchdog.db"
LEGACY_DB_NAMES = ("keeper.db", "hlidac.db")      # names used by earlier versions (hlidac.db = the Czech-only one)
_TOKEN_RX = re.compile(r"^[0-9a-f]{32}$")
_STORED_RX = re.compile(r"files/[0-9a-f]{32}\.[a-z0-9]{1,5}")

# category ids of the first version -> current ids (existing data is migrated automatically)
LEGACY_CATEGORIES = {"pojisteni": "insurance", "stk": "vehicle", "revize": "inspection", "zaruka": "warranty",
                     "smlouva": "contract", "doklad": "id", "osvedceni": "license", "zdravi": "medical",
                     "faktura": "invoice", "ostatni": "other"}


class ValidationError(ValueError):
    """Bad input. `key` and `params` are turned into the user's language by i18n.t()."""

    def __init__(self, key: str, **params):
        self.key, self.params = key, params
        super().__init__(i18n.t("en", key, **params))

    def text(self, lang: str) -> str:
        return i18n.t(lang, self.key, **self.params)


# --------------------------------------------------------------------------
# Dates, status
# --------------------------------------------------------------------------
def parse_user_date(value: str) -> dt.date:
    value = (value or "").strip()
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{4})", value)
    if m:
        try:
            return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    raise ValidationError("err.bad_date")


def parse_remind_days(value: str) -> list:
    """'60, 30 14;7' -> [60, 30, 14, 7] (descending, no duplicates)."""
    days = set()
    for p in [p for p in re.split(r"[\s,;]+", (value or "").strip()) if p]:
        if not p.isdigit():
            raise ValidationError("err.remind_format")
        n = int(p)
        if n > 3650:
            raise ValidationError("err.remind_max")
        days.add(n)
    if len(days) > 12:
        raise ValidationError("err.remind_count")
    return sorted(days, reverse=True)


def days_left(expires: Optional[str], today: Optional[dt.date] = None) -> Optional[int]:
    if not expires:
        return None
    return (dt.date.fromisoformat(expires) - (today or dt.date.today())).days


def classify(expires: Optional[str], remind_days: list, today: Optional[dt.date] = None) -> dict:
    """-> {'key': expired | soon | ok | none, 'days': int or None}. Text comes from i18n.status_label."""
    d = days_left(expires, today)
    if d is None:
        return {"key": "none", "days": None}
    if d < 0:
        return {"key": "expired", "days": d}
    if d <= max(list(remind_days) + [0]):
        return {"key": "soon", "days": d}
    return {"key": "ok", "days": d}


def _clean_name(name: str) -> str:
    name = os.path.basename((name or "").replace("\\", "/"))
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().strip(".")
    return name[:120] or "file"


def validate_fields(title, category, expires, remind_days, note) -> dict:
    title = (title or "").strip()
    if not title:
        raise ValidationError("err.title_required")
    if len(title) > 200:
        raise ValidationError("err.title_long")
    category = (category or "other").strip()
    category = LEGACY_CATEGORIES.get(category, category)
    if category not in CATEGORIES:
        raise ValidationError("err.bad_category")
    exp_iso = parse_user_date(expires).isoformat() if (expires or "").strip() else None
    days = parse_remind_days(remind_days)
    note = (note or "").strip()
    if len(note) > 5000:
        raise ValidationError("err.note_long")
    return {"title": title, "category": category, "expires": exp_iso,
            "remind_days": ",".join(str(x) for x in days), "note": note}


def _now() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'other',
    expires TEXT,
    remind_days TEXT NOT NULL DEFAULT '30,14,7,1',
    note TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    search TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attachments(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    stored TEXT NOT NULL UNIQUE,
    size INTEGER NOT NULL,
    mime TEXT NOT NULL,
    added TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notified(
    doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    expires TEXT NOT NULL,
    threshold INTEGER NOT NULL,
    at TEXT NOT NULL,
    PRIMARY KEY(doc_id, expires, threshold)
);
CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Store:
    def __init__(self, data_dir, lang: Optional[str] = None):
        self.dir = Path(data_dir).resolve()
        self.files = self.dir / "files"
        self.tmp = self.dir / "tmp"
        self.lang_override = lang if lang in i18n.LANGS else None
        for p in (self.dir, self.files, self.tmp):
            p.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(self.dir, 0o700)
        self.db_path = self.dir / DB_NAME
        if not self.db_path.exists():                              # data of an earlier version
            for old_name in LEGACY_DB_NAMES:
                legacy = self.dir / old_name
                if legacy.exists():
                    for suffix in ("", "-wal", "-shm"):
                        with contextlib.suppress(OSError):
                            os.replace(str(legacy) + suffix, str(self.db_path) + suffix)
                    break
        self._init_db()
        self.cleanup_temp()

    def _init_db(self) -> None:
        with self.conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)
            for old, new in LEGACY_CATEGORIES.items():
                c.execute("UPDATE documents SET category=? WHERE category=?", (new, old))

    @contextlib.contextmanager
    def conn(self):
        c = sqlite3.connect(self.db_path, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    # ---- settings -----------------------------------------------------------
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self.conn() as c:
            row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.conn() as c:
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def get_lang(self) -> str:
        """--lang / WATCHDOG_LANG for one run, otherwise the saved setting, otherwise English."""
        if self.lang_override:
            return self.lang_override
        env = i18n.env("LANG")
        if env in i18n.LANGS:
            return env
        return i18n.norm_lang(self.get_setting("lang"))

    def set_lang(self, lang: str) -> None:
        self.set_setting("lang", i18n.norm_lang(lang))

    def get_date_order(self) -> str:
        saved = self.get_setting("date_order")
        return saved if saved in i18n.DATE_ORDERS else i18n.default_date_order(self.get_lang())

    def set_date_order(self, order: str) -> None:
        if order not in i18n.DATE_ORDERS:
            raise ValidationError("http.bad_request")
        self.set_setting("date_order", order)

    # ---- documents ------------------------------------------------------------
    @staticmethod
    def _search_blob(title: str, note: str, body: str) -> str:
        from docparse import fold
        return fold(f"{title}\n{note}\n{body}")

    def add_document(self, title, category="other", expires=None, remind_days="30,14,7,1",
                     note="", body="") -> int:
        f = validate_fields(title, category, expires, remind_days, note)
        body = (body or "")[:MAX_BODY]
        now = _now()
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO documents(title,category,expires,remind_days,note,body,search,created,updated)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (f["title"], f["category"], f["expires"], f["remind_days"], f["note"], body,
                 self._search_blob(f["title"], f["note"], body), now, now))
            return int(cur.lastrowid)

    def update_document(self, doc_id: int, title, category, expires, remind_days, note) -> None:
        f = validate_fields(title, category, expires, remind_days, note)
        with self.conn() as c:
            row = c.execute("SELECT body FROM documents WHERE id=?", (doc_id,)).fetchone()
            if row is None:
                raise KeyError(doc_id)
            c.execute(
                "UPDATE documents SET title=?,category=?,expires=?,remind_days=?,note=?,search=?,updated=?"
                " WHERE id=?",
                (f["title"], f["category"], f["expires"], f["remind_days"], f["note"],
                 self._search_blob(f["title"], f["note"], row["body"]), _now(), doc_id))

    def set_expiry(self, doc_id: int, expires: str) -> None:
        iso = parse_user_date(expires).isoformat()
        with self.conn() as c:
            cur = c.execute("UPDATE documents SET expires=?, updated=? WHERE id=?", (iso, _now(), doc_id))
            if cur.rowcount == 0:
                raise KeyError(doc_id)

    def get_document(self, doc_id: int):
        with self.conn() as c:
            return c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()

    def list_documents(self, query: str = "", category: str = "") -> list:
        from docparse import fold
        sql = ("SELECT d.id,d.title,d.category,d.expires,d.remind_days,d.note,d.created,d.updated,"
               "(SELECT COUNT(*) FROM attachments a WHERE a.doc_id=d.id) AS n_files FROM documents d")
        where, args = [], []
        for term in fold(query or "").split():
            esc = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where.append("d.search LIKE ? ESCAPE '\\'")
            args.append(f"%{esc}%")
        if category and category in CATEGORIES:
            where.append("d.category=?")
            args.append(category)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY (d.expires IS NULL), d.expires, d.title COLLATE NOCASE"
        with self.conn() as c:
            return c.execute(sql, args).fetchall()

    def delete_document(self, doc_id: int) -> None:
        with self.conn() as c:
            stored = [r["stored"] for r in
                      c.execute("SELECT stored FROM attachments WHERE doc_id=?", (doc_id,))]
            cur = c.execute("DELETE FROM documents WHERE id=?", (doc_id,))
            if cur.rowcount == 0:
                raise KeyError(doc_id)
        for name in stored:
            with contextlib.suppress(OSError):
                (self.files / name).unlink()

    # ---- attachments ------------------------------------------------------------
    @staticmethod
    def check_upload(filename: str, size: int) -> str:
        name = _clean_name(filename)
        if os.path.splitext(name)[1].lower() not in ALLOWED_EXT:
            raise ValidationError("err.file_type")
        if size <= 0:
            raise ValidationError("err.file_empty")
        if size > MAX_UPLOAD:
            raise ValidationError("err.file_big")
        return name

    def _store_file(self, doc_id: int, name: str, move_from: Optional[Path], data: Optional[bytes]) -> int:
        ext = os.path.splitext(name)[1].lower()
        stored = uuid.uuid4().hex + ext
        dest = self.files / stored
        if move_from is not None:
            shutil.move(str(move_from), dest)
        else:
            dest.write_bytes(data or b"")
        size = dest.stat().st_size
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        try:
            with self.conn() as c:
                cur = c.execute(
                    "INSERT INTO attachments(doc_id,filename,stored,size,mime,added) VALUES(?,?,?,?,?,?)",
                    (doc_id, name, stored, size, mime, _now()))
                return int(cur.lastrowid)
        except BaseException:
            with contextlib.suppress(OSError):
                dest.unlink()
            raise

    def add_attachment(self, doc_id: int, filename: str, data: bytes) -> int:
        name = self.check_upload(filename, len(data))
        if self.get_document(doc_id) is None:
            raise KeyError(doc_id)
        return self._store_file(doc_id, name, None, data)

    def list_attachments(self, doc_id: int) -> list:
        with self.conn() as c:
            return c.execute("SELECT * FROM attachments WHERE doc_id=? ORDER BY id", (doc_id,)).fetchall()

    def get_attachment(self, att_id: int):
        with self.conn() as c:
            return c.execute("SELECT * FROM attachments WHERE id=?", (att_id,)).fetchone()

    def attachment_path(self, att) -> Path:
        path = (self.files / att["stored"]).resolve()
        if path.parent != self.files.resolve():          # guard against a forged path
            raise ValueError("invalid file path")
        return path

    def delete_attachment(self, att_id: int) -> int:
        with self.conn() as c:
            row = c.execute("SELECT * FROM attachments WHERE id=?", (att_id,)).fetchone()
            if row is None:
                raise KeyError(att_id)
            c.execute("DELETE FROM attachments WHERE id=?", (att_id,))
        with contextlib.suppress(OSError):
            (self.files / row["stored"]).unlink()
        return int(row["doc_id"])

    # ---- uploads waiting for confirmation ------------------------------------------
    def save_temp(self, filename: str, data: bytes) -> str:
        name = self.check_upload(filename, len(data))
        token = uuid.uuid4().hex
        (self.tmp / f"{token}.bin").write_bytes(data)
        (self.tmp / f"{token}.json").write_text(
            json.dumps({"filename": name, "text": ""}, ensure_ascii=False), encoding="utf-8")
        return token

    def temp_info(self, token: str):
        """-> (path to the file, original name, text read from it) or None."""
        if not _TOKEN_RX.match(token or ""):
            return None
        meta, binf = self.tmp / f"{token}.json", self.tmp / f"{token}.bin"
        try:
            info = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not binf.exists():
            return None
        return binf, info.get("filename", "file"), info.get("text", "")

    def set_temp_text(self, token: str, text: str) -> None:
        got = self.temp_info(token)
        if got:
            (self.tmp / f"{token}.json").write_text(
                json.dumps({"filename": got[1], "text": text[:MAX_BODY]}, ensure_ascii=False),
                encoding="utf-8")

    def temp_to_attachment(self, token: str, doc_id: int) -> int:
        got = self.temp_info(token)
        if got is None:
            raise ValidationError("err.upload_gone")
        path, name, _ = got
        att = self._store_file(doc_id, name, path, None)
        with contextlib.suppress(OSError):
            (self.tmp / f"{token}.json").unlink()
        return att

    def discard_temp(self, token: str) -> None:
        if _TOKEN_RX.match(token or ""):
            for ext in (".bin", ".json"):
                with contextlib.suppress(OSError):
                    (self.tmp / f"{token}{ext}").unlink()

    def cleanup_temp(self, max_age_hours: float = 24) -> None:
        limit = time.time() - max_age_hours * 3600
        for p in self.tmp.iterdir():
            with contextlib.suppress(OSError):
                if p.is_file() and p.stat().st_mtime < limit:
                    p.unlink()

    # ---- notifications ----------------------------------------------------------------
    @staticmethod
    def thresholds(remind_days: str) -> list:
        return sorted({int(x) for x in remind_days.split(",") if x.strip().isdigit()} | {0}, reverse=True)

    def due_notifications(self, today: Optional[dt.date] = None) -> list:
        """Documents that just reached a reminder point and haven't been announced for it yet.

        Returns [{doc, days, threshold, applicable}]. Nothing is saved until mark_notified().
        """
        today = today or dt.date.today()
        out = []
        with self.conn() as c:
            docs = c.execute("SELECT id,title,category,expires,remind_days FROM documents "
                             "WHERE expires IS NOT NULL ORDER BY expires").fetchall()
            for doc in docs:
                d = days_left(doc["expires"], today)
                done = {r["threshold"] for r in c.execute(
                    "SELECT threshold FROM notified WHERE doc_id=? AND expires=?",
                    (doc["id"], doc["expires"]))}
                applicable = [-1] if d < 0 else [t for t in self.thresholds(doc["remind_days"]) if d <= t]
                if not applicable:
                    continue
                current = min(applicable)
                if current in done:
                    continue
                out.append({"doc": dict(doc), "days": d, "threshold": current, "applicable": applicable})
        return out

    def mark_notified(self, items: list) -> None:
        now = _now()
        with self.conn() as c:
            for it in items:
                for t in it["applicable"]:
                    c.execute("INSERT OR IGNORE INTO notified(doc_id,expires,threshold,at) VALUES(?,?,?,?)",
                              (it["doc"]["id"], it["doc"]["expires"], t, now))

    # ---- backup and restore -----------------------------------------------------------------
    def backup_to(self, dest) -> None:
        """Writes a consistent backup (database + files) to a zip file."""
        snap = Path(tempfile.mkdtemp(prefix="snap-", dir=self.tmp)) / DB_NAME
        try:
            src = sqlite3.connect(self.db_path, timeout=15)
            dst = sqlite3.connect(snap)
            with dst:
                src.backup(dst)
            dst.close()
            src.close()
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(snap, DB_NAME)
                for p in sorted(self.files.iterdir()):
                    if p.is_file():
                        z.write(p, f"files/{p.name}")
        finally:
            shutil.rmtree(snap.parent, ignore_errors=True)

    def restore_from(self, zip_path) -> Path:
        """Restores a backup. Current data is moved aside into a *-before-restore-* folder."""
        try:
            return self._restore(Path(zip_path))
        except zipfile.BadZipFile:
            raise ValidationError("err.restore_notzip")
        except sqlite3.DatabaseError:
            raise ValidationError("err.restore_corrupt")

    def _restore(self, zip_path: Path) -> Path:
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            db_name = next((n for n in (DB_NAME, *LEGACY_DB_NAMES) if n in names), None)
            if db_name is None:
                raise ValidationError("err.restore_nodb")
            for n in names:
                if n != db_name and not _STORED_RX.fullmatch(n):
                    raise ValidationError("err.restore_unexpected", name=n)
            stage = Path(tempfile.mkdtemp(prefix="restore-", dir=self.tmp))
            try:
                if sum(i.file_size for i in z.infolist()) > 8 * 1024 ** 3:
                    raise ValidationError("err.restore_big")
                (stage / "files").mkdir()
                (stage / DB_NAME).write_bytes(z.read(db_name))
                for n in names:
                    if n.startswith("files/"):
                        (stage / "files" / n[6:]).write_bytes(z.read(n))
                probe = sqlite3.connect(stage / DB_NAME)
                try:
                    tables = {r[0] for r in probe.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                finally:
                    probe.close()
                if not {"documents", "attachments"} <= tables:
                    raise ValidationError("err.restore_struct")
                stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
                old = self.dir.parent / f"{self.dir.name}-before-restore-{stamp}"
                old.mkdir()
                for item in (DB_NAME, DB_NAME + "-wal", DB_NAME + "-shm"):
                    if (self.dir / item).exists():
                        shutil.move(str(self.dir / item), old / item)
                if self.files.exists():
                    shutil.move(str(self.files), old / "files")
                shutil.move(str(stage / DB_NAME), self.dir / DB_NAME)
                shutil.move(str(stage / "files"), self.files)
            finally:
                shutil.rmtree(stage, ignore_errors=True)
        self.files.mkdir(exist_ok=True)
        self._init_db()                                  # also migrates category ids of old backups
        return old


# --------------------------------------------------------------------------
# Calendar (.ics)
# --------------------------------------------------------------------------
def _ics_escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n"))


def _ics_fold(line: str) -> str:
    if len(line.encode("utf-8")) <= 75:
        return line
    parts, cur, limit = [], b"", 75
    for ch in line:
        cb = ch.encode("utf-8")
        if len(cur) + len(cb) > limit:
            parts.append(cur.decode("utf-8"))
            cur, limit = b"", 74
        cur += cb
    parts.append(cur.decode("utf-8"))
    return "\r\n ".join(parts)


def _alarm_trigger(days: int) -> str:
    """Alert at 9:00 local time, `days` days before the end (the event is all-day and starts at 0:00)."""
    if days <= 0:
        return "PT9H"
    if days == 1:
        return "-PT15H"
    return f"-P{days - 1}DT15H"


def build_ics(docs, today: Optional[dt.date] = None, now: Optional[dt.datetime] = None,
              lang: str = "en") -> str:
    now = now or dt.datetime.now(dt.timezone.utc)
    stamp = now.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{i18n.APP_NAME}//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", "X-WR-CALNAME:" + _ics_escape(i18n.APP_NAME)]
    for doc in docs:
        if not doc["expires"]:
            continue
        start = dt.date.fromisoformat(doc["expires"])
        cat_key = LEGACY_CATEGORIES.get(doc["category"], doc["category"])
        label = i18n.category_label(lang, cat_key if cat_key in CATEGORIES else "other")
        desc = i18n.t(lang, "ics.category", cat=label)
        if doc["note"]:
            desc += f"\n{doc['note']}"
        try:
            seq = int(dt.datetime.fromisoformat(doc["updated"]).timestamp())
        except (ValueError, KeyError, TypeError):
            seq = 0
        lines += [
            "BEGIN:VEVENT",
            f"UID:{i18n.APP_SLUG}-{doc['id']}@localhost",
            f"DTSTAMP:{stamp}",
            f"SEQUENCE:{seq}",
            f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
            f"DTEND;VALUE=DATE:{start + dt.timedelta(days=1):%Y%m%d}",
            "SUMMARY:" + _ics_escape(i18n.t(lang, "ics.summary", title=doc["title"])),
            "DESCRIPTION:" + _ics_escape(desc),
            "CATEGORIES:" + _ics_escape(label),
            "TRANSP:TRANSPARENT",
        ]
        for n in Store.thresholds(doc["remind_days"]):
            text = i18n.t(lang, "ics.alarm", title=doc["title"], when=i18n.days_phrase(lang, n),
                          date=i18n.fmt_date(start, lang))
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:" + _ics_escape(text),
                      "TRIGGER:" + _alarm_trigger(n), "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_ics_fold(x) for x in lines) + "\r\n"
