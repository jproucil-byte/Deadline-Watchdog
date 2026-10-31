# Deadline Watchdog – author: jproucil-byte – https://github.com/jproucil-byte/Deadline-Watchdog
import datetime as dt
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import docparse as d  # noqa: E402

TODAY = dt.date(2026, 10, 28)


def analyze(text, name="", order="mdy", lang="en"):
    return d.analyze_text(text, name, TODAY, lang, order)


class DateDetectionEnglish(unittest.TestCase):
    def expect(self, text, expected, order="mdy", **kw):
        r = analyze(text, kw.get("name", ""), order)
        self.assertEqual(r["expires"], expected, msg=str(r))
        return r

    def test_expires_and_expiration_date(self):
        self.expect("Expires: 12/31/2026", "2026-12-31")
        r = self.expect("Expiration Date: December 31, 2026", "2026-12-31")
        self.assertEqual(r["confidence"], "high")

    def test_valid_until_through_thru(self):
        self.expect("Valid until 4th March 2027", "2027-03-04")
        self.expect("Valid through March 4, 2027", "2027-03-04")
        self.expect("VALID THRU 2027-03-04", "2027-03-04")
        self.expect("Good through 06/2027", "2027-06-30")

    def test_month_names_and_ordinals(self):
        for text in ("Registration expires Mar. 4, 2027", "Expires 4 March 2027", "Exp. 04-Mar-2027",
                     "Expires March 4th, 2027", "Expires 4th of March 2027", "expires MAR 4 2027"):
            self.expect(text, "2027-03-04")

    def test_policy_period_takes_the_end(self):
        r = self.expect("INSURANCE POLICY\nPolicy period: 01/01/2026 to 01/01/2027\nDate issued: 12/15/2025",
                        "2027-01-01")
        self.assertEqual(r["reason"], {"code": "interval"})
        self.assertEqual(r["category"], "insurance")
        self.expect("Policy Period 01/01/2026 - 12/31/2026", "2026-12-31")
        self.expect("Lease term: January 1, 2026 through December 31, 2026", "2026-12-31")

    def test_next_inspection_due_beats_the_inspection_date(self):
        self.expect("Next inspection due: 15 June 2027\nInspected on 15 June 2026", "2027-06-15")
        r = self.expect("MOT test certificate. Expiry date: 14 September 2027", "2027-09-14", order="dmy")
        self.assertEqual(r["category"], "vehicle")

    def test_driver_license_picks_exp_not_dob_or_issue(self):
        r = self.expect("Driver License\nDOB 05/14/1985\nISS 03/01/2022\nEXP 03/01/2030", "2030-03-01")
        self.assertEqual(r["category"], "id")

    def test_passport(self):
        r = self.expect("PASSPORT Date of birth 14 MAR 1985 Date of issue 05 MAR 2024 Date of expiry 04 MAR 2034",
                        "2034-03-04")
        self.assertEqual(r["category"], "id")

    def test_invoice_due_date(self):
        r = self.expect("Invoice date: 10/01/2026\nDue date: 11/15/2026", "2026-11-15")
        self.assertEqual(r["category"], "invoice")

    def test_renewal(self):
        self.expect("This policy renews on 2027-02-01.", "2027-02-01")
        r = self.expect("Subscription renewal date: Jan 5, 2027", "2027-01-05")
        self.assertEqual(r["category"], "contract")

    def test_ocr_noise_in_spacing_and_case(self):
        self.expect("EXPIRATION  DATE  :  12 / 31 / 2026", "2026-12-31")
        self.expect("VALID   UNTIL   31 . 12 . 2026", "2026-12-31")

    def test_two_digit_year(self):
        self.expect("Exp. 12/31/26", "2026-12-31")
        self.expect("Valid until 31.12.26", "2026-12-31")

    def test_not_a_date(self):
        for text in ("Phone 555-1234, ZIP 90210, version 1.2.3", "Expires 02/31/2027", "Expires 13/13/2027", ""):
            r = self.expect(text, None)
            self.assertEqual(r["confidence"], "none")

    def test_a_lonely_date_has_low_confidence(self):
        r = self.expect("Thank you for your order #1234 on May 5, 2026. Free shipping.", "2026-05-05")
        self.assertEqual(r["confidence"], "low")

    def test_impossible_month_day_does_not_become_another_date(self):
        # "2. 2027" must not be re-read out of "31. 2. 2027"
        self.expect("Valid until 31. 2. 2027", None)
        self.expect("Valid until 31.12/2026", None)           # mixed separators


