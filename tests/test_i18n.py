# Deadline Watchdog – author: jproucil-byte – https://github.com/jproucil-byte/Deadline-Watchdog
import datetime as dt
import os
import re
import string
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import i18n  # noqa: E402
from docparse import CATEGORIES  # noqa: E402


def fields(entry):
    texts = entry if isinstance(entry, tuple) else (entry,)
    return {name for text in texts for _, name, _, _ in string.Formatter().parse(text) if name}


class Completeness(unittest.TestCase):
    def test_both_languages_have_the_same_keys(self):
        self.assertEqual(sorted(set(i18n.EN) ^ set(i18n.CS)), [])

    def test_placeholders_match_between_languages(self):
        for key in i18n.EN:
            self.assertEqual(fields(i18n.EN[key]) - {"n"}, fields(i18n.CS[key]) - {"n"}, key)

    def test_plural_entries_have_the_right_number_of_forms(self):
        for key, entry in i18n.EN.items():
            if isinstance(entry, tuple):
                self.assertEqual(len(entry), 2, key)
        for key, entry in i18n.CS.items():
            if isinstance(entry, tuple):
                self.assertEqual(len(entry), 3, key)
        for key in i18n.EN:
            self.assertEqual(isinstance(i18n.EN[key], tuple), isinstance(i18n.CS[key], tuple), key)

    def test_no_empty_strings(self):
        for lang, table in i18n.STRINGS.items():
            for key, entry in table.items():
                for text in (entry if isinstance(entry, tuple) else (entry,)):
                    self.assertTrue(text.strip(), f"{lang}:{key}")

    def test_every_key_used_in_the_code_exists(self):
        used = set()
        for name in ("web.py", "store.py", "docparse.py", "watchdog.py"):
            src = open(os.path.join(ROOT, name), encoding="utf-8").read()
            used |= set(re.findall(
                r'(?:self\.(?:T|E|TN|H)|i18n\.t|i18n\.tn|L)\(\s*(?:lang,\s*|self\.lang,\s*)?["\']([a-z0-9_.]+)["\']', src))
            used |= set(re.findall(r'ValidationError\(\s*["\']([a-z0-9_.]+)["\']', src))
            used |= set(re.findall(r'HttpError\(\s*\d+,\s*["\']([a-z0-9_.]+)["\']', src))
        used -= {"en"}                                           # the language code in i18n.t("en", ...)
        used = {k for k in used if not k.endswith(".")}          # prefixes of dynamically built keys
        self.assertGreater(len(used), 80)
        for lang in ("en", "cs"):
            self.assertEqual(sorted(k for k in used if k not in i18n.STRINGS[lang]), [], lang)

    def test_dynamically_built_keys_exist(self):
        wanted = (["flash." + k for k in ("saved", "created", "deleted", "renewed", "uploaded", "filedeleted",
                                          "settings")]
                  + ["http.title." + c for c in ("403", "404", "413", "default")]
                  + ["set.mdy", "set.dmy"] + ["tile." + k for k in ("expired", "soon", "ok")]
                  + ["status." + k for k in ("expired", "soon", "today", "ok", "none")]
                  + ["cat." + k for k in CATEGORIES] + ["cat.generic_title"]
                  + ["conf." + k for k in ("high", "medium", "low", "none")]
                  + ["reason." + k for k in ("label", "interval", "warranty", "warranty_guess", "best_guess",
                                             "nothing_better")]
                  + ["note." + k for k in ("scan_no_tools", "photo_no_tool", "unsupported", "read_failed",
                                           "ocr_timeout", "ocr_failed", "pdftotext_failed", "pdf_unreadable",
                                           "ocr_lang_missing", "pdf_convert_failed", "ambiguous_date")]
                  + ["cli.g." + k for k in ("expired", "soon", "ok", "none")])
        for lang in ("en", "cs"):
            self.assertEqual(sorted(k for k in wanted if k not in i18n.STRINGS[lang]), [], lang)

    def test_every_note_code_the_reader_can_produce_is_translated(self):
        src = open(os.path.join(ROOT, "docparse.py"), encoding="utf-8").read()
        codes = set(re.findall(r'_note\(\s*"([a-z_]+)"', src)) | {"ambiguous_date"}
        for code in codes:
            self.assertIn("note." + code, i18n.EN, code)

    def test_every_text_can_be_filled_in(self):
        """A placeholder called `lang` once collided with the language argument and crashed a page."""
        for lang in ("en", "cs"):
            for key, entry in i18n.STRINGS[lang].items():
                if isinstance(entry, tuple):
                    text = i18n.tn(lang, key, 2, **{name: "x" for name in fields(entry) if name != "n"})
                else:
                    text = i18n.t(lang, key, **{name: "x" for name in fields(entry)})
                self.assertNotRegex(text, r"\{[a-z_]+\}", f"{lang}:{key}")

    def test_notes_with_parameters_render(self):
        note = {"code": "ocr_lang_missing", "tess": "ces"}
        self.assertIn("“ces”", i18n.note_text("en", note))
        self.assertIn("„ces“", i18n.note_text("cs", note))
        self.assertIn("“ces”", i18n.t("en", "cap.lang_missing", tess="ces"))
        self.assertIn("PermissionError", i18n.note_text("en", {"code": "read_failed", "type": "PermissionError"}))


