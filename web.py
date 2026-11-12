# Deadline Watchdog – author: jproucil-byte – https://github.com/jproucil-byte/Deadline-Watchdog
"""Web interface. The server listens on 127.0.0.1 only (not reachable from other devices).

Protections: Host header check (against DNS rebinding), Origin check plus a secret token in
every form (against CSRF), CSP with a nonce, uploaded files are never served as web pages.
"""
from __future__ import annotations

import datetime as dt
import hmac
import html
import http.client
import json
import os
import re
import secrets
import shutil
import socket
import sys
import tempfile
import threading
import traceback
import urllib.parse
import webbrowser
from email.parser import BytesParser
from email.policy import HTTP as HTTP_POLICY
from email.utils import collapse_rfc2231_value
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

import docparse
import i18n
import scheduler
import store as S

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
ACCEPT = ",".join(sorted(S.ALLOWED_EXT))
FLASH = {"saved", "created", "deleted", "renewed", "uploaded", "filedeleted", "settings", "archived",
         "unarchived", "cat_added", "cat_deleted", "ab_saved", "ab_done", "sched_on", "sched_off", "test_sent"}
RECUR_CHOICES = (0, 1, 3, 6, 12, 24, 36, 48, 60, 120)          # months
SYMBOL = {"expired": "✕", "soon": "!", "ok": "✓", "none": "–"}
NAV = [("/", "nav.overview"), ("/new", "nav.add"), ("/export", "nav.export"), ("/settings", "nav.settings")]


def esc(value) -> str:
    return html.escape(str(value), quote=True)


# --------------------------------------------------------------------------
# Look
# --------------------------------------------------------------------------
CSS = """
:root{--bg:#f4f6f8;--card:#fff;--ink:#16202a;--muted:#5a6672;--line:#dfe4ea;--accent:#14639e;--accent-ink:#fff;
--accent-soft:#e8f1f8;--red:#b3261e;--red-bg:#fdecea;--amber:#7a5200;--amber-bg:#fff2cc;--green:#1e6b3c;
--green-bg:#e4f3e9;--gray:#4a5560;--gray-bg:#eaeef2;--radius:12px;
--shadow:0 1px 2px rgba(16,24,40,.05),0 1px 3px rgba(16,24,40,.07)}
@media (prefers-color-scheme:dark){:root{--bg:#0f1418;--card:#171d23;--ink:#e8edf2;--muted:#9aa6b2;--line:#28323b;
--accent:#62b3f2;--accent-ink:#06121c;--accent-soft:#15293a;--red:#ff9088;--red-bg:#3b1b19;--amber:#f3c870;
--amber-bg:#3a2e10;--green:#86d6a5;--green-bg:#12301f;--gray:#b6c0ca;--gray-bg:#232b33;--shadow:none}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
a{color:var(--accent)}
.wrap{max-width:980px;margin:0 auto;padding:0 16px}
header.top{background:var(--card);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
header.top .wrap{display:flex;align-items:center;gap:16px;min-height:58px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:8px;font-weight:700;color:var(--ink);text-decoration:none;font-size:1.05rem}
.brand svg{color:var(--accent)}
nav{display:flex;gap:4px;margin-left:auto;flex-wrap:wrap}
nav a{padding:8px 12px;border-radius:8px;text-decoration:none;color:var(--muted);font-weight:500}
nav a:hover{background:var(--gray-bg);color:var(--ink)}
nav a[aria-current=page]{background:var(--accent-soft);color:var(--accent)}
main{padding:24px 0 24px}
h1{font-size:1.55rem;line-height:1.25;margin:0 0 16px}h2{font-size:1.08rem;margin:0 0 12px}
p{margin:0 0 12px}.muted{color:var(--muted)}.small{font-size:.88rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:18px;box-shadow:var(--shadow);margin-bottom:16px}
.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px}
.tile{display:block;text-decoration:none;color:var(--ink);background:var(--card);border:1px solid var(--line);
border-top:4px solid var(--c);border-radius:var(--radius);padding:12px 16px;box-shadow:var(--shadow)}
.tile .n{display:block;font-size:1.85rem;font-weight:700;line-height:1.15;color:var(--c)}
.tile .l{display:block;color:var(--muted);font-size:.9rem}
.tile[aria-current=true]{outline:2px solid var(--accent);outline-offset:2px}
.expired{--c:var(--red)}.soon{--c:var(--amber)}.ok{--c:var(--green)}.none{--c:var(--gray)}
.search{display:grid;grid-template-columns:1fr 220px auto;gap:10px;margin-bottom:16px}
.docs{display:flex;flex-direction:column;gap:8px}
a.doc{display:grid;grid-template-columns:1fr auto auto;align-items:center;gap:16px;background:var(--card);
border:1px solid var(--line);border-left:5px solid var(--c,var(--line));border-radius:var(--radius);padding:12px 16px;
text-decoration:none;color:var(--ink);box-shadow:var(--shadow)}
a.doc:hover{border-color:var(--accent);border-left-color:var(--c,var(--accent))}
.doc-title{display:block;font-weight:600;overflow-wrap:anywhere}.doc-meta{display:block;color:var(--muted);font-size:.88rem}
.doc-when{text-align:right}.doc-when .date{display:block;font-variant-numeric:tabular-nums}
.doc-when .rel{display:block;color:var(--muted);font-size:.88rem}
.badge{display:inline-block;padding:3px 10px;border-radius:999px;font-size:.82rem;font-weight:600;white-space:nowrap}
.badge.expired{background:var(--red-bg);color:var(--red)}.badge.soon{background:var(--amber-bg);color:var(--amber)}
.badge.ok{background:var(--green-bg);color:var(--green)}.badge.none{background:var(--gray-bg);color:var(--gray)}
label{display:block;font-weight:600;margin:0 0 4px}.hint{color:var(--muted);font-size:.86rem;font-weight:400}
input[type=text],input[type=date],input[type=search],select,textarea{width:100%;font:inherit;color:var(--ink);
background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px 12px;min-height:44px}
textarea{min-height:92px;resize:vertical}
label.radio{display:flex;gap:10px;align-items:flex-start;font-weight:400;margin:0 0 10px}
label.radio input{margin-top:5px}
fieldset{border:0;margin:0 0 14px;padding:0}legend{font-weight:600;padding:0;margin:0 0 8px}
input:focus,select:focus,textarea:focus,.btn:focus-visible,a:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.field{margin-bottom:14px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:44px;padding:0 18px;border-radius:10px;
border:1px solid var(--accent);background:var(--accent);color:var(--accent-ink);font:inherit;font-weight:600;cursor:pointer;text-decoration:none}
.btn.secondary{background:transparent;color:var(--accent)}.btn.danger{background:transparent;color:var(--red);border-color:var(--red)}
.btn.small{min-height:36px;padding:0 12px;font-size:.9rem}
.actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.alert{border-radius:10px;padding:12px 14px;margin-bottom:16px;border:1px solid var(--line)}
.alert.ok{background:var(--green-bg);color:var(--green);border-color:var(--green)}
.alert.err{background:var(--red-bg);color:var(--red);border-color:var(--red)}
.alert.warn{background:var(--amber-bg);color:var(--amber);border-color:var(--amber)}
.alert.info{background:var(--accent-soft);color:var(--ink)}
.alert ul{margin:6px 0 0;padding-left:20px}
.drop-area{position:relative;display:flex;align-items:center;justify-content:center;text-align:center;min-height:150px;
border:2px dashed var(--accent);border-radius:var(--radius);background:var(--accent-soft);padding:24px;cursor:pointer;margin-bottom:14px}
.drop-area input[type=file]{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer}
.drop-area:focus-within{outline:2px solid var(--accent);outline-offset:2px}
form.busy .drop-area{opacity:.6}
.layout{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,2fr);gap:16px;align-items:start}
.files{list-style:none;margin:0 0 12px;padding:0}
.files li{padding:10px 0;border-top:1px solid var(--line)}.files li:first-child{border-top:0}
.fname{overflow-wrap:anywhere;font-weight:600}
.thumb{display:block;max-width:100%;max-height:150px;border-radius:8px;border:1px solid var(--line);margin:8px 0}
pre.text{white-space:pre-wrap;overflow-wrap:anywhere;max-height:320px;overflow:auto;background:var(--bg);
border:1px solid var(--line);border-radius:8px;padding:10px;font-size:.85rem;margin:8px 0 0}
details summary{cursor:pointer;font-weight:600}
code,kbd{font:.9em ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:var(--gray-bg);padding:2px 6px;border-radius:6px}
pre.cmd{background:var(--gray-bg);padding:12px;border-radius:8px;overflow:auto;font:.88rem ui-monospace,Menlo,Consolas,monospace;margin:8px 0 12px}
.foot{color:var(--muted);font-size:.85rem;padding:8px 0 32px}
.cap li{margin-bottom:4px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 14px}
.chip{display:inline-block;padding:3px 10px;border-radius:999px;background:var(--gray-bg);color:var(--ink);
text-decoration:none;font-size:.85rem;border:1px solid transparent}
a.chip:hover{border-color:var(--accent)}.chip[aria-current=true]{background:var(--accent-soft);color:var(--accent);border-color:var(--accent)}
.chip .c{color:var(--muted);margin-left:4px}
.more{margin:14px 0 0}
table.list{width:100%;border-collapse:collapse}table.list td{padding:8px 0;border-top:1px solid var(--line);vertical-align:middle}
table.list tr:first-child td{border-top:0}table.list td.r{text-align:right}
@media(max-width:700px){.tiles{gap:8px}.tile{padding:10px 12px}.search,.grid2,.layout{grid-template-columns:1fr}
a.doc{grid-template-columns:1fr auto}a.doc .badge{grid-column:1;grid-row:2;justify-self:start}
.doc-when{grid-column:2;grid-row:1/3}header.top{position:static}header.top .wrap{gap:0;min-height:0;padding-top:4px;padding-bottom:2px}.brand{padding:6px 0}nav{width:100%;margin-left:0;gap:0;justify-content:space-between}nav a{padding:8px 10px;font-size:.95rem}}
"""