class AmbiguousDates(unittest.TestCase):
    def test_slash_date_follows_the_chosen_order(self):
        us = analyze("Expiration date: 03/04/2027", order="mdy")
        eu = analyze("Expiration date: 03/04/2027", order="dmy")
        self.assertEqual(us["expires"], "2027-03-04")
        self.assertEqual(eu["expires"], "2027-04-03")

    def test_ambiguity_is_reported_and_confidence_lowered(self):
        r = analyze("Expiration date: 03/04/2027")
        self.assertEqual(r["confidence"], "medium")
        self.assertEqual(r["notes"], [{"code": "ambiguous_date", "raw": "03/04/2027",
                                       "used": "2027-03-04", "other": "2027-04-03"}])
        dates = [c["date"] for c in r["candidates"]]
        self.assertIn("2027-04-03", dates)                    # the other reading is offered
        self.assertTrue(all(c["ambiguous"] for c in r["candidates"] if c["date"] in ("2027-03-04", "2027-04-03")))

    def test_unambiguous_dates_have_no_note_and_keep_high_confidence(self):
        for text in ("Expires 12/31/2026", "Expires 31/12/2026", "Expires 05/05/2027", "Expires 2027-03-04"):
            r = analyze(text)
            self.assertEqual(r["notes"], [], text)
            self.assertEqual(r["confidence"], "high", text)

    def test_day_above_12_decides_regardless_of_order(self):
        for order in ("mdy", "dmy"):
            self.assertEqual(analyze("Expires 12/31/2026", order=order)["expires"], "2026-12-31")
            self.assertEqual(analyze("Expires 31/12/2026", order=order)["expires"], "2026-12-31")

    def test_dots_are_always_day_first(self):
        self.assertEqual(analyze("Expires 3.4.2027", order="mdy")["expires"], "2027-04-03")
        self.assertEqual(analyze("Expires 3.4.2027", order="mdy")["notes"], [])

    def test_hyphens_follow_the_order(self):
        self.assertEqual(analyze("Expires 03-04-2027", order="mdy")["expires"], "2027-03-04")
        self.assertEqual(analyze("Expires 03-04-2027", order="dmy")["expires"], "2027-04-03")

    def test_default_order_depends_on_interface_language(self):
        self.assertEqual(d.analyze_text("Expires 03/04/2027", "", TODAY, "en")["expires"], "2027-03-04")
        self.assertEqual(d.analyze_text("Expires 03/04/2027", "", TODAY, "cs")["expires"], "2027-04-03")
        self.assertEqual(d.analyze_text("Expires 03/04/2027", "", TODAY, "cs", "mdy")["expires"], "2027-03-04")

    def test_interval_with_ambiguous_dates(self):
        r = analyze("Policy period: 03/04/2026 to 03/04/2027")
        self.assertEqual(r["expires"], "2027-03-04")
        self.assertEqual(r["notes"][0]["raw"], "03/04/2027")


class DateDetectionCzech(unittest.TestCase):
    def expect(self, text, expected):
        r = analyze(text, "", "dmy", "cs")
        self.assertEqual(r["expires"], expected, msg=str(r))
        return r

    def test_czech_documents_are_still_read(self):
        self.expect("Platnost do: 31. 12. 2026", "2026-12-31")
        self.expect("Pojistné období od 1. 1. 2026 do 31. 12. 2026\nDatum vystavení: 5. 12. 2025", "2026-12-31")
        self.expect("OBČANSKÝ PRŮKAZ\nDatum narození 14. 3. 1985\nDatum vydání 5.3.2024\nPlatnost do 5.3.2034", "2034-03-05")
        self.expect("Platnost technické prohlídky do 10/2027", "2027-10-31")
        self.expect("Smlouva platí do 15. března 2027, podepsáno 15. března 2025", "2027-03-15")
        self.expect("Platnost do 15. brezna 2027", "2027-03-15")
        self.expect("Platnost do\n31.12.2027\nVydáno 1.1.2025", "2027-12-31")
        self.expect("Příští STK: 3.5.2026\nDatum kontroly 3.5.2024", "2026-05-03")

    def test_czech_invoice_and_category(self):
        r = self.expect("Faktura č. 1\nDatum vystavení 1.10.2026\nDatum splatnosti: 15.11.2026", "2026-11-15")
        self.assertEqual(r["category"], "invoice")

    def test_a_czech_document_read_with_the_english_interface(self):
        r = analyze("Pojistná smlouva, povinné ručení. Platnost do 31. 12. 2027", "x.pdf", "mdy", "en")
        self.assertEqual((r["expires"], r["category"]), ("2027-12-31", "insurance"))