class Branding(unittest.TestCase):
    def setUp(self):
        self._saved = {k: v for k, v in os.environ.items() if k.startswith(i18n.ENV_PREFIXES)}
        for k in self._saved:
            del os.environ[k]
        self.addCleanup(self._restore)

    def _restore(self):
        for k in [k for k in os.environ if k.startswith(i18n.ENV_PREFIXES)]:
            del os.environ[k]
        os.environ.update(self._saved)

    def test_author_and_project_are_credited(self):
        self.assertEqual(i18n.APP_AUTHOR, "jproucil-byte")
        self.assertEqual(i18n.APP_URL, "https://github.com/jproucil-byte/Deadline-Watchdog")
        self.assertTrue(i18n.APP_URL.lower().endswith("/" + i18n.APP_SLUG))
        self.assertEqual(i18n.APP_SLUG, i18n.APP_NAME.lower().replace(" ", "-"))

    def test_app_name_is_filled_in_from_one_place(self):
        for lang in ("en", "cs"):
            self.assertIn(i18n.APP_NAME, i18n.t(lang, "err.restore_nodb"))
            self.assertIn(i18n.APP_NAME, i18n.t(lang, "cli.restore_warn2"))
        self.assertIn("by", i18n.t("en", "footer_by"))
        self.assertIn("od", i18n.t("cs", "footer_by"))

    def test_environment_prefixes_and_their_order(self):
        self.assertIsNone(i18n.env("LANG"))
        os.environ["HLIDAC_LANG"] = "cs"
        self.assertEqual(i18n.env("LANG"), "cs")                        # names of the first version still work
        os.environ["KEEPER_LANG"] = "en"
        self.assertEqual(i18n.env("LANG"), "en")
        os.environ["WATCHDOG_LANG"] = "cs"
        self.assertEqual(i18n.env("LANG"), "cs")                        # the current name wins
        os.environ["WATCHDOG_LANG"] = ""
        self.assertEqual(i18n.env("LANG"), "en")                        # an empty value counts as unset


class Formatting(unittest.TestCase):
    def test_plurals(self):
        self.assertEqual([i18n.tn("en", "files.count", n) for n in (1, 2, 0)],
                         ["1 file", "2 files", "0 files"])
        self.assertEqual([i18n.tn("cs", "files.count", n) for n in (1, 2, 4, 5, 11, 0)],
                         ["1 soubor", "2 soubory", "4 soubory", "5 souborů", "11 souborů", "0 souborů"])

    def test_date_formats(self):
        self.assertEqual(i18n.fmt_date("2027-03-04"), "Mar 4, 2027")
        self.assertEqual(i18n.fmt_date(dt.date(2026, 12, 31)), "Dec 31, 2026")
        self.assertEqual(i18n.fmt_date("2027-03-04", "cs"), "4. 3. 2027")
        self.assertEqual(i18n.fmt_date(dt.datetime(2027, 3, 4, 12, 0)), "Mar 4, 2027")

    def test_relative_days_english(self):
        expected = {0: "today", 1: "tomorrow", -1: "yesterday", 3: "in 3 days", -5: "5 days ago", 60: "in 60 days",
                    150: "in 5 months", -150: "5 months ago", 800: "in 2 years", -800: "2 years ago"}
        for d, text in expected.items():
            self.assertEqual(i18n.days_phrase("en", d), text, d)
        self.assertEqual(i18n.days_phrase("en", None), "no deadline")

    def test_relative_days_czech(self):
        expected = {0: "dnes", 1: "zítra", -1: "včera", 3: "za 3 dny", 5: "za 5 dní", -5: "před 5 dny",
                    -2: "před 2 dny", 150: "za 5 měsíců", -150: "před 5 měsíci", 800: "za 2 roky",
                    -800: "před 2 lety", 2685: "za 7 let"}
        for d, text in expected.items():
            self.assertEqual(i18n.days_phrase("cs", d), text, d)

    def test_fallbacks(self):
        self.assertEqual(i18n.t("xx", "nav.overview"), "Overview")          # unknown language -> English
        self.assertEqual(i18n.t("en", "no.such.key"), "no.such.key")        # unknown key -> the key
        self.assertEqual(i18n.norm_lang("fr"), "en")
        self.assertEqual(i18n.default_date_order("en"), "mdy")
        self.assertEqual(i18n.default_date_order("cs"), "dmy")

    def test_items_and_notes(self):
        self.assertEqual(i18n.item_line("en", "Policy", "2026-11-04", 6), "Policy – expires in 6 days (Nov 4, 2026)")
        self.assertEqual(i18n.item_line("en", "Policy", "2026-11-04", 0), "Policy – expires today (Nov 4, 2026)")
        self.assertEqual(i18n.item_line("en", "Policy", "2026-10-20", -9), "Policy – expired 9 days ago (Oct 20, 2026)")
        self.assertEqual(i18n.item_line("cs", "Pojistka", "2026-11-04", 6), "Pojistka – vyprší za 6 dní (4. 11. 2026)")
        note = {"code": "ambiguous_date", "raw": "03/04/2027", "used": "2027-03-04", "other": "2027-04-03"}
        self.assertIn("Mar 4, 2027 or Apr 3, 2027", i18n.note_text("en", note))
        self.assertIn("4. 3. 2027 nebo 3. 4. 2027", i18n.note_text("cs", note))
        self.assertEqual(i18n.reason_text("en", {"code": "label", "text": "Valid until"}),
                         "found next to “Valid until”")
        self.assertEqual(i18n.reason_text("en", None), "")
        self.assertIn("24 months", i18n.reason_text(
            "en", {"code": "warranty", "from": "2025-05-12", "months": 24, "sure": True}))

    def test_status_label_today(self):
        self.assertEqual(i18n.status_label("en", {"key": "soon", "days": 0}), "Today")
        self.assertEqual(i18n.status_label("en", {"key": "soon", "days": 5}), "Soon")
        self.assertEqual(i18n.status_label("cs", {"key": "expired", "days": -1}), "Prošlo")


if __name__ == "__main__":
    unittest.main()