JS = """
(function(){
  document.querySelectorAll('form[data-confirm]').forEach(function(f){
    f.addEventListener('submit',function(e){if(!window.confirm(f.getAttribute('data-confirm')))e.preventDefault();});
  });
  var up=document.getElementById('upload');
  if(up){var inp=up.querySelector('input[type=file]');
    inp.addEventListener('change',function(){if(inp.files.length){up.classList.add('busy');
      up.querySelector('.drop-text').textContent=up.getAttribute('data-busy');up.submit();}});}
  document.querySelectorAll('[data-date]').forEach(function(b){
    b.addEventListener('click',function(){var i=document.getElementById('expires');if(i){i.value=b.getAttribute('data-date');}});});
  var cat=document.getElementById('category'),rem=document.getElementById('remind_days');
  if(cat&&rem&&cat.getAttribute('data-defaults')){var defs={};try{defs=JSON.parse(cat.getAttribute('data-defaults'));}catch(e){}
    rem.addEventListener('input',function(){rem.setAttribute('data-touched','1');});
    cat.addEventListener('change',function(){if(!rem.getAttribute('data-touched')&&defs[cat.value]){rem.value=defs[cat.value];}});}
  var flt=document.getElementById('cat-filter');
  if(flt){flt.addEventListener('change',function(){flt.form.submit();});}
})();
"""

FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E"
           "%3Crect x='3' y='4.5' width='18' height='16' rx='3.5' fill='none' stroke='%2314639e' stroke-width='2'/%3E"
           "%3Cpath d='M3 9.5h18M8 3v4M16 3v4' stroke='%2314639e' stroke-width='2' stroke-linecap='round' fill='none'/%3E"
           "%3Cpath d='m9 15 2.2 2.2L15.5 13' stroke='%2314639e' stroke-width='2' stroke-linecap='round' "
           "stroke-linejoin='round' fill='none'/%3E%3C/svg%3E")

LOGO = ('<svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4.5" width="18" height="16" rx="3.5" '
        'fill="none" stroke="currentColor" stroke-width="2"/><path d="M3 9.5h18M8 3v4M16 3v4" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" fill="none"/><path d="m9 15 2.2 2.2L15.5 13" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>')


class HttpError(Exception):
    def __init__(self, status: int, key: str, **params):
        super().__init__(key)
        self.status, self.key, self.params = status, key, params


# --------------------------------------------------------------------------
# Forms
# --------------------------------------------------------------------------
def _fix_name(name: str) -> str:
    if any("\udc80" <= ch <= "\udcff" for ch in name):
        return name.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    return name