class Warranty(unittest.TestCase):
    def test_czech(self):
        r = analyze("Záruční list\nDatum prodeje: 12. 5. 2025\nZáruční doba: 24 měsíců", "", "dmy", "cs")
        self.assertEqual((r["expires"], r["category"], r["confidence"]), ("2027-05-12", "warranty", "high"))

    def test_english_months_and_years(self):
        r = analyze("Warranty card\nDate of purchase: 05/12/2025\nWarranty period: 24 months")
        self.assertEqual((r["expires"], r["category"], r["confidence"]), ("2027-05-12", "warranty", "high"))
        self.assertEqual(r["reason"]["months"], 24)
        self.assertEqual(analyze("2-year limited warranty. Purchase date: June 1, 2025")["expires"], "2027-06-01")
        self.assertEqual(analyze("Warranty: 3 years\nPurchased on 2025-02-01")["expires"], "2028-02-01")
        self.assertEqual(analyze("12 month warranty. Invoice date: 2026-01-31")["expires"], "2027-01-31")

    def test_unsure_purchase_date_is_flagged(self):
        r = analyze("Limited warranty 1 year. 03/15/2026")
        self.assertEqual(r["expires"], "2027-03-15")
        self.assertFalse(r["reason"]["sure"])

    def test_explicit_end_beats_computation(self):
        r = analyze("Warranty card. Purchase date 01/01/2025. Warranty period 24 months. Warranty valid until 06/15/2027")
        self.assertEqual(r["expires"], "2027-06-15")

    def test_month_arithmetic_does_not_overflow(self):
        self.assertEqual(d.add_months(dt.date(2025, 1, 31), 1), dt.date(2025, 2, 28))
        self.assertEqual(d.add_months(dt.date(2024, 1, 31), 1), dt.date(2024, 2, 29))
        self.assertEqual(d.add_months(dt.date(2025, 11, 15), 3), dt.date(2026, 2, 15))


class CategoryAndTitle(unittest.TestCase):
    def test_categories_english(self):
        cases = {"Certificate of insurance. Policy number 123, coverage and liability": "insurance",
                 "Vehicle inspection report. Emissions test. VIN 1HGCM82633A004352": "vehicle",
                 "Fire extinguisher annual inspection certificate": "inspection",
                 "Limited warranty and guarantee": "warranty",
                 "Residential lease agreement between landlord and tenant": "contract",
                 "United States passport": "id", "Driver's license": "id",
                 "Food handler certification training": "license",
                 "Invoice. Amount due. Remit to": "invoice", "Medical certificate, physical exam": "medical",
                 "nothing interesting here": "other"}
        for text, expected in cases.items():
            self.assertEqual(d.guess_category(text), expected, text)

    def test_categories_czech(self):
        self.assertEqual(d.guess_category("Pojistná smlouva, povinné ručení"), "insurance")
        self.assertEqual(d.guess_category("Protokol o technické kontrole STK"), "vehicle")
        self.assertEqual(d.guess_category("Revizní zpráva elektro"), "inspection")
        self.assertEqual(d.guess_category("Občanský průkaz"), "id")

    def test_title_from_the_file_name(self):
        self.assertEqual(analyze("", "home_insurance_2026.pdf")["title"], "Home insurance 2026")

    def test_generic_file_names_are_replaced(self):
        for name in ("IMG_20260310_1234.jpg", "scan0001.pdf", "Scan 2026-01-02.pdf", "Screenshot 2026-03-01.png",
                     "document (3).pdf", "DSC_0042.JPG", "image.png"):
            self.assertEqual(analyze("", name)["title"], "Document", name)
        self.assertEqual(analyze("Auto insurance policy. Coverage. Expires 12/31/2026", "IMG_0042.jpg")["title"],
                         "Insurance")
        self.assertEqual(analyze("", "scan0001.pdf", lang="cs")["title"], "Dokument")
        self.assertEqual(analyze("Pojistná smlouva, povinné ručení", "IMG_1.jpg", lang="cs")["title"], "Pojištění")

    def test_czech_licence_plate_in_the_title(self):
        r = analyze("Protokol o technické kontrole STK, SPZ 5L1 4321, platnost do 10/2027", "IMG_1.jpg", lang="cs")
        self.assertEqual(r["title"], "STK / emise / registrace vozidla – 5L1 4321")

    def test_default_reminders_follow_the_category(self):
        self.assertEqual(analyze("Passport. Date of expiry 04 MAR 2034")["remind_days"], "180,90,30,14")
        self.assertEqual(analyze("Invoice. Due date: 11/15/2026")["remind_days"], "14,7,3,1")


