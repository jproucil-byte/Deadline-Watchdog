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
import errno
import functools
import threading
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


MAX_TAGS = 10
MAX_TAG_LEN = 40
MAX_RECUR = 120                      # months
CUSTOM_CAT_RX = re.compile(r"^u_[0-9a-f]{8}$")


def parse_tags(value) -> list:
    """'Car, family ,car' -> ['Car', 'family'] (trimmed, no case-insensitive duplicates, original order)."""
    out, seen = [], set()
    for raw in re.split(r"[,;]+", value or ""):
        tag = re.sub(r"\s+", " ", raw).strip().lstrip("#").strip()
        if not tag:
            continue
        if len(tag) > MAX_TAG_LEN:
            raise ValidationError("err.tag_long", n=MAX_TAG_LEN)
        key = tag.casefold()
        if key not in seen:
            seen.add(key)
            out.append(tag)
    if len(out) > MAX_TAGS:
        raise ValidationError("err.tag_count", n=MAX_TAGS)
    return out


def parse_recur(value) -> int:
    """Number of months after which the deadline repeats (0 = it doesn't)."""
    value = str(value if value is not None else "").strip()
    if not value:
        return 0
    if not value.isdigit() or int(value) > MAX_RECUR:
        raise ValidationError("err.bad_recur")
    return int(value)