def parse_multipart(content_type: str, body: bytes):
    raw = (b"Content-Type: " + content_type.encode("latin-1", "replace")
           + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
    msg = BytesParser(policy=HTTP_POLICY).parsebytes(raw)
    if not msg.is_multipart():
        raise ValueError("not multipart")
    fields, files = {}, {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if isinstance(name, tuple):
            name = collapse_rfc2231_value(name)
        if not name:
            continue
        name = _fix_name(str(name))
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename is not None:
            files[name] = (_fix_name(str(filename)), payload)
        else:
            fields[name] = payload.decode("utf-8", "replace")
    return fields, files


class App:
    def __init__(self, store: S.Store, token: Optional[str] = None):
        self.store = store
        if not token:
            # kept in the database, so forms in tabs left open still work after the app restarts
            token = store.get_setting("csrf_token")
            if not token or len(token) < 24:
                token = secrets.token_urlsafe(24)
                store.set_setting("csrf_token", token)
        self.token = token
        self.allowed_hosts: set = set()
        self.max_upload = S.MAX_UPLOAD
        self.port = 0

    def set_port(self, port: int) -> None:
        self.port = port
        self.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = i18n.APP_NAME.replace(" ", "")
        sys_version = ""
        nonce = ""
        lang = i18n.DEFAULT_LANG

        def log_message(self, fmt, *args):  # quiet; errors are reported separately
            pass

        # ---- text helpers ----------------------------------------------------
        def T(self, key, **kw):
            return i18n.t(self.lang, key, **kw)

        def E(self, key, **kw):
            return esc(i18n.t(self.lang, key, **kw))

        def TN(self, key, n, **kw):
            return i18n.tn(self.lang, key, n, **kw)

        def H(self, key, **html_params):
            """A translated sentence with already-escaped HTML inserted in the placeholders."""
            html_params.setdefault("app", esc(i18n.APP_NAME))
            return esc(i18n.raw(self.lang, key)).format(**html_params)

        def D(self, value):
            return esc(i18n.fmt_date(value, self.lang))

        def err(self, e) -> str:
            return e.text(self.lang)

        # ---- entry -----------------------------------------------------------
        def do_GET(self):
            self.dispatch("GET")

        def do_POST(self):
            self.dispatch("POST")

        def dispatch(self, method: str):
            self.nonce = secrets.token_urlsafe(12)
            self._labels = None
            try:
                self.lang = app.store.get_lang()
            except Exception:  # noqa: BLE001 - a broken settings read must not take the page down
                self.lang = i18n.DEFAULT_LANG
            try:
                if (self.headers.get("Host") or "").lower() not in app.allowed_hosts:
                    raise HttpError(403, "http.bad_host")
                if method == "POST":
                    self.check_origin()
                parsed = urllib.parse.urlsplit(self.path)
                path = urllib.parse.unquote(parsed.path)
                query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
                for verb, rx, func in self.routes():
                    if verb == method:
                        m = rx.fullmatch(path)
                        if m:
                            return func(query, *[int(g) if g.isdigit() else g for g in m.groups()])
                raise HttpError(404, "http.not_found")
            except HttpError as e:
                self.error_page(e.status, self.T(e.key, **e.params))
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:  # noqa: BLE001 - the user must not see a traceback
                traceback.print_exc(file=sys.stderr)
                try:
                    self.error_page(500, self.T("http.server_error"))
                except OSError:
                    pass

        def routes(self):
            R = re.compile
            return [
                ("GET", R(r"/"), self.get_index),
                ("GET", R(r"/new"), self.get_new),
                ("GET", R(r"/review"), self.get_review),
                ("POST", R(r"/analyze"), self.post_analyze),
                ("POST", R(r"/save"), self.post_save),
                ("GET", R(r"/doc/(\d+)"), self.get_doc),
                ("POST", R(r"/doc/(\d+)/edit"), self.post_edit),
                ("POST", R(r"/doc/(\d+)/renew"), self.post_renew),
                ("POST", R(r"/doc/(\d+)/attach"), self.post_attach),
                ("POST", R(r"/doc/(\d+)/delete"), self.post_delete),
                ("POST", R(r"/doc/(\d+)/archive"), self.post_archive),
                ("GET", R(r"/doc/(\d+)\.ics"), self.get_doc_ics),
                ("POST", R(r"/file/(\d+)/delete"), self.post_file_delete),
                ("GET", R(r"/file/(\d+)"), self.get_file),
                ("GET", R(r"/calendar\.ics"), self.get_calendar),
                ("GET", R(r"/export"), self.get_export),
                ("GET", R(r"/backup\.zip"), self.get_backup),
                ("GET", R(r"/settings"), self.get_settings),
                ("POST", R(r"/settings"), self.post_settings),
                ("POST", R(r"/settings/category"), self.post_category_add),
                ("POST", R(r"/settings/category/(u_[0-9a-f]{8})/delete"), self.post_category_delete),
                ("POST", R(r"/settings/backup"), self.post_backup_settings),
                ("POST", R(r"/settings/backup/run"), self.post_backup_run),
                ("POST", R(r"/schedule"), self.post_schedule),
                ("GET", R(r"/ping"), self.get_ping),
            ]

        def check_origin(self):
            origin = self.headers.get("Origin")
            if origin is not None:
                ok = origin in {"http://" + h for h in app.allowed_hosts}
            else:
                referer = self.headers.get("Referer")
                ok = True if not referer else urllib.parse.urlsplit(referer).netloc.lower() in app.allowed_hosts
            if not ok:
                raise HttpError(403, "http.cross_site")

        def read_body(self, limit: int) -> bytes:
            if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
                raise HttpError(411, "http.unsupported")
            try:
                n = int(self.headers.get("Content-Length", ""))
            except ValueError:
                raise HttpError(411, "http.no_length")
            if n < 0:
                raise HttpError(400, "http.bad_request")
            if n > limit:
                left = min(n, 200 * 1024 * 1024)   # read and discard, so the browser can see our answer
                while left > 0:
                    chunk = self.rfile.read(min(65536, left))
                    if not chunk:
                        break
                    left -= len(chunk)
                raise HttpError(413, "http.too_big")
            return self.rfile.read(n)

        def read_form(self):
            ctype = self.headers.get("Content-Type", "")
            if ctype.lower().startswith("multipart/form-data"):
                body = self.read_body(app.max_upload + 1_000_000)
                try:
                    fields, files = parse_multipart(ctype, body)
                except (ValueError, KeyError):
                    raise HttpError(400, "http.form_unreadable")
            else:
                body = self.read_body(1_000_000)
                parsed = urllib.parse.parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)
                fields, files = {k: v[0] for k, v in parsed.items()}, {}
            if not hmac.compare_digest(fields.get("csrf", "").encode("utf-8"), app.token.encode("utf-8")):
                raise HttpError(403, "http.stale")
            return fields, files

        # ---- output ----------------------------------------------------------
        def send_bytes(self, status, body: bytes, ctype: str, headers: Optional[dict] = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            # "same-origin": our own forms then send a proper Origin header. With "no-referrer" the
            # browser sends "Origin: null" and the cross-site protection would reject legitimate posts.
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def redirect(self, location: str):
            self.send_response(303)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def page(self, title: str, body: str, active: str = "", status: int = 200):
            nav = "".join(f'<a href="{href}"{" aria-current=page" if href == active else ""}>{self.E(key)}</a>'
                          for href, key in NAV)
            doc = f"""<!doctype html>
<html lang="{esc(self.lang)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><title>{esc(title)} – {esc(i18n.APP_NAME)}</title>
<link rel="icon" href="{FAVICON}"><style>{CSS}</style></head><body>
<header class="top"><div class="wrap"><a class="brand" href="/">{LOGO} {esc(i18n.APP_NAME)}</a><nav>{nav}</nav></div></header>
<main><div class="wrap">{body}</div></main>
<footer><div class="wrap foot">{self.E("footer", path=str(app.store.dir))}
<br><a href="{esc(i18n.APP_URL)}" target="_blank" rel="noopener noreferrer">{esc(i18n.APP_NAME)}</a> {self.E("footer_by")} {esc(i18n.APP_AUTHOR)}</div></footer>
<script nonce="{self.nonce}">{JS}</script></body></html>"""
            csp = ("default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-%s'; img-src 'self' data:; "
                   "form-action 'self'; base-uri 'none'; frame-ancestors 'none'" % self.nonce)
            self.send_bytes(status, doc.encode("utf-8"), "text/html; charset=utf-8",
                            {"Content-Security-Policy": csp, "X-Frame-Options": "DENY"})

        def error_page(self, status: int, message: str):
            title = self.T("http.title." + str(status)) if status in (403, 404, 413) else self.T("http.title.default")
            self.page(title, f'<h1>{esc(title)}</h1><div class="alert err">{esc(message)}</div>'
                             f'<p><a class="btn secondary" href="/">{self.E("http.back")}</a></p>', status=status)

        def csrf(self) -> str:
            return f'<input type="hidden" name="csrf" value="{esc(app.token)}">'

        def flash(self, query: dict) -> str:
            key = query.get("msg", "")
            return f'<div class="alert ok" role="status">{self.E("flash." + key)}</div>' if key in FLASH else ""

        def labels(self) -> dict:
            if getattr(self, "_labels", None) is None:
                self._labels = app.store.category_labels(self.lang)
            return self._labels

        def cat_label(self, key: str) -> str:
            labels = self.labels()
            return labels.get(key) or labels["other"]

        def cat_options(self, selected: str) -> str:
            return "".join(f'<option value="{esc(k)}"{" selected" if k == selected else ""}>'
                           f'{esc(label)}</option>' for k, label in self.labels().items())

        def recur_label(self, months: int) -> str:
            if not months:
                return self.T("recur.none")
            if months % 12 == 0:
                return self.TN("recur.years", months // 12)
            return self.TN("recur.months", months)

        def tag_chips(self, tags: str, current: str = "") -> str:
            out = []
            for t in [t for t in (tags or "").split(",") if t]:
                cur = ' aria-current="true"' if t.casefold() == current.casefold() else ""
                out.append(f'<a class="chip" href="/?t={esc(urllib.parse.quote(t))}"{cur}>#{esc(t)}</a>')
            return "".join(out)

        def badge(self, st: dict) -> str:
            return f'<span class="badge {st["key"]}">{SYMBOL[st["key"]]} {esc(i18n.status_label(self.lang, st))}</span>'

        # ---- overview ----------------------------------------------------------
        def get_index(self, query):
            today = dt.date.today()
            q, cat, flt = query.get("q", "").strip(), query.get("c", ""), query.get("s", "")
            tag, archive = query.get("t", "").strip(), query.get("a") == "1"
            if flt not in ("expired", "soon", "ok", "none"):
                flt = ""
            keys = [S.classify(r["expires"], S.parse_remind_days(r["remind_days"]), today)["key"]
                    for r in app.store.list_documents()]
            counts = {k: keys.count(k) for k in ("expired", "soon", "ok", "none")}
            n_archived = app.store.count_archived()
            rows = []
            for r in app.store.list_documents(q, cat, tag, archived=archive):
                st = S.classify(r["expires"], S.parse_remind_days(r["remind_days"]), today)
                if flt and st["key"] != flt:
                    continue
                rows.append((r, st))

            def tile(key):
                cur = ' aria-current="true"' if flt == key else ""
                href = "/" if flt == key else f"/?s={key}"
                return (f'<a class="tile {key}" href="{href}"{cur}><span class="n">{counts[key]}</span>'
                        f'<span class="l">{self.E("tile." + key)}</span></a>')

            tiles = '<div class="tiles">' + tile("expired") + tile("soon") + tile("ok") + "</div>"
            hidden_flt = f'<input type="hidden" name="s" value="{esc(flt)}">' if flt else ""
            if tag:
                hidden_flt += f'<input type="hidden" name="t" value="{esc(tag)}">'
            if archive:
                hidden_flt += '<input type="hidden" name="a" value="1">'
            tags = app.store.all_tags()
            chips = ""
            if tags and not archive:
                chips = '<div class="chips" aria-label="' + self.E("ov.tags_label") + '">' + "".join(
                    f'<a class="chip" href="{"/" if t.casefold() == tag.casefold() else "/?t=" + esc(urllib.parse.quote(t))}"'
                    f'{" aria-current=true" if t.casefold() == tag.casefold() else ""}>#{esc(t)}<span class="c">{n}</span></a>'
                    for t, n in tags) + "</div>"
            if tag and not any(t.casefold() == tag.casefold() for t, _ in tags):
                chips += (f'<div class="chips"><a class="chip" href="/" aria-current="true">#{esc(tag)} ✕</a></div>')
            search = (f'<form class="search" method="get" action="/" role="search">'
                      f'<input type="search" name="q" value="{esc(q)}" placeholder="{self.E("ov.search_ph")}" '
                      f'aria-label="{self.E("ov.search_label")}">'
                      f'<select name="c" id="cat-filter" aria-label="{self.E("ov.cat_label")}">'
                      f'<option value="">{self.E("ov.all_categories")}</option>{self.cat_options(cat)}</select>'
                      f'{hidden_flt}<button class="btn secondary" type="submit">{self.E("ov.search_btn")}</button></form>')
            if not rows:
                if archive:
                    inner = f'<div class="card"><p>{self.E("ov.archive_empty")}</p></div>'
                elif not any(counts.values()) and not n_archived:
                    inner = (f'<div class="card"><h2>{self.E("ov.empty_title")}</h2><p>{self.E("ov.empty_text")}</p>'
                             f'<a class="btn" href="/new">{self.E("ov.empty_btn")}</a></div>')
                else:
                    inner = f'<div class="card"><p>{self.E("ov.no_match")}</p></div>'
            else:
                items = []
                for r, st in rows:
                    meta = self.cat_label(r["category"])
                    if r["recur_months"]:
                        meta += " · ↻ " + self.recur_label(r["recur_months"])
                    if r["n_files"]:
                        meta += " · " + self.TN("files.count", r["n_files"])
                    if r["tags"]:
                        meta += " · " + " ".join("#" + t for t in r["tags"].split(",") if t)
                    if r["expires"]:
                        when = (f'<span class="date">{self.D(r["expires"])}</span>'
                                f'<span class="rel">{esc(i18n.days_phrase(self.lang, st["days"]))}</span>')
                    else:
                        when = f'<span class="rel">{self.E("ov.no_date")}</span>'
                    items.append(f'<a class="doc {st["key"]}" href="/doc/{r["id"]}"><span class="doc-main">'
                                 f'<span class="doc-title">{esc(r["title"])}</span><span class="doc-meta">{esc(meta)}</span></span>'
                                 f'<span class="doc-when">{when}</span>{self.badge(st)}</a>')
                inner = '<div class="docs">' + "".join(items) + "</div>"
            if archive:
                head = (f'<p><a href="/">{self.E("ov.archive_back")}</a></p>'
                        f'<h1>{self.E("ov.archive_title")}</h1><p class="muted">{self.E("arch.help")}</p>')
                self.page(self.T("ov.archive_title"), self.flash(query) + head + search + inner, "/")
                return
            head = (f'<div class="actions" style="justify-content:space-between;margin-bottom:12px">'
                    f'<h1 style="margin:0">{self.E("ov.title")}</h1>'
                    f'<a class="btn" href="/new">{self.E("ov.add")}</a></div>')
            more = (f'<p class="more"><a href="/?a=1">{esc(self.TN("ov.archive_link", n_archived))}</a></p>'
                    if n_archived else "")
            self.page(self.T("ov.title"), self.flash(query) + head + tiles + search + chips + inner + more, "/")

        # ---- add a document ----------------------------------------------------
        def get_new(self, query):
            cap = docparse.capabilities(self.lang)

            def line(ok, key, missing_key=""):
                extra = f" – {self.E(missing_key)}" if (missing_key and not ok) else ""
                return f'<li>{"✓" if ok else "✗"} {self.E(key)}{extra}</li>'

            lines = [line(True, "cap.docx"), line(cap["pdf_text"], "cap.pdf", "cap.need_pdf"),
                     line(cap["ocr_images"], "cap.ocr", "cap.need_tess"),
                     line(cap["ocr_pdf"], "cap.ocrpdf", "cap.need_tesspdf")]
            if cap["ocr_images"] and cap["missing_lang"]:
                lines.append(f'<li>! {self.E("cap.lang_missing", tess=cap["missing_lang"])}</li>')
            body = f"""<h1>{self.E("new.title")}</h1>
<form id="upload" class="card" method="post" action="/analyze" enctype="multipart/form-data" data-busy="{self.E("new.reading")}">{self.csrf()}
<label class="drop-area"><input type="file" name="file" required accept="{esc(ACCEPT)}">
<span class="drop-text"><strong>{self.E("new.drop_main")}</strong><br><span class="muted">{self.E("new.drop_sub")}</span></span></label>
<div class="actions"><button class="btn" type="submit">{self.E("new.read_btn")}</button>
<a class="btn secondary" href="/review">{self.E("new.manual")}</a></div></form>
<div class="card cap"><h2>{self.E("new.cap_title")}</h2><ul style="list-style:none;padding:0;margin:0">{"".join(lines)}</ul>
<p class="muted small" style="margin:10px 0 0">{self.E("new.cap_note")}</p></div>"""
            self.page(self.T("new.title"), body, "/new")

        def post_analyze(self, query):
            fields, files = self.read_form()
            upload = files.get("file")
            if not upload or not upload[1]:
                return self.simple_error("new.title", self.T("new.err_nofile"), "/new", 400)
            try:
                token = app.store.save_temp(upload[0], upload[1])
            except S.ValidationError as e:
                return self.simple_error("new.title", self.err(e), "/new", 400)
            path, name, _ = app.store.temp_info(token)
            result = docparse.analyze(str(path), name, lang=self.lang, date_order=app.store.get_date_order())
            app.store.set_temp_text(token, result["text"])
            values = {"title": result["title"], "category": result["category"], "expires": result["expires"] or "",
                      "remind_days": result["remind_days"], "note": "", "tmp": token, "tags": "",
                      "recur": str(DEFAULT_RECUR.get(result["category"], 0))}
            self.render_review(values, [], result, name)

        def simple_error(self, title_key, message, back, status):
            self.page(self.T(title_key), f'<h1>{self.E(title_key)}</h1><div class="alert err">{esc(message)}</div>'
                                         f'<p><a class="btn" href="{back}">{self.E("common.back")}</a></p>', back, status)

        def get_review(self, query):
            self.render_review({"title": "", "category": "other", "expires": "", "remind_days": "30,14,7,1",
                                "note": "", "tmp": "", "tags": "", "recur": "0"}, [], None, "")

        def form_fields(self, v: dict) -> str:
            defaults = json.dumps({k: m["remind"] for k, m in app.store.categories().items()})
            try:
                cur_recur = int(str(v.get("recur") or 0))
            except ValueError:
                cur_recur = 0
            choices = list(RECUR_CHOICES) + ([cur_recur] if cur_recur not in RECUR_CHOICES else [])
            recur_opts = "".join(f'<option value="{m}"{" selected" if m == cur_recur else ""}>'
                                 f'{esc(self.recur_label(m))}</option>' for m in sorted(choices))
            return f"""<div class="field"><label for="title">{self.E("form.title")}</label>
<input type="text" id="title" name="title" value="{esc(v['title'])}" maxlength="200" required></div>
<div class="grid2"><div class="field"><label for="category">{self.E("form.category")}</label>
<select id="category" name="category" data-defaults="{esc(defaults)}">{self.cat_options(v['category'])}</select></div>
<div class="field"><label for="expires">{self.E("form.expires")} <span class="hint">{self.E("form.expires_hint")}</span></label>
<input type="date" id="expires" name="expires" value="{esc(v['expires'])}"></div></div>
<div class="field"><label for="remind_days">{self.E("form.remind")} <span class="hint">{self.E("form.remind_hint")}</span></label>
<input type="text" id="remind_days" name="remind_days" value="{esc(v['remind_days'])}" inputmode="numeric"></div>
<div class="grid2"><div class="field"><label for="recur">{self.E("form.recur")} <span class="hint">{self.E("form.recur_hint")}</span></label>
<select id="recur" name="recur">{recur_opts}</select></div>
<div class="field"><label for="tags">{self.E("form.tags")} <span class="hint">{self.E("form.tags_hint")}</span></label>
<input type="text" id="tags" name="tags" value="{esc(v.get('tags', '').replace(',', ', '))}" maxlength="500"></div></div>
<div class="field"><label for="note">{self.E("form.note")}</label><textarea id="note" name="note" maxlength="5000">{esc(v['note'])}</textarea></div>"""

        def render_review(self, values, errors, analysis, filename):
            parts = [f'<h1>{self.E("review.title")}</h1>']
            if errors:
                parts.append(f'<div class="alert err" role="alert"><strong>{self.E("review.fix")}</strong><ul>'
                             + "".join(f"<li>{esc(e)}</li>" for e in errors) + "</ul></div>")
            if filename:
                parts.append(f'<p class="muted">{self.H("review.file", name="<strong>" + esc(filename) + "</strong>")}</p>')
            if analysis is not None:
                conf = analysis["confidence"]
                if analysis["expires"]:
                    summary = self.H("review.found", date="<strong>" + self.D(analysis["expires"]) + "</strong>",
                                     conf=esc(i18n.conf_label(self.lang, conf)),
                                     reason=esc(i18n.reason_text(self.lang, analysis["reason"])))
                else:
                    summary = self.E("review.none")
                kind = "warn" if conf in ("low", "none") else "info"
                block = [f'<div class="alert {kind}"><p style="margin:0 0 6px">{summary}</p>']
                if conf in ("low", "medium"):
                    block.append(f'<p style="margin:0 0 6px"><strong>{self.E("review.check_date")}</strong></p>')
                for note in analysis["notes"]:
                    block.append(f'<p style="margin:0 0 6px">{esc(i18n.note_text(self.lang, note))}</p>')
                others = [c for c in analysis["candidates"] if c["date"] != analysis["expires"]][:5]
                if others:
                    buttons = []
                    for c in others:
                        label = i18n.fmt_date(c["date"], self.lang)
                        if c["kind"] == "month":
                            label += " " + self.T("cand.month_end")
                        buttons.append(f'<button type="button" class="btn small secondary" data-date="{esc(c["date"])}">'
                                       f'{esc(label)}</button>')
                    block.append(f'<p style="margin:8px 0 6px">{self.E("review.others")}</p>'
                                 f'<div class="actions">{"".join(buttons)}</div>')
                block.append("</div>")
                parts.append("".join(block))
            parts.append(f'<form class="card" method="post" action="/save">{self.csrf()}'
                         f'<input type="hidden" name="tmp" value="{esc(values["tmp"])}">'
                         f'{self.form_fields(values)}<div class="actions"><button class="btn" type="submit">{self.E("form.save")}</button>'
                         f'<a class="btn secondary" href="/">{self.E("common.cancel")}</a></div></form>')
            if analysis is not None and analysis["text"].strip():
                parts.append(f'<details class="card"><summary>{self.E("review.text_summary")}</summary>'
                             f'<pre class="text">{esc(analysis["text"][:6000])}</pre></details>')
            self.page(self.T("review.title"), "".join(parts), "/new", 400 if errors else 200)

        def post_save(self, query):
            fields, _ = self.read_form()
            values = {k: fields.get(k, "") for k in ("title", "category", "expires", "remind_days", "note", "tmp",
                                                     "tags", "recur")}
            tmp = values["tmp"]
            info = app.store.temp_info(tmp) if tmp else None
            if tmp and info is None:
                return self.render_review(values, [self.T("err.upload_gone")], None, "")
            try:
                app.store.validate(values["title"], values["category"], values["expires"],
                                   values["remind_days"], values["note"], values["tags"], values["recur"])
            except S.ValidationError as e:
                return self.render_review(values, [self.err(e)], None, info[1] if info else "")
            doc_id = app.store.add_document(values["title"], values["category"], values["expires"],
                                            values["remind_days"], values["note"], info[2] if info else "",
                                            values["tags"], values["recur"], upload_token=tmp)
            self.redirect(f"/doc/{doc_id}?msg=created")

        # ---- detail ----------------------------------------------------------------
        def need_doc(self, doc_id):
            doc = app.store.get_document(doc_id)
            if doc is None:
                raise HttpError(404, "http.no_doc")
            return doc

        def get_doc(self, query, doc_id, values=None, errors=None):
            doc = self.need_doc(doc_id)
            today = dt.date.today()
            st = S.classify(doc["expires"], S.parse_remind_days(doc["remind_days"]), today)
            v = values or {"title": doc["title"], "category": doc["category"], "expires": doc["expires"] or "",
                           "remind_days": doc["remind_days"], "note": doc["note"], "tags": doc["tags"],
                           "recur": str(doc["recur_months"])}
            if doc["expires"]:
                when = f'{self.D(doc["expires"])} · {esc(i18n.days_phrase(self.lang, st["days"]))}'
            else:
                when = self.E("detail.no_end")
            if doc["recur_months"]:
                when += " · ↻ " + esc(self.recur_label(doc["recur_months"]))
            archived = bool(doc["archived"])
            err = ""
            if errors:
                err = ('<div class="alert err" role="alert"><ul style="margin:0;padding-left:20px">'
                       + "".join(f"<li>{esc(e)}</li>" for e in errors) + "</ul></div>")
            back = "/?a=1" if archived else "/"
            chips = self.tag_chips(doc["tags"])
            head = (f'<p><a href="{back}">{self.E("common.back")}</a></p><div class="actions" style="margin-bottom:6px">{self.badge(st)}</div>'
                    f'<h1 style="margin-bottom:4px">{esc(doc["title"])}</h1><p class="muted">{when}</p>'
                    + (f'<div class="chips">{chips}</div>' if chips else "")
                    + (f'<div class="alert info">{self.E("arch.banner")}</div>' if archived else ""))
            edit = (f'<form class="card" method="post" action="/doc/{doc_id}/edit">{self.csrf()}<h2>{self.E("detail.data")}</h2>'
                    f'{self.form_fields(v)}<div class="actions"><button class="btn" type="submit">{self.E("form.save_changes")}</button>'
                    f'<a class="btn secondary" href="/doc/{doc_id}.ics">{self.E("detail.ics")}</a></div></form>')
            if doc["body"].strip():
                edit += (f'<details class="card"><summary>{self.E("detail.text")}</summary>'
                         f'<pre class="text">{esc(doc["body"][:6000])}</pre></details>')

            recur_btn = (f'<button class="btn small" name="mode" value="recur">'
                         f'{self.E("renew.recur", every=self.recur_label(doc["recur_months"]))}</button>'
                         if doc["recur_months"] else "")
            renew = (f'<form class="card" method="post" action="/doc/{doc_id}/renew">{self.csrf()}<h2>{self.E("renew.title")}</h2>'
                     f'<p class="muted small">{self.E("renew.help")}</p><div class="actions" style="margin-bottom:12px">'
                     f'{recur_btn}'
                     f'<button class="btn small secondary" name="mode" value="y1">{self.E("renew.y1")}</button>'
                     f'<button class="btn small secondary" name="mode" value="y2">{self.E("renew.y2")}</button></div>'
                     f'<div class="field"><label for="rdate">{self.E("renew.exact")}</label>'
                     f'<input type="date" id="rdate" name="date"></div>'
                     f'<button class="btn small" name="mode" value="date">{self.E("renew.set")}</button></form>')

            items = []
            for att in app.store.list_attachments(doc_id):
                size = (f"{att['size']} B" if att["size"] < 1024 else f"{att['size'] / 1024:.0f} kB"
                        if att["size"] < 1024 * 1024 else f"{att['size'] / 1048576:.1f} MB")
                thumb = (f'<a href="/file/{att["id"]}" target="_blank" rel="noopener"><img class="thumb" '
                         f'src="/file/{att["id"]}" alt="{self.E("files.preview", name=att["filename"])}" loading="lazy"></a>'
                         if att["mime"] in ("image/jpeg", "image/png", "image/gif", "image/webp") else "")
                open_btn = (f'<a class="btn small secondary" href="/file/{att["id"]}" target="_blank" rel="noopener">{self.E("files.open")}</a>'
                            if att["mime"] in S.INLINE_TYPES else "")
                items.append(
                    f'<li><div class="fname">{esc(att["filename"])}</div><div class="muted small">{size}</div>{thumb}'
                    f'<div class="actions">{open_btn}<a class="btn small secondary" href="/file/{att["id"]}?dl=1">{self.E("files.download")}</a>'
                    f'<form method="post" action="/file/{att["id"]}/delete" data-confirm="{self.E("files.confirm")}">{self.csrf()}'
                    f'<button class="btn small danger" type="submit">{self.E("files.delete")}</button></form></div></li>')
            listing = f'<ul class="files">{"".join(items)}</ul>' if items else f'<p class="muted">{self.E("files.none")}</p>'
            files = (f'<div class="card"><h2>{self.E("files.title")}</h2>{listing}'
                     f'<form method="post" action="/doc/{doc_id}/attach" enctype="multipart/form-data">{self.csrf()}'
                     f'<div class="field"><label for="afile">{self.E("files.add")}</label>'
                     f'<input type="file" id="afile" name="file" required accept="{esc(ACCEPT)}"></div>'
                     f'<button class="btn small secondary" type="submit">{self.E("files.upload")}</button></form></div>')
            arch = (f'<form class="card" method="post" action="/doc/{doc_id}/archive">{self.csrf()}'
                    f'<h2>{self.E("arch.title")}</h2><p class="muted small">{self.E("arch.help")}</p>'
                    f'<input type="hidden" name="archived" value="{"0" if archived else "1"}">'
                    f'<button class="btn small secondary" type="submit">'
                    f'{self.E("arch.restore_btn" if archived else "arch.btn")}</button></form>')
            danger = (f'<form class="card" method="post" action="/doc/{doc_id}/delete" '
                      f'data-confirm="{self.E("del.confirm")}">{self.csrf()}'
                      f'<h2>{self.E("del.title")}</h2><p class="muted small">{self.E("del.help")}</p>'
                      f'<button class="btn danger" type="submit">{self.E("del.btn")}</button></form>')
            body = self.flash(query) + head + err + f'<div class="layout"><div>{edit}</div><div>{renew}{files}{arch}{danger}</div></div>'
            self.page(doc["title"], body, "/", 400 if errors else 200)

        def post_edit(self, query, doc_id):
            fields, _ = self.read_form()
            self.need_doc(doc_id)
            values = {k: fields.get(k, "") for k in ("title", "category", "expires", "remind_days", "note",
                                                     "tags", "recur")}
            try:
                app.store.update_document(doc_id, values["title"], values["category"], values["expires"],
                                          values["remind_days"], values["note"],
                                          values["tags"] if "tags" in fields else None,
                                          values["recur"] if "recur" in fields else None)
            except S.ValidationError as e:
                return self.get_doc({}, doc_id, values, [self.err(e)])
            self.redirect(f"/doc/{doc_id}?msg=saved")

        def post_renew(self, query, doc_id):
            fields, _ = self.read_form()
            doc = self.need_doc(doc_id)
            mode, today = fields.get("mode", ""), dt.date.today()
            try:
                if mode in ("y1", "y2"):
                    years = 1 if mode == "y1" else 2
                    base = dt.date.fromisoformat(doc["expires"]) if doc["expires"] else today
                    new = docparse.add_months(base, 12 * years)
                    if new < today:                       # long expired: count from today
                        new = docparse.add_months(today, 12 * years)
                    app.store.set_expiry(doc_id, new.isoformat())
                elif mode == "date":
                    app.store.set_expiry(doc_id, fields.get("date", ""))
                elif mode == "recur":
                    app.store.renew_by_interval(doc_id, today)
                else:
                    raise HttpError(400, "http.bad_action")
            except S.ValidationError as e:
                return self.get_doc({}, doc_id, None, [self.err(e)])
            self.redirect(f"/doc/{doc_id}?msg=renewed")

        def post_attach(self, query, doc_id):
            _, files = self.read_form()
            self.need_doc(doc_id)
            upload = files.get("file")
            try:
                if not upload or not upload[1]:
                    raise S.ValidationError("new.err_nofile")
                app.store.add_attachment(doc_id, upload[0], upload[1])
            except S.ValidationError as e:
                return self.get_doc({}, doc_id, None, [self.err(e)])
            self.redirect(f"/doc/{doc_id}?msg=uploaded")

        def post_archive(self, query, doc_id):
            fields, _ = self.read_form()
            self.need_doc(doc_id)
            on = fields.get("archived") == "1"
            app.store.set_archived(doc_id, on)
            self.redirect(f"/doc/{doc_id}?msg={'archived' if on else 'unarchived'}")

        def post_delete(self, query, doc_id):
            self.read_form()
            self.need_doc(doc_id)
            app.store.delete_document(doc_id)
            self.redirect("/?msg=deleted")

        def post_file_delete(self, query, att_id):
            self.read_form()
            if app.store.get_attachment(att_id) is None:
                raise HttpError(404, "http.no_file")
            doc_id = app.store.delete_attachment(att_id)
            self.redirect(f"/doc/{doc_id}?msg=filedeleted")

        # ---- files, calendar, backup ---------------------------------------------------
        def get_file(self, query, att_id):
            att = app.store.get_attachment(att_id)
            if att is None:
                raise HttpError(404, "http.no_file")
            path = app.store.attachment_path(att)
            if not path.exists():
                raise HttpError(404, "http.file_missing")
            inline = att["mime"] in S.INLINE_TYPES and query.get("dl") != "1"
            name = att["filename"]
            ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", name) or "file"
            disp = (f'{"inline" if inline else "attachment"}; filename="{ascii_name}"; '
                    f"filename*=UTF-8''{urllib.parse.quote(name)}")
            headers = {"Content-Disposition": disp, "X-Frame-Options": "DENY"}
            if inline and att["mime"].startswith("image/"):
                headers["Content-Security-Policy"] = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"
            self.send_response(200)
            self.send_header("Content-Type", att["mime"] if inline else "application/octet-stream")
            self.send_header("Content-Length", str(path.stat().st_size))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            with open(path, "rb") as fh:
                shutil.copyfileobj(fh, self.wfile)

        def send_ics(self, docs, filename):
            data = S.build_ics(docs, lang=self.lang, labels=self.labels()).encode("utf-8")
            self.send_bytes(200, data, "text/calendar; charset=utf-8",
                            {"Content-Disposition": f'attachment; filename="{filename}"'})

        def get_calendar(self, query):
            self.send_ics(app.store.list_documents(), f"{i18n.APP_SLUG}.ics")

        def get_doc_ics(self, query, doc_id):
            self.send_ics([self.need_doc(doc_id)], f"deadline-{doc_id}.ics")

        def get_backup(self, query):
            fd, tmp = tempfile.mkstemp(suffix=".zip", dir=app.store.tmp)
            os.close(fd)
            try:
                app.store.backup_to(tmp)
                size = os.path.getsize(tmp)
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Length", str(size))
                self.send_header("Content-Disposition",
                                 f'attachment; filename="{i18n.APP_SLUG}-backup-{dt.date.today().isoformat()}.zip"')
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                with open(tmp, "rb") as fh:
                    shutil.copyfileobj(fh, self.wfile)
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

        def get_export(self, query):
            body = f"""{self.flash(query)}<h1>{self.E("export.title")}</h1>
<div class="card"><h2>{self.E("export.cal_title")}</h2>
<p>{self.E("export.cal_text")}</p>
<p class="muted small">{self.E("export.cal_note")}</p>
<a class="btn" href="/calendar.ics">{self.E("export.cal_btn")}</a></div>
{self.schedule_card()}
<div class="card"><h2>{self.E("export.bk_title")}</h2>
<p>{self.E("export.bk_text")}</p>
<pre class="cmd">{esc(scheduler.cli_prefix(app.store.dir))} restore backup.zip --yes</pre>
<a class="btn secondary" href="/backup.zip">{self.E("export.bk_btn")}</a></div>"""
            self.page(self.T("export.title"), body, "/export")

        def schedule_card(self) -> str:
            parts = [f'<div class="card"><h2>{self.E("export.desk_title")}</h2><p>{self.E("export.desk_text")}</p>']
            kind = scheduler.kind()
            if kind:
                on = scheduler.status(app.store.dir)
                if on:
                    parts.append(f'<div class="alert ok">✓ {self.E("sched.on")} {self.E("sched.how." + kind)}</div>')
                else:
                    parts.append(f'<p class="muted">{self.E("sched.off")} {self.E("sched.how." + kind)}</p>')
                action = "off" if on else "on"
                parts.append(f'<form method="post" action="/schedule" class="actions">{self.csrf()}'
                             f'<button class="btn{" secondary" if on else ""}" name="action" value="{action}">'
                             f'{self.E("sched.disable" if on else "sched.enable")}</button>'
                             f'<button class="btn secondary" name="action" value="test">{self.E("sched.test")}</button>'
                             f'</form>')
            else:
                parts.append(f'<p class="muted">{self.E("sched.unsupported")}</p>')
            parts.append(f'<details style="margin-top:12px"><summary>{self.E("sched.manual")}</summary>'
                         f'<pre class="cmd">{esc(scheduler.command_line(app.store.dir))}</pre></details></div>')
            return "".join(parts)

        def post_schedule(self, query):
            fields, _ = self.read_form()
            action = fields.get("action", "")
            try:
                if action == "on":
                    scheduler.install(app.store.dir)
                    msg = "sched_on"
                elif action == "off":
                    scheduler.remove()
                    msg = "sched_off"
                elif action == "test":
                    if not scheduler.desktop_notify(i18n.APP_NAME, self.T("cli.test_text")):
                        raise scheduler.ScheduleError(self.T("cli.test_fail"))
                    msg = "test_sent"
                else:
                    raise HttpError(400, "http.bad_action")
            except scheduler.ScheduleError as e:
                return self.simple_error("export.title", self.T("err.sched_failed", msg=str(e)), "/export", 500)
            self.redirect(f"/export?msg={msg}")

        def get_ping(self, query):
            """Lets a second start of the program find this one (and its data folder) instead of starting twice."""
            body = json.dumps({"app": i18n.APP_NAME, "data": str(app.store.dir)}).encode("utf-8")
            self.send_bytes(200, body, "application/json")

        # ---- settings ----------------------------------------------------------------------
        def get_settings(self, query, errors=None, ab_values=None, cat_values=None):
            order = app.store.get_date_order()
            langs = "".join(f'<option value="{esc(code)}"{" selected" if code == self.lang else ""}>{esc(name)}</option>'
                            for code, name in i18n.LANGS.items())
            radios = "".join(
                f'<label class="radio"><input type="radio" name="date_order" value="{o}"{" checked" if o == order else ""}>'
                f'<span>{self.E("set." + o)}</span></label>' for o in i18n.DATE_ORDERS)
            body = (f'{self.flash(query)}<h1>{self.E("set.title")}</h1>'
                    f'<form class="card" method="post" action="/settings">{self.csrf()}'
                    f'<div class="field"><label for="lang">{self.E("set.lang")}</label>'
                    f'<select id="lang" name="lang">{langs}</select></div>'
                    f'<fieldset><legend>{self.E("set.date_order")}</legend>{radios}'
                    f'<p class="muted small">{self.E("set.date_help")}</p></fieldset>'
                    f'<button class="btn" type="submit">{self.E("set.save")}</button></form>')
            err = ""
            if errors:
                err = ('<div class="alert err" role="alert"><ul style="margin:0;padding-left:20px">'
                       + "".join(f"<li>{esc(e)}</li>" for e in errors) + "</ul></div>")
            body = err + body + self.categories_card(cat_values or {}) + self.backup_card(ab_values)
            self.page(self.T("set.title"), body, "/settings", 400 if errors else 200)

        def categories_card(self, v: dict) -> str:
            rows = []
            for c in app.store.custom_categories():
                used = esc(self.TN("set.cat_used", c["n_docs"])) if c["n_docs"] else ""
                rows.append(f'<tr><td><strong>{esc(c["label"])}</strong><br><span class="muted small">'
                            f'{self.E("form.remind")}: {esc(c["remind"].replace(",", ", "))}'
                            f'{" · " + used if used else ""}</span></td>'
                            f'<td class="r"><form method="post" action="/settings/category/{esc(c["id"])}/delete" '
                            f'data-confirm="{self.E("set.cat_confirm")}">{self.csrf()}'
                            f'<button class="btn small danger" type="submit">{self.E("set.cat_delete")}</button>'
                            f'</form></td></tr>')
            listing = (f'<table class="list">{"".join(rows)}</table>' if rows
                       else f'<p class="muted">{self.E("set.cat_none")}</p>')
            return (f'<div class="card"><h2>{self.E("set.cat_title")}</h2><p class="muted small">{self.E("set.cat_help")}</p>'
                    f'{listing}<form method="post" action="/settings/category" style="margin-top:14px">{self.csrf()}'
                    f'<div class="grid2"><div class="field"><label for="cat_label">{self.E("set.cat_label")}</label>'
                    f'<input type="text" id="cat_label" name="label" maxlength="60" required value="{esc(v.get("label", ""))}"></div>'
                    f'<div class="field"><label for="cat_remind">{self.E("set.cat_remind")}</label>'
                    f'<input type="text" id="cat_remind" name="remind" inputmode="numeric" '
                    f'value="{esc(v.get("remind", "30,14,7,1"))}"></div></div>'
                    f'<button class="btn secondary" type="submit">{self.E("set.cat_add")}</button></form></div>')

        def backup_card(self, v=None) -> str:
            cfg = app.store.auto_backup_config()
            v = v or {"dir": cfg["dir"], "days": str(cfg["days"]), "keep": str(cfg["keep"])}
            if not cfg["dir"]:
                state = f'<p class="muted">{self.E("set.ab_off")}</p>'
            elif cfg["last"]:
                state = f'<p class="muted">{self.E("set.ab_last", when=cfg["last"][:16])}</p>'
            else:
                state = f'<p class="muted">{self.E("set.ab_never")}</p>'
            if cfg["error"]:
                state += f'<div class="alert err">{self.E("set.ab_error", msg=cfg["error"])}</div>'
            hint = scheduler.suggested_backup_dir()
            tip = f'<br>{self.E("set.ab_suggest", path=hint)}' if hint else ""
            run = (f'<form method="post" action="/settings/backup/run" style="margin-top:10px">{self.csrf()}'
                   f'<button class="btn secondary" type="submit">{self.E("set.ab_now")}</button></form>'
                   if cfg["dir"] else "")
            return (f'<div class="card"><h2>{self.E("set.ab_title")}</h2><p class="muted small">{self.E("set.ab_help")}{tip}</p>'
                    f'{state}<form method="post" action="/settings/backup">{self.csrf()}'
                    f'<div class="field"><label for="ab_dir">{self.E("set.ab_dir")} <span class="hint">{self.E("set.ab_dir_hint")}</span></label>'
                    f'<input type="text" id="ab_dir" name="dir" value="{esc(v["dir"])}" placeholder="{esc(hint)}"></div>'
                    f'<div class="grid2"><div class="field"><label for="ab_days">{self.E("set.ab_days")}</label>'
                    f'<input type="text" id="ab_days" name="days" inputmode="numeric" value="{esc(v["days"])}"></div>'
                    f'<div class="field"><label for="ab_keep">{self.E("set.ab_keep")}</label>'
                    f'<input type="text" id="ab_keep" name="keep" inputmode="numeric" value="{esc(v["keep"])}"></div></div>'
                    f'<button class="btn" type="submit">{self.E("set.ab_save")}</button></form>{run}</div>')

        def post_category_add(self, query):
            fields, _ = self.read_form()
            try:
                app.store.add_category(fields.get("label", ""), fields.get("remind", ""))
            except S.ValidationError as e:
                return self.get_settings({}, [self.err(e)], cat_values=fields)
            self.redirect("/settings?msg=cat_added")

        def post_category_delete(self, query, cat_id):
            self.read_form()
            try:
                app.store.delete_category(cat_id)
            except KeyError:
                raise HttpError(404, "http.not_found")
            self.redirect("/settings?msg=cat_deleted")

        def post_backup_settings(self, query):
            fields, _ = self.read_form()
            v = {k: fields.get(k, "") for k in ("dir", "days", "keep")}
            try:
                app.store.set_auto_backup(v["dir"], v["days"], v["keep"])
            except S.ValidationError as e:
                return self.get_settings({}, [self.err(e)], ab_values=v)
            self.redirect("/settings?msg=ab_saved")

        def post_backup_run(self, query):
            self.read_form()
            try:
                done = app.store.run_auto_backup(force=True)
            except OSError as e:
                return self.get_settings({}, [self.T("err.ab_failed", msg=str(e))])
            self.redirect("/settings?msg=" + ("ab_done" if done else "ab_saved"))

        def post_settings(self, query):
            fields, _ = self.read_form()
            if fields.get("lang") in i18n.LANGS:
                app.store.set_lang(fields["lang"])
            if fields.get("date_order") in i18n.DATE_ORDERS:
                app.store.set_date_order(fields["date_order"])
            self.redirect("/settings?msg=settings")

    return Handler


# --------------------------------------------------------------------------
# Starting the server
# --------------------------------------------------------------------------
DEFAULT_RECUR = {"vehicle": 24, "inspection": 12, "insurance": 12}   # suggested repeat (months) per category


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets a second program take a port that is already in use (both then "work"),
    # so there the port is claimed exclusively instead.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class AlreadyRunning(Exception):
    def __init__(self, port: int):
        super().__init__(port)
        self.port = port


def running_copy(port: int, data_dir) -> bool:
    """True when the program listening on `port` is this app working with the same data folder."""
    conn = http.client.HTTPConnection(HOST, port, timeout=2)
    try:
        conn.request("GET", "/ping", headers={"Host": f"{HOST}:{port}"})
        r = conn.getresponse()
        if r.status != 200:
            return False
        info = json.loads(r.read(4096).decode("utf-8"))
        return info.get("app") == i18n.APP_NAME and os.path.normcase(info.get("data", "")) == \
            os.path.normcase(str(data_dir))
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        conn.close()


def make_server(store: S.Store, port: int = DEFAULT_PORT, search: bool = True,
                token: Optional[str] = None, reuse_running: bool = False):
    app = App(store, token)
    last = None
    for p in (range(port, port + 20) if search and port else [port]):
        try:
            httpd = Server((HOST, p), make_handler(app))
            app.set_port(httpd.server_address[1])
            return httpd, app
        except OSError as e:
            last = e
            if reuse_running and p and running_copy(p, store.dir):
                raise AlreadyRunning(p)
    raise OSError(f"Could not open port {port}: {last}")


def _auto_backup_loop(store: S.Store, stop: threading.Event) -> None:
    if stop.wait(5):
        return
    while True:
        try:
            done = store.run_auto_backup()
            if done:
                print(i18n.t(store.get_lang(), "cli.ab_done", path=done))
        except Exception as e:  # noqa: BLE001 - the error is shown on the Settings page; keep the app running
            print(i18n.t(i18n.DEFAULT_LANG, "cli.error", msg=e), file=sys.stderr)
        if stop.wait(3600):
            return


def serve(store: S.Store, port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    lang = store.get_lang()
    try:
        httpd, app = make_server(store, port, search=port == DEFAULT_PORT, reuse_running=True)
    except AlreadyRunning as e:
        url = f"http://127.0.0.1:{e.port}/"
        print(i18n.t(lang, "srv.already", app=i18n.APP_NAME, url=url))
        if open_browser:
            webbrowser.open(url)
        return
    url = f"http://127.0.0.1:{app.port}/"
    stop = threading.Event()
    threading.Thread(target=_auto_backup_loop, args=(store, stop), daemon=True).start()
    print(i18n.t(lang, "srv.running", app=i18n.APP_NAME, url=url))
    print(i18n.t(lang, "srv.data", path=store.dir))
    print(i18n.t(lang, "srv.stop"))
    if open_browser:
        threading.Timer(0.7, webbrowser.open, [url]).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n" + i18n.t(lang, "srv.bye"))
    finally:
        stop.set()
        httpd.server_close()