class Helpers(unittest.TestCase):
    def test_fold_keeps_the_length(self):
        for s in ("Příliš žluťoučký kůň", "İstanbul ß ǅ", "ŘEŠENÍ", "naïve café", ""):
            self.assertEqual(len(d.fold(s)), len(s), s)
        self.assertEqual(d.fold("Příliš ŽLUŤOUČKÝ café"), "prilis zlutoucky cafe")

    def test_candidates_are_language_neutral_iso_dates(self):
        r = analyze("Expires 12/31/2026")
        self.assertEqual(r["candidates"][0]["date"], "2026-12-31")
        self.assertEqual(set(r["candidates"][0]), {"date", "kind", "score", "why", "ambiguous"})


def make_docx(path, paragraphs):
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w='
           '"http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + body + "</w:body></w:document>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)


class FileExtraction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def test_txt_in_utf8_and_cp1250(self):
        text = "Valid until 12/31/2026 – příliš žluťoučký kůň"
        for enc in ("utf-8", "cp1250"):
            p = self.path(f"a-{enc}.txt")
            with open(p, "wb") as fh:
                fh.write(text.encode(enc))
            self.assertEqual(d.extract_text(p)["text"], text, enc)
            self.assertEqual(d.analyze(p, today=TODAY)["expires"], "2026-12-31", enc)

    def test_docx(self):
        p = self.path("lease.docx")
        make_docx(p, ["Residential Lease Agreement", "Lease ends", "June 30, 2028"])
        res = d.analyze(p, today=TODAY)
        self.assertEqual((res["method"], res["expires"], res["category"]), ("docx", "2028-06-30", "contract"))

    def test_damaged_docx_does_not_crash(self):
        p = self.path("broken.docx")
        with open(p, "wb") as fh:
            fh.write(b"this is not a zip")
        res = d.analyze(p)
        self.assertIsNone(res["expires"])
        self.assertEqual([n["code"] for n in res["notes"]], ["read_failed"])
        self.assertEqual(res["notes"][0]["type"], "BadZipFile")

    def test_unknown_type(self):
        p = self.path("data.xlsx")
        with open(p, "wb") as fh:
            fh.write(b"PK")
        res = d.analyze(p)
        self.assertEqual((res["method"], [n["code"] for n in res["notes"]]), ("none", ["unsupported"]))

    def test_missing_file_does_not_crash(self):
        self.assertEqual(d.extract_text(self.path("nope.pdf"))["text"].strip(), "")

    def test_type_comes_from_the_original_name_not_the_path(self):
        # uploads waiting for confirmation are stored as <token>.bin
        src = self.path("lease.docx")
        make_docx(src, ["Expires", "June 30, 2028"])
        blob = self.path("a287387572fc472bb494b34349b5ef34.bin")
        os.replace(src, blob)
        res = d.analyze(blob, "lease.docx", TODAY)
        self.assertEqual((res["method"], res["expires"]), ("docx", "2028-06-30"))
        txt = self.path("b.bin")
        with open(txt, "wb") as fh:
            fh.write(b"Expires 02/01/2029 (Feb 1)")
        self.assertEqual(d.analyze(txt, "note.txt", TODAY)["method"], "text")
        self.assertEqual(d.analyze(txt, "note.xyz", TODAY)["method"], "none")

    def test_ocr_language_choice(self):
        old = os.environ.pop("WATCHDOG_OCR_LANG", None)
        self.addCleanup(lambda: os.environ.__setitem__("WATCHDOG_OCR_LANG", old) if old else None)
        self.assertEqual(d.wanted_ocr_langs("en"), ["eng"])
        self.assertEqual(d.wanted_ocr_langs("cs"), ["ces", "eng"])
        os.environ["WATCHDOG_OCR_LANG"] = "eng+deu"
        self.assertEqual(d.ocr_lang("en"), "eng+deu")