def validate_fields(title, category, expires, remind_days, note, tags="", recur="",
                    categories=None) -> dict:
    """`categories`: the category ids that may be used (default: the built-in ones)."""
    title = (title or "").strip()
    if not title:
        raise ValidationError("err.title_required")
    if len(title) > 200:
        raise ValidationError("err.title_long")
    category = (category or "other").strip()
    category = LEGACY_CATEGORIES.get(category, category)
    if category not in (categories if categories is not None else CATEGORIES):
        raise ValidationError("err.bad_category")
    exp_iso = parse_user_date(expires).isoformat() if (expires or "").strip() else None
    days = parse_remind_days(remind_days)
    note = (note or "").strip()
    if len(note) > 5000:
        raise ValidationError("err.note_long")
    return {"title": title, "category": category, "expires": exp_iso,
            "remind_days": ",".join(str(x) for x in days), "note": note,
            "tags": ",".join(parse_tags(tags)), "recur_months": parse_recur(recur)}


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
    updated TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '',
    recur_months INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0
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
CREATE TABLE IF NOT EXISTS categories(
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    remind TEXT NOT NULL DEFAULT '30,14,7,1',
    created TEXT NOT NULL
);
"""
# columns added after version 1.1 (older databases and backups get them when opened)
NEW_COLUMNS = (("tags", "TEXT NOT NULL DEFAULT ''"),
               ("recur_months", "INTEGER NOT NULL DEFAULT 0"),
               ("archived", "INTEGER NOT NULL DEFAULT 0"))
AUTO_BACKUP_RX = re.compile(r"^" + re.escape(i18n.APP_SLUG) + r"-auto-\d{4}-\d{2}-\d{2}-\d{6}\.zip$")


# One reentrant lock per data directory, shared by threads and by app/CLI processes.
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
_LOCK_STATE = threading.local()


def locked(method):
    @functools.wraps(method)
    def call(self, *args, **kwargs):
        with self.data_lock():
            return method(self, *args, **kwargs)
    return call


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
        with self.data_lock():
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

    @contextlib.contextmanager
    def data_lock(self):
        key = os.path.normcase(str(self.dir))
        with _LOCKS_GUARD:
            lock = _LOCKS.setdefault(key, threading.RLock())
        with lock:
            held = getattr(_LOCK_STATE, "held", None)
            if held is None:
                held = _LOCK_STATE.held = set()
            if key in held:
                yield
                return
            with open(self.dir / ".watchdog.lock", "a+b") as fh:
                if os.name == "nt":
                    import msvcrt
                    if fh.tell() == 0:
                        fh.write(b"0")
                        fh.flush()
                    while True:
                        fh.seek(0)
                        try:
                            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                            break
                        except OSError as exc:
                            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                                raise
                            time.sleep(0.05)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                held.add(key)
                try:
                    yield
                finally:
                    held.remove(key)
                    if os.name == "nt":
                        fh.seek(0)
                        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def _init_db(self) -> None:
        with self.conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)
            have = {r["name"] for r in c.execute("PRAGMA table_info(documents)")}
            for name, decl in NEW_COLUMNS:
                if name not in have:
                    c.execute(f"ALTER TABLE documents ADD COLUMN {name} {decl}")
            for old, new in LEGACY_CATEGORIES.items():
                c.execute("UPDATE documents SET category=? WHERE category=?", (new, old))

    @contextlib.contextmanager
    def conn(self):
        with self.data_lock():
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
    def _search_blob(title: str, note: str, body: str, tags: str = "") -> str:
        from docparse import fold
        return fold(f"{title}\n{tags.replace(',', ' ')}\n{note}\n{body}")

    def validate(self, title, category, expires, remind_days, note, tags="", recur="") -> dict:
        return validate_fields(title, category, expires, remind_days, note, tags, recur,
                               categories=self.categories())

    @locked
    def add_document(self, title, category="other", expires=None, remind_days="30,14,7,1",
                     note="", body="", tags="", recur="", upload_token="") -> int:
        f = self.validate(title, category, expires, remind_days, note, tags, recur)
        body = (body or "")[:MAX_BODY]
        now = _now()
        upload = self.temp_info(upload_token) if upload_token else None
        if upload_token and upload is None:
            raise ValidationError("err.upload_gone")
        dest = None
        try:
            with self.conn() as c:
                cur = c.execute(
                    "INSERT INTO documents(title,category,expires,remind_days,note,body,search,created,updated,"
                    "tags,recur_months) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (f["title"], f["category"], f["expires"], f["remind_days"], f["note"], body,
                     self._search_blob(f["title"], f["note"], body, f["tags"]), now, now,
                     f["tags"], f["recur_months"]))
                doc_id = int(cur.lastrowid)
                if upload:
                    path, name, _ = upload
                    stored = uuid.uuid4().hex + Path(name).suffix.lower()
                    dest = self.files / stored
                    shutil.copyfile(path, dest)
                    c.execute("INSERT INTO attachments(doc_id,filename,stored,size,mime,added) VALUES(?,?,?,?,?,?)",
                              (doc_id, name, stored, dest.stat().st_size,
                               mimetypes.guess_type(name)[0] or "application/octet-stream", now))
        except BaseException:
            if dest is not None:
                with contextlib.suppress(OSError):
                    dest.unlink()
            raise
        if upload_token:
            self.discard_temp(upload_token)
        return doc_id

    def update_document(self, doc_id: int, title, category, expires, remind_days, note,
                        tags=None, recur=None) -> None:
        """tags / recur = None keeps the saved value."""
        with self.conn() as c:
            row = c.execute("SELECT body,tags,recur_months FROM documents WHERE id=?", (doc_id,)).fetchone()
            if row is None:
                raise KeyError(doc_id)
            f = self.validate(title, category, expires, remind_days, note,
                              row["tags"] if tags is None else tags,
                              row["recur_months"] if recur is None else recur)
            c.execute(
                "UPDATE documents SET title=?,category=?,expires=?,remind_days=?,note=?,search=?,updated=?,"
                "tags=?,recur_months=? WHERE id=?",
                (f["title"], f["category"], f["expires"], f["remind_days"], f["note"],
                 self._search_blob(f["title"], f["note"], row["body"], f["tags"]), _now(),
                 f["tags"], f["recur_months"], doc_id))

    def set_archived(self, doc_id: int, archived: bool) -> None:
        with self.conn() as c:
            cur = c.execute("UPDATE documents SET archived=?, updated=? WHERE id=?",
                            (1 if archived else 0, _now(), doc_id))
            if cur.rowcount == 0:
                raise KeyError(doc_id)

    def renew_by_interval(self, doc_id: int, today: Optional[dt.date] = None) -> str:
        """Moves the end date by the document's repeat interval (as many periods as needed to reach today)."""
        from docparse import add_months
        today = today or dt.date.today()
        doc = self.get_document(doc_id)
        if doc is None:
            raise KeyError(doc_id)
        months = int(doc["recur_months"] or 0)
        if months <= 0:
            raise ValidationError("err.no_recur")
        start = dt.date.fromisoformat(doc["expires"]) if doc["expires"] else today
        n = 1
        new = add_months(start, months)
        while new < today and n < 1000:
            n += 1
            new = add_months(start, months * n)       # from the original date, so the 31st stays the 31st
        self.set_expiry(doc_id, new.isoformat())
        return new.isoformat()

    def set_expiry(self, doc_id: int, expires: str) -> None:
        iso = parse_user_date(expires).isoformat()
        with self.conn() as c:
            cur = c.execute("UPDATE documents SET expires=?, updated=? WHERE id=?", (iso, _now(), doc_id))
            if cur.rowcount == 0:
                raise KeyError(doc_id)

    def get_document(self, doc_id: int):
        with self.conn() as c:
            return c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()

    def list_documents(self, query: str = "", category: str = "", tag: str = "",
                       archived: Optional[bool] = False) -> list:
        """Archived documents are left out unless archived=True (only them) or None (everything)."""
        from docparse import fold
        sql = ("SELECT d.id,d.title,d.category,d.expires,d.remind_days,d.note,d.created,d.updated,"
               "d.tags,d.recur_months,d.archived,"
               "(SELECT COUNT(*) FROM attachments a WHERE a.doc_id=d.id) AS n_files FROM documents d")
        where, args = [], []
        if archived is not None:
            where.append("d.archived=?")
            args.append(1 if archived else 0)
        for term in fold(query or "").split():
            esc = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where.append("d.search LIKE ? ESCAPE '\\'")
            args.append(f"%{esc}%")
        if category and category in self.categories():
            where.append("d.category=?")
            args.append(category)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY (d.expires IS NULL), d.expires, d.title COLLATE NOCASE"
        with self.conn() as c:
            rows = c.execute(sql, args).fetchall()
        if tag:
            want = tag.strip().casefold()
            rows = [r for r in rows if want in (t.casefold() for t in r["tags"].split(",") if t)]
        return rows

    def all_tags(self) -> list:
        """[(tag, number of documents)] for documents that aren't archived, sorted by name."""
        counts, names = {}, {}
        with self.conn() as c:
            for r in c.execute("SELECT tags FROM documents WHERE archived=0 AND tags<>''"):
                for t in r["tags"].split(","):
                    if t:
                        k = t.casefold()
                        counts[k] = counts.get(k, 0) + 1
                        names.setdefault(k, t)
        return [(names[k], counts[k]) for k in sorted(names, key=lambda k: names[k].casefold())]

    def count_archived(self) -> int:
        with self.conn() as c:
            return int(c.execute("SELECT COUNT(*) FROM documents WHERE archived=1").fetchone()[0])

    # ---- categories (built-in + the user's own) ------------------------------------
    def custom_categories(self) -> list:
        with self.conn() as c:
            return c.execute("SELECT c.id,c.label,c.remind,"
                             "(SELECT COUNT(*) FROM documents d WHERE d.category=c.id) AS n_docs "
                             "FROM categories c ORDER BY c.label COLLATE NOCASE").fetchall()

    def categories(self) -> dict:
        """id -> {'remind': '60,30,...', 'label': None for built-in ones (translated) or the user's text}."""
        out = {k: {"remind": m["remind"], "label": None} for k, m in CATEGORIES.items()}
        for r in self.custom_categories():
            out[r["id"]] = {"remind": r["remind"], "label": r["label"]}
        return out

    def category_labels(self, lang: str) -> dict:
        return {k: (m["label"] or i18n.category_label(lang, k)) for k, m in self.categories().items()}

    def add_category(self, label: str, remind: str = "30,14,7,1") -> str:
        label = re.sub(r"\s+", " ", label or "").strip()
        if not label:
            raise ValidationError("err.cat_label_required")
        if len(label) > 60:
            raise ValidationError("err.cat_label_long")
        days = ",".join(str(x) for x in parse_remind_days(remind)) or "30,14,7,1"
        taken = {v.casefold() for lang in i18n.LANGS for v in self.category_labels(lang).values()}
        if label.casefold() in taken:
            raise ValidationError("err.cat_exists")
        cat_id = "u_" + uuid.uuid4().hex[:8]
        with self.conn() as c:
            c.execute("INSERT INTO categories(id,label,remind,created) VALUES(?,?,?,?)",
                      (cat_id, label, days, _now()))
        return cat_id

    def delete_category(self, cat_id: str) -> int:
        """Deletes one of the user's categories; its documents move to 'other'. Returns how many moved."""
        if not CUSTOM_CAT_RX.match(cat_id or ""):
            raise KeyError(cat_id)
        with self.conn() as c:
            if c.execute("DELETE FROM categories WHERE id=?", (cat_id,)).rowcount == 0:
                raise KeyError(cat_id)
            return c.execute("UPDATE documents SET category='other' WHERE category=?", (cat_id,)).rowcount

    @locked
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

    @locked
    def _store_file(self, doc_id: int, name: str, move_from: Optional[Path], data: Optional[bytes]) -> int:
        ext = os.path.splitext(name)[1].lower()
        stored = uuid.uuid4().hex + ext
        dest = self.files / stored
        try:
            if move_from is not None:
                shutil.copyfile(move_from, dest)
            else:
                dest.write_bytes(data or b"")
            size = dest.stat().st_size
            mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
            with self.conn() as c:
                cur = c.execute(
                    "INSERT INTO attachments(doc_id,filename,stored,size,mime,added) VALUES(?,?,?,?,?,?)",
                    (doc_id, name, stored, size, mime, _now()))
                att_id = int(cur.lastrowid)
            if move_from is not None:
                with contextlib.suppress(OSError):
                    move_from.unlink()
            return att_id
        except BaseException:
            with contextlib.suppress(OSError):
                dest.unlink()
            raise

    @locked
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

    @locked
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
    @locked
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

    @locked
    def temp_to_attachment(self, token: str, doc_id: int) -> int:
        got = self.temp_info(token)
        if got is None:
            raise ValidationError("err.upload_gone")
        path, name, _ = got
        att = self._store_file(doc_id, name, path, None)
        with contextlib.suppress(OSError):
            (self.tmp / f"{token}.json").unlink()
        return att

    @locked
    def discard_temp(self, token: str) -> None:
        if _TOKEN_RX.match(token or ""):
            for ext in (".bin", ".json"):
                with contextlib.suppress(OSError):
                    (self.tmp / f"{token}{ext}").unlink()

    @locked
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
                             "WHERE expires IS NOT NULL AND archived=0 ORDER BY expires").fetchall()
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
    @locked
    def missing_attachments(self) -> list:
        """Attachments whose file is no longer on disk: [{'doc_id', 'title', 'filename', 'stored'}]."""
        with self.conn() as c:
            rows = c.execute("SELECT a.doc_id, d.title, a.filename, a.stored FROM attachments a "
                             "JOIN documents d ON d.id=a.doc_id ORDER BY d.title COLLATE NOCASE, a.id").fetchall()
        return [dict(r) for r in rows
                if not _STORED_RX.fullmatch(f"files/{r['stored']}") or not (self.files / r["stored"]).is_file()]

    @locked
    def backup_to(self, dest) -> list:
        """Writes a consistent backup (database + files) to a zip file.

        A file that has gone missing from disk doesn't stop the backup – everything else is still
        saved. Returns the stored names of such files (empty list = the backup is complete)."""
        dest = Path(dest)
        # Write next to the destination so publishing the finished archive is atomic.
        fd, part_name = tempfile.mkstemp(prefix=dest.name + ".", suffix=".part", dir=dest.parent)
        os.close(fd)
        part = Path(part_name)
        snap_dir = Path(tempfile.mkdtemp(prefix="snap-", dir=self.tmp))
        snap = snap_dir / DB_NAME
        try:
            with contextlib.closing(sqlite3.connect(self.db_path, timeout=15)) as src, \
                    contextlib.closing(sqlite3.connect(snap)) as dst:
                src.backup(dst)
                referenced = [r[0] for r in dst.execute("SELECT stored FROM attachments")]
            missing = [name for name in referenced
                       if not _STORED_RX.fullmatch(f"files/{name}") or not (self.files / name).is_file()]
            with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(snap, DB_NAME)
                for p in sorted(self.files.iterdir()):
                    if p.is_file() and _STORED_RX.fullmatch(f"files/{p.name}"):
                        z.write(p, f"files/{p.name}")
            os.replace(part, dest)
            return missing
        finally:
            with contextlib.suppress(OSError):
                part.unlink()
            shutil.rmtree(snap_dir, ignore_errors=True)

    @locked
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
                if n == db_name or _STORED_RX.fullmatch(n):
                    continue
                if n == "files/" or (n.startswith("files/") and "/" not in n[6:] and ".." not in n
                                     and "\\" not in n):
                    continue                     # a folder entry or a stray system file (Thumbs.db…): skipped
                raise ValidationError("err.restore_unexpected", name=n)
            stage = Path(tempfile.mkdtemp(prefix="restore-", dir=self.tmp))
            try:
                if sum(i.file_size for i in z.infolist()) > 8 * 1024 ** 3:
                    raise ValidationError("err.restore_big")
                (stage / "files").mkdir()
                with z.open(db_name) as src, open(stage / DB_NAME, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                for n in names:
                    if _STORED_RX.fullmatch(n):
                        with z.open(n) as src, open(stage / "files" / n[6:], "wb") as dst:
                            shutil.copyfileobj(src, dst)
                # Validate the schema before migration, including optional tables when present.
                with contextlib.closing(sqlite3.connect(stage / DB_NAME)) as probe, \
                        contextlib.closing(sqlite3.connect(":memory:")) as expected:
                    expected.executescript(SCHEMA)
                    tables = {r[0] for r in probe.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if not {"documents", "attachments"} <= tables:
                        raise ValidationError("err.restore_struct")
                    for table in ("documents", "attachments", "settings", "notified", "categories"):
                        if table not in tables:
                            continue
                        required = {r[1] for r in expected.execute(f"PRAGMA table_info({table})")}
                        if table == "documents":
                            required -= {name for name, _ in NEW_COLUMNS}
                        actual = {r[1] for r in probe.execute(f"PRAGMA table_info({table})")}
                        if not required <= actual:
                            raise ValidationError("err.restore_struct")
                    if probe.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                        raise ValidationError("err.restore_corrupt")
                staged = Store(stage)
                with staged.conn() as c:
                    if c.execute("PRAGMA foreign_key_check").fetchone():
                        raise ValidationError("err.restore_corrupt")
                    for att in c.execute("SELECT stored,size FROM attachments"):
                        name = att["stored"]
                        if not _STORED_RX.fullmatch(f"files/{name}"):
                            raise ValidationError("err.restore_struct")
                        path = staged.files / name
                        # A file that was already missing when the backup was made is no reason to refuse
                        # everything else; a file that is there but has the wrong size is damage.
                        if path.is_file() and path.stat().st_size != att["size"]:
                            raise ValidationError("err.restore_corrupt")
                # All staged connections are closed before moving the migrated database.
                stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                old = self.dir.parent / f"{self.dir.name}-before-restore-{stamp}"
                old.mkdir()
                moves = []
                try:
                    for item in (DB_NAME, DB_NAME + "-wal", DB_NAME + "-shm", "files"):
                        source = self.dir / item
                        if source.exists():
                            target = old / item
                            os.replace(source, target)
                            moves.append((source, target))
                    for item in (DB_NAME, "files"):
                        source, target = stage / item, self.dir / item
                        os.replace(source, target)
                        moves.append((source, target))
                except BaseException:
                    for source, target in reversed(moves):
                        os.replace(target, source)
                    raise
            finally:
                shutil.rmtree(stage, ignore_errors=True)
        self.files.mkdir(exist_ok=True)
        return old

    # ---- automatic backup ------------------------------------------------------------------
    def auto_backup_config(self) -> dict:
        def num(key, default, lo, hi):
            try:
                return min(max(int(self.get_setting(key, str(default))), lo), hi)
            except (TypeError, ValueError):
                return default
        return {"dir": self.get_setting("autobackup_dir", "") or "",
                "days": num("autobackup_days", 7, 1, 365),
                "keep": num("autobackup_keep", 5, 1, 100),
                "last": self.get_setting("autobackup_last", "") or "",
                "error": self.get_setting("autobackup_error", "") or ""}

    def set_auto_backup(self, folder: str, days, keep) -> None:
        """Empty folder = automatic backup off."""
        folder = (folder or "").strip().strip('"')
        if folder:
            path = Path(os.path.expandvars(os.path.expanduser(folder)))
            if not path.is_absolute():
                raise ValidationError("err.ab_relative")
            resolved = path.resolve()
            if resolved == self.dir or self.dir in resolved.parents:
                raise ValidationError("err.ab_inside")
            folder = str(path)
        try:
            days, keep = int(str(days).strip()), int(str(keep).strip())
        except ValueError:
            raise ValidationError("err.ab_numbers")
        if not (1 <= days <= 365 and 1 <= keep <= 100):
            raise ValidationError("err.ab_numbers")
        self.set_setting("autobackup_dir", folder)
        self.set_setting("autobackup_days", str(days))
        self.set_setting("autobackup_keep", str(keep))
        self.set_setting("autobackup_error", "")

    def auto_backup_due(self, now: Optional[dt.datetime] = None) -> bool:
        cfg = self.auto_backup_config()
        if not cfg["dir"]:
            return False
        now = now or dt.datetime.now()
        try:
            last = dt.datetime.fromisoformat(cfg["last"])
        except ValueError:
            return True
        return now - last >= dt.timedelta(days=cfg["days"]) or last > now

    @locked
    def run_auto_backup(self, force: bool = False, now: Optional[dt.datetime] = None) -> Optional[Path]:
        """Saves a backup into the configured folder if one is due (or force=True), keeps the newest N.

        Returns the new file, or None when nothing was due. A failure is remembered for the
        Settings page and raised as OSError."""
        cfg = self.auto_backup_config()
        if not cfg["dir"] or not (force or self.auto_backup_due(now)):
            return None
        now = now or dt.datetime.now()
        folder = Path(cfg["dir"])
        dest = folder / f"{i18n.APP_SLUG}-auto-{now:%Y-%m-%d-%H%M%S}.zip"
        part = folder / (dest.name + ".part")
        try:
            folder.mkdir(parents=True, exist_ok=True)
            stale = time.time() - 3600           # leftovers of a backup that was interrupted (power cut…)
            for p in folder.iterdir():
                with contextlib.suppress(OSError):
                    if (p.is_file() and p.name.startswith(i18n.APP_SLUG + "-auto-") and p.name.endswith(".part")
                            and p.stat().st_mtime < stale):
                        p.unlink()
            self.backup_to(part)
            os.replace(part, dest)
            ours = sorted(p for p in folder.iterdir() if p.is_file() and AUTO_BACKUP_RX.match(p.name))
            for p in ours[:-cfg["keep"]]:
                with contextlib.suppress(OSError):
                    p.unlink()
        except OSError as e:
            with contextlib.suppress(OSError):
                part.unlink()
            with contextlib.suppress(sqlite3.Error):
                self.set_setting("autobackup_error", f"{now:%Y-%m-%d %H:%M} – {e}")
            raise
        self.set_setting("autobackup_last", now.replace(microsecond=0).isoformat(sep=" "))
        self.set_setting("autobackup_error", "")
        return dest


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


def _rrule(months: int) -> Optional[str]:
    if not months:
        return None
    if months % 12 == 0:
        return f"RRULE:FREQ=YEARLY;INTERVAL={months // 12}"
    return f"RRULE:FREQ=MONTHLY;INTERVAL={months}"


def build_ics(docs, today: Optional[dt.date] = None, now: Optional[dt.datetime] = None,
              lang: str = "en", labels: Optional[dict] = None) -> str:
    """`labels`: category id -> label, for the user's own categories (Store.category_labels)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    stamp = now.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{i18n.APP_NAME}//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", "X-WR-CALNAME:" + _ics_escape(i18n.APP_NAME)]
    for doc in docs:
        if not doc["expires"]:
            continue
        start = dt.date.fromisoformat(doc["expires"])
        cat_key = LEGACY_CATEGORIES.get(doc["category"], doc["category"])
        if labels and cat_key in labels:
            label = labels[cat_key]
        else:
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
        try:
            rule = _rrule(int(doc["recur_months"] or 0))
        except (KeyError, IndexError, TypeError, ValueError):
            rule = None
        if rule:
            lines.append(rule)
        for n in Store.thresholds(doc["remind_days"]):
            text = i18n.t(lang, "ics.alarm", title=doc["title"], when=i18n.days_phrase(lang, n),
                          date=i18n.fmt_date(start, lang))
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:" + _ics_escape(text),
                      "TRIGGER:" + _alarm_trigger(n), "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_ics_fold(x) for x in lines) + "\r\n"
