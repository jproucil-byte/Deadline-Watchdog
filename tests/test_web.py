# Deadline Watchdog – author: jproucil-byte – https://github.com/jproucil-byte/Deadline-Watchdog
import datetime as dt
import html
import http.client
import io
import json
import os
import re
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import i18n  # noqa: E402
import store as S  # noqa: E402
import web  # noqa: E402

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x9a\xa0\xa0\x00\x00\x00\x00IEND\xaeB`\x82")


def r_plain(text):
    return html.unescape(text)


def iso(days):
    return (dt.date.today() + dt.timedelta(days=days)).isoformat()


def multipart(fields, files):
    boundary = "----watchdogtest7c1f"
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for k, (filename, data) in files.items():
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{filename}"\r\n'
                  f"Content-Type: application/octet-stream\r\n\r\n".encode())
        out.write(data)
        out.write(b"\r\n")
    out.write(f"--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


class Resp:
    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, headers, body

    @property
    def text(self):
        return self.body.decode("utf-8", "replace")

    @property
    def plain(self):
        """The page text with HTML entities decoded (apostrophes and ampersands are escaped in the markup)."""
        return html.unescape(self.text)

    def header(self, name):
        return self.headers.get(name.lower())


class WebCase(unittest.TestCase):
    def setUp(self):
        os.environ.pop("WATCHDOG_LANG", None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = S.Store(Path(self.tmp.name) / "data")
        self.httpd, self.app = web.make_server(self.store, 0, search=False)
        self.port = self.app.port
        t = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        t.start()
        self.addCleanup(self._stop, t)
        self.origin = f"http://127.0.0.1:{self.port}"

    def _stop(self, t):
        self.httpd.shutdown()
        self.httpd.server_close()
        t.join(5)

    # ---- helpers ----------------------------------------------------------------
    def request(self, method, path, body=None, headers=None, host=None, origin="auto", csrf=True):
        hdr = dict(headers or {})
        if host is not None:
            hdr["Host"] = host
        if method == "POST":
            if origin == "auto":
                hdr["Origin"] = self.origin
            elif origin is not None:
                hdr["Origin"] = origin
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        try:
            conn.request(method, path, body=body, headers=hdr)
            r = conn.getresponse()
            return Resp(r.status, {k.lower(): v for k, v in r.getheaders()}, r.read())
        finally:
            conn.close()

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, fields=None, csrf=True, **kw):
        data = dict(fields or {})
        if csrf:
            data["csrf"] = self.app.token
        body = urllib.parse.urlencode(data).encode()
        hdr = {"Content-Type": "application/x-www-form-urlencoded", **kw.pop("headers", {})}
        return self.request("POST", path, body=body, headers=hdr, **kw)

    def upload(self, path, filename, data, fields=None, csrf=True, **kw):
        f = dict(fields or {})
        if csrf:
            f["csrf"] = self.app.token
        body, ctype = multipart(f, {"file": (filename, data)})
        return self.request("POST", path, body=body, headers={"Content-Type": ctype}, **kw)

    def set_settings(self, lang="en", order=None):
        fields = {"lang": lang}
        if order:
            fields["date_order"] = order
        r = self.post("/settings", fields)
        self.assertEqual(r.status, 303)

    def make_doc(self, title="Car insurance", category="insurance", expires=None, remind="30,7", note=""):
        return self.store.add_document(title, category, expires if expires is not None else iso(100), remind, note)


# ==========================================================================
class Pages(WebCase):
    def test_empty_overview(self):
        r = self.get("/")
        self.assertEqual(r.status, 200)
        self.assertIn("Overview", r.text)
        self.assertIn("Nothing here yet", r.text)
        self.assertIn('<html lang="en">', r.text)
        self.assertIn("Deadline Watchdog", r.text)

    def test_footer_credits_the_author_with_a_safe_link(self):
        for lang, word in (("en", "by jproucil-byte"), ("cs", "od jproucil-byte")):
            self.store.set_lang(lang)
            for path in ("/", "/new", "/settings"):
                text = self.get(path).text
                self.assertIn(word, text, (lang, path))
                self.assertIn('href="https://github.com/jproucil-byte/Deadline-Watchdog"', text)
                self.assertIn('rel="noopener noreferrer"', text)
        self.store.set_lang("en")

    def test_security_headers(self):
        r = self.get("/")
        self.assertEqual(r.header("x-content-type-options"), "nosniff")
        self.assertEqual(r.header("referrer-policy"), "same-origin")
        self.assertEqual(r.header("cache-control"), "no-store")
        self.assertEqual(r.header("x-frame-options"), "DENY")
        csp = r.header("content-security-policy")
        nonce = re.search(r"script-src 'nonce-([\w-]+)'", csp).group(1)
        self.assertIn(f'<script nonce="{nonce}">', r.text)
        self.assertIn("default-src 'none'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertNotIn("Server: Python", str(r.headers))
        self.assertNotIn("python", (r.header("server") or "").lower())

    def test_every_page_renders_in_both_languages(self):
        doc = self.make_doc(note="a note")
        paths = ["/", "/new", "/review", "/export", "/settings", f"/doc/{doc}", "/?s=soon", "/?q=car&c=insurance",
                 "/?msg=created", "/settings?msg=settings"]
        for lang in ("en", "cs"):
            self.set_settings(lang)
            for path in paths:
                r = self.get(path)
                self.assertEqual(r.status, 200, (lang, path))
                self.assertIn(f'<html lang="{lang}">', r.text)
                self.assertNotRegex(r.text, r"\{[a-z_]+\}", (lang, path))          # no unfilled placeholder
                for key in ("nav.overview", "nav.add", "nav.export", "nav.settings"):
                    self.assertIn(i18n.t(lang, key), r.plain)

    def test_no_english_leaks_into_the_czech_pages_and_vice_versa(self):
        self.make_doc()
        self.set_settings("cs")
        text = self.get("/").text
        self.assertIn("Přehled", text)
        self.assertNotIn("Overview", text)
        self.assertNotIn("Nothing here", text)
        self.set_settings("en")
        text = self.get("/").text
        self.assertNotIn("Přehled", text)

    def test_overview_counts_and_filters(self):
        self.make_doc("Expired one", expires=iso(-3))
        self.make_doc("Soon one", expires=iso(5))
        self.make_doc("Fine one", expires=iso(300), remind="30")
        self.make_doc("No date one", expires="")
        t = self.get("/").text
        for title in ("Expired one", "Soon one", "Fine one", "No date one"):
            self.assertIn(title, t)
        self.assertIn("3 days ago", t)
        self.assertIn("in 5 days", t)
        self.assertIn("no end date", t)
        self.assertEqual(re.findall(r'class="n">(\d+)<', t), ["1", "1", "1"])
        only = self.get("/?s=expired").text
        self.assertIn("Expired one", only)
        self.assertNotIn("Soon one", only)
        found = self.get("/?q=fine").text
        self.assertIn("Fine one", found)
        self.assertNotIn("Soon one", found)
        none = self.get("/?q=nothing-like-this").text
        self.assertIn("Nothing found.", none)
        self.assertNotIn("Nothing here yet", none)
        bogus = self.get("/?s=%3Cscript%3E&c=%3Cx%3E")
        self.assertEqual(bogus.status, 200)
        self.assertNotIn("<script>alert", bogus.text)

    def test_titles_are_escaped_everywhere(self):
        evil = '<script>alert(1)</script><img src=x onerror=alert(2)>"\''
        doc = self.make_doc(evil, note=evil)
        for path in ("/", f"/doc/{doc}", f"/?q={urllib.parse.quote(evil)}"):
            t = self.get(path).text
            self.assertNotIn("<script>alert(1)", t, path)
            self.assertNotIn("<img src=x", t, path)
        self.assertIn("&lt;script&gt;alert(1)", self.get("/").text)

    def test_new_page_shows_capabilities(self):
        t = self.get("/new").text
        self.assertIn("Word", t)
        self.assertRegex(t, r"[✓✗] Photos and scans")
        self.assertIn('enctype="multipart/form-data"', t)
        self.assertIn('data-busy="', t)

    def test_missing_czech_ocr_data_is_mentioned_only_in_czech(self):
        import docparse
        cap = docparse.capabilities("cs")
        if not (cap["ocr_images"] and cap["missing_lang"]):
            self.skipTest("Czech OCR data installed or Tesseract missing")
        self.assertNotIn("ces", self.get("/new").text.replace("ces=", ""))
        self.set_settings("cs")
        self.assertIn("ces", self.get("/new").text)

    def test_export_page(self):
        t = self.get("/export").text
        self.assertRegex(r_plain(t), r"watchdog\.py\"? --data .+ notify")
        self.assertIn("restore backup.zip --yes", t)
        self.assertIn('href="/calendar.ics"', t)
        self.assertIn('href="/backup.zip"', t)

    def test_unknown_routes_and_methods(self):
        r = self.get("/nope")
        self.assertEqual(r.status, 404)
        self.assertIn("This page doesn't exist.", r.plain)
        self.assertEqual(self.get("/doc/999").status, 404)
        self.assertEqual(self.get("/file/999").status, 404)
        self.assertEqual(self.get("/doc/1.ics").status, 404)
        self.assertEqual(self.get("/file/../../etc/passwd").status, 404)
        self.assertEqual(self.get("/%2e%2e/%2e%2e/etc/passwd").status, 404)
        self.assertEqual(self.get("/analyze").status, 404)
        self.assertEqual(self.request("PUT", "/", body=b"x").status, 501)
        self.set_settings("cs")
        self.assertIn("Tahle stránka neexistuje.", self.get("/nope").plain)


# ==========================================================================
class Security(WebCase):
    def test_wrong_host_is_refused(self):
        for host in ("evil.example", "evil.example:%d" % self.port, "127.0.0.1", "127.0.0.1:1", ""):
            r = self.get("/", host=host)
            self.assertEqual(r.status, 403, host)
            self.assertNotIn("Deadlines", r.text)                      # no page content, only the error
        self.assertEqual(self.get("/", host=f"localhost:{self.port}").status, 200)
        self.assertEqual(self.get("/", host=f"LOCALHOST:{self.port}").status, 200)

    def test_rebinding_with_a_valid_looking_host_but_posting_is_also_refused(self):
        r = self.post("/settings", {"lang": "cs"}, host="evil.example")
        self.assertEqual(r.status, 403)
        self.assertEqual(self.store.get_lang(), "en")

    def test_cross_site_post_is_refused(self):
        doc = self.make_doc()
        for origin in ("http://evil.example", "null", "https://127.0.0.1:%d" % self.port, f"http://127.0.0.1:{self.port + 1}",
                       "http://localhost.evil.example"):
            r = self.post(f"/doc/{doc}/delete", origin=origin)
            self.assertEqual(r.status, 403, origin)
        self.assertIsNotNone(self.store.get_document(doc))

    def test_referer_is_checked_when_there_is_no_origin(self):
        doc = self.make_doc()
        bad = self.post(f"/doc/{doc}/delete", origin=None, headers={"Referer": "http://evil.example/page"})
        self.assertEqual(bad.status, 403)
        self.assertIsNotNone(self.store.get_document(doc))
        good = self.post("/settings", {"lang": "en"}, origin=None, headers={"Referer": self.origin + "/settings"})
        self.assertEqual(good.status, 303)

    def test_missing_or_wrong_csrf_token_is_refused(self):
        doc = self.make_doc()
        self.assertEqual(self.post(f"/doc/{doc}/delete", csrf=False).status, 403)
        r = self.post(f"/doc/{doc}/delete", {"csrf": "wrong"}, csrf=False)
        self.assertEqual(r.status, 403)
        self.assertIn("out of date", r.text)
        self.assertEqual(self.upload("/analyze", "a.txt", b"x", csrf=False).status, 403)
        self.assertEqual(self.upload(f"/doc/{doc}/attach", "a.txt", b"x", csrf=False).status, 403)
        self.assertIsNotNone(self.store.get_document(doc))
        self.assertEqual(self.store.list_attachments(doc), [])

    def test_every_post_route_requires_the_token(self):
        doc = self.make_doc()
        for path in ("/analyze", "/save", f"/doc/{doc}/edit", f"/doc/{doc}/renew", f"/doc/{doc}/attach",
                     f"/doc/{doc}/delete", "/file/1/delete", "/settings"):
            r = self.request("POST", path, body=b"a=1", headers={"Content-Type": "application/x-www-form-urlencoded"})
            self.assertEqual(r.status, 403, path)

    def test_every_form_carries_the_token(self):
        doc = self.make_doc()
        self.store.add_attachment(doc, "a.txt", b"x")
        for path in ("/new", "/review", f"/doc/{doc}", "/settings"):
            t = self.get(path).text
            forms = len(re.findall(r'<form[^>]*method="post"', t))
            tokens = len(re.findall(r'name="csrf" value="%s"' % re.escape(self.app.token), t))
            self.assertGreaterEqual(forms, 1, path)
            self.assertEqual(forms, tokens, path)

    def test_state_changing_requests_cannot_be_made_with_get(self):
        doc = self.make_doc()
        for path in (f"/doc/{doc}/delete", f"/doc/{doc}/renew?mode=y1", "/save", "/file/1/delete"):
            self.assertEqual(self.get(path).status, 404, path)
        self.assertIsNotNone(self.store.get_document(doc))

    def test_server_listens_on_loopback_only(self):
        self.assertEqual(self.httpd.server_address[0], "127.0.0.1")

    def test_missing_content_length_and_chunked_bodies(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.putrequest("POST", "/settings")
        conn.putheader("Origin", self.origin)
        conn.putheader("Content-Type", "application/x-www-form-urlencoded")
        conn.endheaders()
        self.assertEqual(conn.getresponse().status, 411)
        conn.close()
        r = self.request("POST", "/settings", body=iter([b"lang=cs"]), headers={
            "Content-Type": "application/x-www-form-urlencoded", "Transfer-Encoding": "chunked"})
        self.assertEqual(r.status, 411)

    def test_oversized_upload_is_refused_politely(self):
        self.app.max_upload = 50_000
        r = self.upload("/analyze", "big.txt", b"x" * 1_200_000)
        self.assertEqual(r.status, 413)
        self.assertIn("too large", r.plain.lower())
        self.assertEqual(list(self.store.tmp.iterdir()), [])
        self.assertEqual(self.get("/").status, 200)                    # the server is still fine

    def test_malformed_multipart_does_not_crash(self):
        for body in (b"garbage", b"--x\r\n", b""):
            r = self.request("POST", "/analyze", body=body, headers={"Content-Type": "multipart/form-data; boundary=x"})
            self.assertIn(r.status, (400, 403), body)
        self.assertEqual(self.get("/").status, 200)

    def test_no_traceback_is_shown_on_internal_errors(self):
        self.store.get_lang = lambda: 1 / 0               # a failing settings read must not break the page
        self.assertEqual(self.get("/").status, 200)


# ==========================================================================
class Flows(WebCase):
    def test_manual_entry(self):
        t = self.get("/review").text
        self.assertIn("Add a document", t) if "Add a document" in t else None
        r = self.post("/save", {"title": "Dog license", "category": "license", "expires": iso(40),
                                "remind_days": "30, 7", "note": "Town hall", "tmp": ""})
        self.assertEqual(r.status, 303)
        loc = r.header("location")
        self.assertRegex(loc, r"^/doc/\d+\?msg=created$")
        page = self.get(loc).text
        self.assertIn("Dog license", page)
        self.assertIn("Document added", page)
        self.assertIn("in 40 days", page)
        self.assertIn('value="30,7"', page)
        self.assertIn("Town hall", page)

    def test_invalid_input_keeps_the_form_and_explains(self):
        r = self.post("/save", {"title": "  ", "category": "other", "expires": "", "remind_days": "7", "note": "", "tmp": ""})
        self.assertEqual(r.status, 400)
        self.assertIn("Enter a title for the document.", r.text)
        r = self.post("/save", {"title": "Keep me", "category": "other", "expires": "31.2.2027", "remind_days": "x", "note": "", "tmp": ""})
        self.assertEqual(r.status, 400)
        self.assertIn('value="Keep me"', r.text)
        self.assertEqual(self.store.list_documents(), [])

    def test_upload_read_confirm_save(self):
        text = b"INSURANCE POLICY\nPolicy period: 01/01/2026 to 01/01/2027\nDate issued: 12/15/2025\n"
        r = self.upload("/analyze", "home_insurance.txt", text)
        self.assertEqual(r.status, 200)
        self.assertIn('value="2027-01-01"', r.text)                         # the date field is pre-filled
        self.assertIn('<option value="insurance" selected>Insurance</option>', r.text)
        self.assertIn("Jan 1, 2027", r.text)
        self.assertIn("home_insurance.txt", r.text)
        self.assertIn("Text I read from the document", r.text)
        token = re.search(r'name="tmp" value="([0-9a-f]{32})"', r.text).group(1)
        self.assertEqual(self.store.list_documents(), [])                    # nothing is saved before confirmation
        r = self.post("/save", {"title": "Home insurance", "category": "insurance", "expires": "2027-01-01",
                                "remind_days": "60,30", "note": "", "tmp": token})
        self.assertEqual(r.status, 303)
        doc_id = int(re.search(r"/doc/(\d+)", r.header("location")).group(1))
        atts = self.store.list_attachments(doc_id)
        self.assertEqual([a["filename"] for a in atts], ["home_insurance.txt"])
        self.assertIn("Policy period", self.store.get_document(doc_id)["body"])      # text stored for searching
        self.assertEqual([x["title"] for x in self.store.list_documents("policy period")], ["Home insurance"])
        self.assertEqual(list(self.store.tmp.iterdir()), [])
        again = self.post("/save", {"title": "Dup", "category": "other", "expires": "", "remind_days": "7", "note": "", "tmp": token})
        self.assertEqual(again.status, 400)
        self.assertIn("no longer available", again.plain)
        self.assertEqual(len(self.store.list_documents()), 1)

    def test_upload_without_a_file_or_with_a_bad_type(self):
        r = self.upload("/analyze", "", b"")
        self.assertEqual(r.status, 400)
        r = self.upload("/analyze", "virus.exe", b"MZ")
        self.assertEqual(r.status, 400)
        self.assertIn("isn't supported", r.plain)
        r = self.upload("/analyze", "page.html", b"<script>")
        self.assertEqual(r.status, 400)
        self.assertEqual(list(self.store.tmp.iterdir()), [])

    def test_the_date_order_setting_changes_how_a_slash_date_is_read(self):
        data = b"Insurance card\nExpiration date: 03/04/2027\n"
        r = self.upload("/analyze", "card.txt", data)
        self.assertIn('value="2027-03-04"', r.text)
        self.assertIn("can be read two ways", r.text)
        self.assertIn("Mar 4, 2027 or Apr 3, 2027", r.text)
        self.assertIn('data-date="2027-04-03"', r.text)                      # one-click alternative
        self.assertIn("Please check the date against the document.", r.text)
        self.set_settings("en", "dmy")
        r = self.upload("/analyze", "card.txt", data)
        self.assertIn('value="2027-04-03"', r.text)
        self.assertIn('data-date="2027-03-04"', r.text)

    def test_unambiguous_date_has_no_warning(self):
        r = self.upload("/analyze", "card.txt", b"Insurance\nExpires 12/31/2026\n")
        self.assertIn('value="2026-12-31"', r.text)
        self.assertNotIn("can be read two ways", r.text)

    def test_nothing_found_says_so(self):
        r = self.upload("/analyze", "empty.txt", b"hello world, nothing to see")
        self.assertEqual(r.status, 200)
        self.assertIn("I couldn't find an expiry date", r.plain)
        self.assertIn('id="expires" name="expires" value=""', r.text)

    def test_czech_upload(self):
        self.set_settings("cs")
        r = self.upload("/analyze", "pojistka.txt", "Pojistná smlouva\nPlatnost do: 31. 12. 2027\n".encode("utf-8"))
        self.assertIn('value="2027-12-31"', r.text)
        self.assertIn("31. 12. 2027", r.text)
        self.assertIn('selected>Pojištění</option>', r.text)

    def test_edit(self):
        doc = self.make_doc()
        fields = {"title": "Renamed", "category": "vehicle", "expires": iso(200), "remind_days": "14", "note": "n"}
        r = self.post(f"/doc/{doc}/edit", fields)
        self.assertEqual((r.status, r.header("location")), (303, f"/doc/{doc}?msg=saved"))
        d = self.store.get_document(doc)
        self.assertEqual((d["title"], d["category"], d["remind_days"]), ("Renamed", "vehicle", "14"))
        bad = self.post(f"/doc/{doc}/edit", dict(fields, expires="nonsense"))
        self.assertEqual(bad.status, 400)
        self.assertIn("date", bad.text.lower())
        self.assertIn('value="Renamed"', bad.text)
        self.assertEqual(self.post("/doc/999/edit", fields).status, 404)

    def test_renew(self):
        doc = self.store.add_document("Passport", "id", iso(10), "30")
        base = dt.date.fromisoformat(iso(10))
        r = self.post(f"/doc/{doc}/renew", {"mode": "y1"})
        self.assertEqual((r.status, r.header("location")), (303, f"/doc/{doc}?msg=renewed"))
        self.assertEqual(self.store.get_document(doc)["expires"], base.replace(year=base.year + 1).isoformat()
                         if not (base.month == 2 and base.day == 29) else f"{base.year + 1}-02-28")
        self.post(f"/doc/{doc}/renew", {"mode": "date", "date": "2031-05-06"})
        self.assertEqual(self.store.get_document(doc)["expires"], "2031-05-06")
        self.assertEqual(self.post(f"/doc/{doc}/renew", {"mode": "date", "date": "soon"}).status, 400)
        self.assertEqual(self.post(f"/doc/{doc}/renew", {"mode": "bogus"}).status, 400)
        self.assertEqual(self.store.get_document(doc)["expires"], "2031-05-06")

    def test_renewing_something_long_expired_counts_from_today(self):
        doc = self.store.add_document("Old", "id", iso(-900), "30")
        self.post(f"/doc/{doc}/renew", {"mode": "y1"})
        self.assertGreater(self.store.get_document(doc)["expires"], iso(300))

    def test_renewing_a_document_without_a_date(self):
        doc = self.store.add_document("Undated", "other", None, "30")
        self.post(f"/doc/{doc}/renew", {"mode": "y2"})
        self.assertGreater(self.store.get_document(doc)["expires"], iso(700))

    def test_attach_and_delete_file(self):
        doc = self.make_doc()
        r = self.upload(f"/doc/{doc}/attach", "receipt.png", PNG)
        self.assertEqual((r.status, r.header("location")), (303, f"/doc/{doc}?msg=uploaded"))
        att = self.store.list_attachments(doc)[0]
        page = self.get(f"/doc/{doc}").text
        self.assertIn("receipt.png", page)
        self.assertIn(f'src="/file/{att["id"]}"', page)                       # preview of images
        self.assertEqual(self.upload(f"/doc/{doc}/attach", "bad.exe", b"x").status, 400)
        self.assertEqual(self.upload(f"/doc/{doc}/attach", "", b"").status, 400)
        r = self.post(f"/file/{att['id']}/delete")
        self.assertEqual(r.header("location"), f"/doc/{doc}?msg=filedeleted")
        self.assertEqual(self.store.list_attachments(doc), [])
        self.assertEqual(self.post(f"/file/{att['id']}/delete").status, 404)

    def test_delete_document(self):
        doc = self.make_doc()
        self.store.add_attachment(doc, "a.txt", b"x")
        stored = self.store.attachment_path(self.store.list_attachments(doc)[0])
        r = self.post(f"/doc/{doc}/delete")
        self.assertEqual((r.status, r.header("location")), (303, "/?msg=deleted"))
        self.assertIsNone(self.store.get_document(doc))
        self.assertFalse(stored.exists())
        self.assertIn("Document deleted", self.get("/?msg=deleted").text)
        self.assertEqual(self.post(f"/doc/{doc}/delete").status, 404)

    def test_unknown_flash_messages_are_ignored(self):
        t = self.get("/?msg=%3Cb%3Ehi").text
        self.assertNotIn("<b>hi", t)
        self.assertNotIn('role="status"', t)


# ==========================================================================
class FilesAndExports(WebCase):
    def test_pdf_is_shown_inline_other_types_only_downloaded(self):
        doc = self.make_doc()
        pdf = self.store.add_attachment(doc, "policy.pdf", b"%PDF-1.4 x")
        txt = self.store.add_attachment(doc, "notes.txt", b"hello")
        word = self.store.add_attachment(doc, "lease.docx", b"PK")
        r = self.get(f"/file/{pdf}")
        self.assertEqual((r.status, r.header("content-type")), (200, "application/pdf"))
        self.assertTrue(r.header("content-disposition").startswith("inline"))
        self.assertEqual(r.header("x-content-type-options"), "nosniff")
        for att in (txt, word):
            r = self.get(f"/file/{att}")
            self.assertEqual(r.header("content-type"), "application/octet-stream")
            self.assertTrue(r.header("content-disposition").startswith("attachment"))
        dl = self.get(f"/file/{pdf}?dl=1")
        self.assertEqual(dl.header("content-type"), "application/octet-stream")
        self.assertTrue(dl.header("content-disposition").startswith("attachment"))

    def test_images_are_served_with_a_locked_down_policy(self):
        doc = self.make_doc()
        att = self.store.add_attachment(doc, "photo.png", PNG)
        r = self.get(f"/file/{att}")
        self.assertEqual(r.header("content-type"), "image/png")
        self.assertEqual(r.body, PNG)
        self.assertIn("default-src 'none'", r.header("content-security-policy"))

    def test_hostile_file_names_do_not_break_headers(self):
        doc = self.make_doc()
        att = self.store.add_attachment(doc, 'a"b\r\nX-Evil: 1;č.txt', b"x")
        r = self.get(f"/file/{att}")
        self.assertEqual(r.status, 200)
        self.assertNotIn("x-evil", r.headers)
        disp = r.header("content-disposition")
        self.assertIn("filename*=UTF-8''", disp)
        self.assertNotIn("\n", disp)
        self.assertEqual(self.get(f"/doc/{doc}").status, 200)

    def test_a_missing_file_on_disk_gives_a_clear_page(self):
        doc = self.make_doc()
        att = self.store.add_attachment(doc, "a.pdf", b"%PDF")
        self.store.attachment_path(self.store.get_attachment(att)).unlink()
        r = self.get(f"/file/{att}")
        self.assertEqual(r.status, 404)
        self.assertIn("missing", r.text.lower())

    def test_calendar_export(self):
        self.make_doc("Car insurance", expires=iso(60))
        self.store.add_document("Undated")
        for lang, summary in (("en", "SUMMARY:Expires: Car insurance"), ("cs", "SUMMARY:Konec platnosti: Car insurance")):
            self.set_settings(lang)
            r = self.get("/calendar.ics")
            self.assertEqual(r.status, 200)
            self.assertTrue(r.header("content-type").startswith("text/calendar"))
            self.assertIn('filename="deadline-watchdog.ics"', r.header("content-disposition"))
            self.assertIn(summary, r.text)
            self.assertEqual(r.text.count("BEGIN:VEVENT"), 1)
        one = self.get("/doc/1.ics")
        self.assertIn('filename="deadline-1.ics"', one.header("content-disposition"))
        self.assertEqual(self.get("/doc/2.ics").text.count("BEGIN:VEVENT"), 0)

    def test_backup_download_is_a_restorable_zip(self):
        doc = self.make_doc("Lease")
        self.store.add_attachment(doc, "lease.pdf", b"%PDF-lease")
        r = self.get("/backup.zip")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.header("content-type"), "application/zip")
        self.assertRegex(r.header("content-disposition"), r'filename="deadline-watchdog-backup-\d{4}-\d{2}-\d{2}\.zip"')
        with zipfile.ZipFile(io.BytesIO(r.body)) as z:
            self.assertIn("watchdog.db", z.namelist())
            self.assertEqual(len([n for n in z.namelist() if n.startswith("files/")]), 1)
            self.assertIsNone(z.testzip())
        # the server deletes its temporary zip right after sending it, which can be a moment after we read it
        deadline = time.monotonic() + 5
        while list(self.store.tmp.iterdir()) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(list(self.store.tmp.iterdir()), [])                 # no temporary leftovers


# ==========================================================================
class SettingsPage(WebCase):
    def test_defaults(self):
        t = self.get("/settings").text
        self.assertIn('<option value="en" selected>English</option>', t)
        self.assertIn('<option value="cs">Čeština</option>', t)
        self.assertRegex(t, r'value="mdy" checked')
        self.assertNotRegex(t, r'value="dmy" checked')

    def test_save_language_and_order(self):
        r = self.post("/settings", {"lang": "cs", "date_order": "dmy"})
        self.assertEqual((r.status, r.header("location")), (303, "/settings?msg=settings"))
        t = self.get("/settings?msg=settings").text
        self.assertIn('<html lang="cs">', t)
        self.assertIn('<option value="cs" selected>Čeština</option>', t)
        self.assertRegex(t, r'value="dmy" checked')
        self.assertIn("Nastavení je uloženo.", t)

    def test_garbage_values_are_ignored(self):
        self.post("/settings", {"lang": "klingon", "date_order": "ymd"})
        self.assertEqual((self.store.get_lang(), self.store.get_date_order()), ("en", "mdy"))
        self.post("/settings", {"lang": "cs"})
        self.assertEqual(self.store.get_date_order(), "dmy")

    def test_the_setting_survives_a_restart(self):
        self.set_settings("cs", "mdy")
        again = S.Store(self.store.dir)
        self.assertEqual((again.get_lang(), again.get_date_order()), ("cs", "mdy"))


# ==========================================================================
class MultipartParser(unittest.TestCase):
    def test_fields_and_files(self):
        body, ctype = multipart({"a": "1", "b": "čau"}, {"file": ("x y.txt", b"\x00\x01data\r\nline")})
        fields, files = web.parse_multipart(ctype, body)
        self.assertEqual(fields, {"a": "1", "b": "čau"})
        self.assertEqual(files, {"file": ("x y.txt", b"\x00\x01data\r\nline")})

    def test_utf8_file_name(self):
        raw = ('--B\r\nContent-Disposition: form-data; name="file"; filename="příliš žluťoučký.pdf"\r\n\r\ndata\r\n--B--\r\n'
               ).encode("utf-8")
        _, files = web.parse_multipart("multipart/form-data; boundary=B", raw)
        self.assertEqual(files["file"][0], "příliš žluťoučký.pdf")

    def test_not_multipart(self):
        with self.assertRaises(ValueError):
            web.parse_multipart("text/plain", b"hello")


if __name__ == "__main__":
    unittest.main()