def _image_with_text(path, lines, size=54):
    from PIL import Image, ImageDraw, ImageFont  # type: ignore
    try:
        font = ImageFont.load_default(size=size)
    except TypeError:
        font = ImageFont.truetype("DejaVuSans.ttf", size)
    img = Image.new("RGB", (1500, 140 * len(lines) + 60), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((40, 40 + 140 * i), line, fill="black", font=font)
    img.save(path)
    return img


CAP = d.capabilities()
try:
    import PIL  # noqa: F401
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False
try:
    import reportlab  # noqa: F401
    HAVE_RL = True
except ImportError:
    HAVE_RL = False


class OptionalTools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def p(self, name):
        return os.path.join(self.tmp.name, name)

    @unittest.skipUnless(CAP["ocr_images"] and HAVE_PIL, "needs Tesseract and Pillow")
    def test_ocr_of_a_photo_in_us_format(self):
        _image_with_text(self.p("photo.png"), ["Insurance policy", "Expiration date: 12/31/2026"])
        res = d.analyze(self.p("photo.png"), "photo.png", TODAY)
        self.assertEqual((res["method"], res["expires"], res["category"]), ("ocr", "2026-12-31", "insurance"),
                         msg=res["text"])

    @unittest.skipUnless(CAP["ocr_images"] and HAVE_PIL, "needs Tesseract and Pillow")
    def test_ocr_of_a_photo_with_month_names(self):
        _image_with_text(self.p("photo.png"), ["Vehicle registration", "Valid until March 4, 2027"])
        res = d.analyze(self.p("photo.png"), "photo.png", TODAY)
        self.assertEqual((res["expires"], res["category"]), ("2027-03-04", "vehicle"), msg=res["text"])

    @unittest.skipUnless(CAP["ocr_images"] and HAVE_PIL, "needs Tesseract and Pillow")
    def test_ocr_works_with_a_foreign_extension_on_disk(self):
        _image_with_text(self.p("photo.png"), ["Insurance policy", "Valid until 31.12.2026"])
        os.replace(self.p("photo.png"), self.p("0123456789abcdef0123456789abcdef.bin"))
        res = d.analyze(self.p("0123456789abcdef0123456789abcdef.bin"), "photo.png", TODAY)
        self.assertEqual(res["expires"], "2026-12-31")

    @unittest.skipUnless(CAP["pdf_text"] and HAVE_RL, "needs pdftotext/pypdf and reportlab")
    def test_pdf_with_text(self):
        from reportlab.pdfgen import canvas  # type: ignore
        c = canvas.Canvas(self.p("policy.pdf"))
        c.setFont("Helvetica", 14)
        c.drawString(72, 760, "Insurance contract no. 123")
        c.drawString(72, 730, "Valid until 03/15/2027")
        c.save()
        res = d.analyze(self.p("policy.pdf"), "policy.pdf", TODAY)
        self.assertEqual((res["method"], res["expires"]), ("pdf", "2027-03-15"))

    @unittest.skipUnless(CAP["ocr_pdf"] and HAVE_PIL, "needs Tesseract, pdftoppm and Pillow")
    def test_scanned_pdf(self):
        img = _image_with_text(self.p("tmp.png"), ["Warranty card", "Valid until 09/01/2028"])
        img.save(self.p("scan.pdf"))
        res = d.analyze(self.p("scan.pdf"), "scan.pdf", TODAY)
        self.assertEqual((res["method"], res["expires"]), ("ocr", "2028-09-01"), msg=str(res["notes"]))

    @unittest.skipUnless(CAP["ocr_images"] and HAVE_PIL, "needs Tesseract and Pillow")
    def test_missing_czech_data_is_reported_only_for_czech_ui(self):
        if "ces" in d.tesseract_langs():
            self.skipTest("Czech data is installed")
        from PIL import Image  # type: ignore
        Image.new("RGB", (400, 100), "white").save(self.p("blank.png"))
        codes_en = [n["code"] for n in d.extract_text(self.p("blank.png"), lang="en")["notes"]]
        notes_cs = d.extract_text(self.p("blank.png"), lang="cs")["notes"]
        self.assertNotIn("ocr_lang_missing", codes_en)
        self.assertEqual([n for n in notes_cs if n["code"] == "ocr_lang_missing"],
                         [{"code": "ocr_lang_missing", "tess": "ces"}])


if __name__ == "__main__":
    unittest.main()
