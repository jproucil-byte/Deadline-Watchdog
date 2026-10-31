# Deadline Watchdog – author: jproucil-byte – https://github.com/jproucil-byte/Deadline-Watchdog
"""End-to-end walkthrough in a real Chromium (skipped when Playwright or a browser is missing).

Set WATCHDOG_SHOTS=/some/folder to also save screenshots.
"""
import datetime as dt
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import store as S  # noqa: E402
import web  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
    HAVE_PW = True
except ImportError:
    HAVE_PW = False
try:
    from PIL import Image, ImageDraw, ImageFont
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False
import docparse  # noqa: E402

SHOTS = os.environ.get("WATCHDOG_SHOTS")


def iso(days):
    return (dt.date.today() + dt.timedelta(days=days)).isoformat()


def photo(path, lines):
    try:
        font = ImageFont.load_default(size=54)
    except TypeError:
        font = ImageFont.truetype("DejaVuSans.ttf", 54)
    img = Image.new("RGB", (1500, 140 * len(lines) + 60), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((40, 40 + 140 * i), line, fill="black", font=font)
    img.save(path)


@unittest.skipUnless(HAVE_PW, "Playwright is not installed")
class BrowserWalkthrough(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.pop("WATCHDOG_LANG", None)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.store = S.Store(cls.root / "data")
        cls.httpd, cls.app = web.make_server(cls.store, 0, search=False)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.app.port}"
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as e:  # noqa: BLE001
            cls.pw.stop()
            cls.httpd.shutdown()
            cls.tmp.cleanup()
            raise unittest.SkipTest(f"Chromium cannot be started: {e}")
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        self.ctx = self.browser.new_context(viewport={"width": 1100, "height": 800}, accept_downloads=True)
        self.page = self.ctx.new_page()
        self.problems = []
        self.page.on("console", lambda m: self.problems.append(f"console {m.type}: {m.text}")
                     if m.type in ("error", "warning") else None)
        self.page.on("pageerror", lambda e: self.problems.append(f"pageerror: {e}"))
        self.page.on("dialog", lambda d: d.accept())
        self.addCleanup(self.ctx.close)
        self.addCleanup(lambda: self.assertEqual(self.problems, []))

    def shot(self, name):
        if SHOTS:
            self.page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=True)

    def write(self, name, data):
        p = self.root / name
        p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return str(p)

    # ------------------------------------------------------------------------------------
    def test_01_full_story_in_english(self):
        page = self.page
        for d in list(self.store.list_documents()):
            self.store.delete_document(d["id"])
        self.store.set_lang("en")
        self.store.set_date_order("mdy")

        page.goto(self.url + "/")
        self.assertIn("Nothing here yet", page.inner_text("main"))
        self.shot("01-empty")

        # upload a text file with an ambiguous US/EU date: the form submits itself after choosing the file
        page.click("nav >> text=\"Add\"")
        self.shot("02-add")
        page.set_input_files("input[type=file]", self.write(
            "policy.txt", "HOME INSURANCE POLICY\nPolicyholder: J. Smith\nExpiration date: 03/04/2027\nIssued: 03/05/2026\n"))
        page.wait_for_url("**/analyze")
        self.assertEqual(page.input_value("#expires"), "2027-03-04")
        self.assertEqual(page.input_value("#category"), "insurance")
        body = page.inner_text("main")
        self.assertIn("can be read two ways", body)
        self.assertIn("Please check the date against the document.", body)
        self.shot("03-review-ambiguous")

        # the other reading is one click away
        page.click("button[data-date='2027-04-03']")
        self.assertEqual(page.input_value("#expires"), "2027-04-03")
        self.assertIsNone(page.query_selector("button[data-date='2027-03-04']"))     # the chosen date is not offered again
        page.fill("#expires", "2027-03-04")

        # changing the category fills in sensible reminders until the user types their own
        page.select_option("#category", "id")
        self.assertEqual(page.input_value("#remind_days"), "180,90,30,14")
        page.fill("#remind_days", "21")
        page.select_option("#category", "invoice")
        self.assertEqual(page.input_value("#remind_days"), "21")
        page.select_option("#category", "insurance")

        page.fill("#title", "Home insurance")
        page.click("form[action='/save'] button[type=submit]")
        page.wait_for_url("**/doc/*")
        self.assertIn("Document added.", page.inner_text("main"))
        self.assertIn("Mar 4, 2027", page.inner_text("main"))
        self.assertEqual(len(page.query_selector_all(".files li")), 1)
        self.shot("04-detail")

        # a photo, read by OCR (needs Tesseract and Pillow)
        if docparse.capabilities()["ocr_images"] and HAVE_PIL:
            photo(self.root / "card.png", ["Vehicle registration", "Valid until March 4, 2028"])
            page.goto(self.url + "/new")
            page.set_input_files("input[type=file]", str(self.root / "card.png"))
            page.wait_for_url("**/analyze", timeout=60000)
            self.assertEqual(page.input_value("#expires"), "2028-03-04")
            self.assertEqual(page.input_value("#category"), "vehicle")
            page.fill("#title", "Car registration")
            page.click("form[action='/save'] button[type=submit]")
            page.wait_for_url("**/doc/*")
            page.wait_for_selector("img.thumb")
            self.assertGreater(page.eval_on_selector("img.thumb", "i => i.naturalWidth"), 0)

        # a document without a date, added by hand
        page.goto(self.url + "/new")
        page.click("text=Add without a file")
        page.fill("#title", "Gym membership")
        page.select_option("#category", "contract")
        page.fill("#expires", iso(12))
        page.click("form[action='/save'] button[type=submit]")
        page.wait_for_url("**/doc/*")

        # overview, tiles, search
        page.goto(self.url + "/")
        self.assertGreaterEqual(len(page.query_selector_all("a.doc")), 2)
        self.assertEqual(page.inner_text("a.tile.soon .n"), "1")
        self.shot("05-overview")
        page.click("a.tile.soon")
        self.assertEqual(len(page.query_selector_all("a.doc")), 1)
        self.assertIn("Gym membership", page.inner_text("a.doc"))
        page.goto(self.url + "/")
        page.fill("input[type=search]", "HOME insurance")
        page.press("input[type=search]", "Enter")
        self.assertEqual(len(page.query_selector_all("a.doc")), 1)

        # renew with one click, then delete (the confirm dialog is accepted by the handler above)
        page.click("a.doc")
        page.wait_for_url("**/doc/*")
        page.click("button[name=mode][value=y1]")
        page.wait_for_selector("text=Expiry date updated.")
        self.assertIn("Mar 4, 2028", page.inner_text("main"))
        page.click("text=Delete document")
        page.wait_for_url(self.url + "/?msg=deleted")
        self.assertEqual(len(page.query_selector_all("a.doc")), len(self.store.list_documents()))

    def test_02_czech_and_date_order_setting(self):
        page = self.page
        self.store.set_lang("en")
        page.goto(self.url + "/settings")
        page.select_option("#lang", "cs")
        page.check("input[name=date_order][value=dmy]")
        page.click("button[type=submit]")
        page.wait_for_url("**/settings?msg=settings")
        self.assertEqual(page.get_attribute("html", "lang"), "cs")
        self.assertIn("Nastavení je uloženo.", page.inner_text("main"))
        self.shot("06-settings-cs")
        page.click("nav >> text=\"Přidat\"")
        page.set_input_files("input[type=file]", self.write("smlouva.txt", "Pojistná smlouva\nPlatnost do: 31. 12. 2027\n"))
        page.wait_for_url("**/analyze")
        self.assertEqual(page.input_value("#expires"), "2027-12-31")
        self.assertIn("31. 12. 2027", page.inner_text("main"))
        self.shot("07-review-cs")
        self.store.set_lang("en")
        self.store.set_date_order("mdy")

    def test_03_downloads(self):
        self.store.set_lang("en")
        self.store.add_document("Download test", "other", iso(30), "7")
        page = self.page
        page.goto(self.url + "/export")
        with page.expect_download() as dl:
            page.click("text=Download calendar (.ics)")
        self.assertEqual(dl.value.suggested_filename, "deadline-watchdog.ics")
        self.assertIn("BEGIN:VCALENDAR", Path(dl.value.path()).read_text(encoding="utf-8"))
        with page.expect_download() as dl:
            page.click("a[href='/backup.zip']")
        self.assertRegex(dl.value.suggested_filename, r"^deadline-watchdog-backup-\d{4}-\d{2}-\d{2}\.zip$")

    def test_04_phone_width_has_no_sideways_scroll_and_the_menu_fits(self):
        self.store.set_lang("en")
        self.store.add_document("A rather long document title that has to wrap on a small screen", "insurance", iso(3), "7")
        for lang in ("en", "cs"):
            self.store.set_lang(lang)
            ctx = self.browser.new_context(viewport={"width": 390, "height": 800}, device_scale_factor=2, is_mobile=True)
            page = ctx.new_page()
            for path in ("/", "/new", "/export", "/settings", "/doc/1"):
                page.goto(self.url + path)
                self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 391, (lang, path))
            page.goto(self.url + "/")
            nav_h = page.evaluate("document.querySelector('header.top').getBoundingClientRect().height")
            self.assertLess(nav_h, 110, (lang, nav_h))              # brand + a single row of menu items
            if SHOTS:
                page.screenshot(path=os.path.join(SHOTS, f"08-mobile-{lang}.png"), full_page=True)
            ctx.close()
        self.store.set_lang("en")

    def test_05_dark_mode_is_readable(self):
        self.store.set_lang("en")
        self.store.add_document("Dark mode", "contract", iso(-2), "7")
        ctx = self.browser.new_context(viewport={"width": 1100, "height": 800}, color_scheme="dark")
        page = ctx.new_page()
        page.goto(self.url + "/")
        bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
        fg = page.evaluate("getComputedStyle(document.body).color")
        lum = lambda c: sum(int(x) for x in c[c.index('(') + 1:-1].split(",")[:3]) / 3  # noqa: E731
        self.assertLess(lum(bg), 60)
        self.assertGreater(lum(fg), 180)
        if SHOTS:
            page.screenshot(path=os.path.join(SHOTS, "09-dark.png"), full_page=True)
        ctx.close()

    def test_06_pages_are_not_blocked_by_their_own_policy(self):
        # the nonce-based script policy must let our script run: the form submits itself after choosing a file
        page = self.page
        page.goto(self.url + "/new")
        page.set_input_files("input[type=file]", self.write("x.txt", "Valid until 12/31/2031"))
        page.wait_for_url("**/analyze")
        self.assertEqual(page.input_value("#expires"), "2031-12-31")


if __name__ == "__main__":
    unittest.main()
