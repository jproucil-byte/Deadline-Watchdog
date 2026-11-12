# Deadline Watchdog – author: jproucil-byte – https://github.com/jproucil-byte/Deadline-Watchdog
"""Reading documents and finding the expiry date.

Standard library only. External tools are optional; without them you simply enter the
date by hand:

  * pdftotext (poppler)       text from PDFs
  * pypdf (pip install pypdf) fallback when pdftotext is missing
  * tesseract (+ pdftoppm)    OCR of scans and photos

The result is language-neutral (codes, ISO dates). The UI / CLI turn it into text with i18n.
Documents are read in English and Czech regardless of the interface language.
"""
from __future__ import annotations

import calendar
import datetime as dt
import importlib.util
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from typing import Optional

import i18n

MAX_TEXT = 200_000          # never process more than this many characters of one document
MIN_PDF_TEXT = 40           # fewer characters = the PDF is probably a scan
OCR_TIMEOUT = 120           # seconds per page / photo
OCR_PAGES = 4               # how many pages of a scanned PDF are read

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp", ".gif"}
TEXT_EXT = {".txt", ".md", ".csv"}

# --------------------------------------------------------------------------
# Categories: id -> default reminder lead times and keywords. Keywords are matched against
# lower-case text without diacritics, English and Czech together.
# --------------------------------------------------------------------------
CATEGORIES = {
    "insurance": {"remind": "60,30,14,7",
                  "kw": [r"insuranc", r"\bpolic(?:y|ies)\b", r"policyholder", r"\binsured\b", r"\bpremium",
                         r"coverage", r"liability", r"deductible",
                         r"pojisten", r"pojistn", r"pojistka", r"povinne\s*ruceni", r"havarijn",
                         r"pojistitel", r"pojistenec"]},
    "vehicle": {"remind": "60,30,14,7,1",
                "kw": [r"vehicle\s*(?:inspection|registration)", r"\bmot\b", r"\bsmog\b", r"\bemissions?\b",
                       r"registration\s*(?:renewal|card|certificate|expir)", r"\bvin\b",
                       r"licen[sc]e\s*plate", r"number\s*plate", r"roadworthi", r"odometer",
                       r"\bstk\b", r"technick\w*\s*kontrol", r"emisn", r"stanice\s*technick",
                       r"protokol\s*o\s*technick", r"\bspz\b", r"registracni\s*znacka"]},
    "inspection": {"remind": "60,30,14,7",
                   "kw": [r"fire\s*extinguisher", r"\bboiler", r"gas\s*safe", r"\beicr\b",
                          r"electrical\s*(?:inspection|safety|installation)", r"inspection\s*certificate",
                          r"\belevator", r"pressure\s*(?:vessel|test)", r"calibration",
                          r"fire\s*(?:safety|alarm)", r"safety\s*certificate", r"annual\s*inspection",
                          r"backflow", r"revizn", r"\brevize\b", r"komin", r"hasic\w*\s*pristroj",
                          r"tlakov\w*\s*nadob"]},
    "warranty": {"remind": "60,30,14,7",
                 "kw": [r"warrant", r"guarantee", r"zarucn", r"zaruk", r"reklamac"]},
    "contract": {"remind": "90,60,30,14",
                 "kw": [r"contract", r"agreement", r"\blease", r"tenant", r"landlord", r"\blessor",
                        r"\blessee", r"subscription", r"membership",
                        r"smlouv", r"dodatek", r"najemn", r"najemce", r"pronajimatel", r"vypoved"]},
    "id": {"remind": "180,90,30,14",
           "kw": [r"passport", r"driver[’']?s?\s*licen[sc]e", r"driving\s*licen[sc]e", r"identity\s*card",
                  r"national\s*id", r"\bid\s*card\b", r"green\s*card", r"residence\s*permit",
                  r"travel\s*document", r"\bvisa\b", r"real\s*id",
                  r"obcansk\w*\s*prukaz", r"cestovn\w*\s*pas", r"ridicsk\w*\s*prukaz", r"ridicak",
                  r"cestovni\s*doklad"]},
    "license": {"remind": "90,60,30,14",
                "kw": [r"certificat", r"licen[sc]", r"accreditation", r"\bpermit\b", r"training",
                       r"certified", r"\bosha\b", r"first\s*aid",
                       r"osvedceni", r"opravneni", r"skoleni", r"bozp", r"zivnostensk"]},
    "medical": {"remind": "30,14,7",
                "kw": [r"medical\s*(?:certificate|exam)", r"health\s*(?:certificate|check)",
                       r"physical\s*exam", r"vaccin", r"immuni[sz]ation", r"prescription", r"check-?up",
                       r"zdravotni\s*zpusobilost", r"lekarsk\w*\s*prohlid", r"ockovani",
                       r"preventivn\w*\s*prohlid"]},
    "invoice": {"remind": "14,7,3,1",
                "kw": [r"invoice", r"bill\s*to", r"amount\s*due", r"balance\s*due", r"payment\s*due",
                       r"due\s*date", r"remit\s*to", r"purchase\s*order",
                       r"faktur", r"danov\w*\s*doklad", r"splatnost", r"variabilni\s*symbol"]},
    "other": {"remind": "30,14,7,1", "kw": []},
}

MONTH_WORDS = {
    # English
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9, "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
    # Czech (without diacritics)
    "ledna": 1, "leden": 1, "unora": 2, "unor": 2, "brezna": 3, "brezen": 3,
    "dubna": 4, "duben": 4, "kvetna": 5, "kveten": 5, "cervna": 6, "cerven": 6,
    "cervence": 7, "cervenec": 7, "srpna": 8, "srpen": 8, "zari": 9,
    "rijna": 10, "rijen": 10, "listopadu": 11, "listopad": 11,
    "prosince": 12, "prosinec": 12,
}
_MONTH_RE = "|".join(sorted(MONTH_WORDS, key=len, reverse=True))

_RE_ISO = re.compile(r"(?<!\d)(\d{4})([-/.])(\d{1,2})\2(\d{1,2})(?!\d)")
_RE_NUM = re.compile(
    r"(?<![\d.])(\d{1,2})(\s{0,2}[./\-]\s{0,2})(\d{1,2})(\s{0,2}[./\-]\s{0,2})(\d{4}|\d{2})(?!\d)")
_RE_DAY_MONTH_YEAR = re.compile(
    r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?\s?\.?\s?(?:of\s+)?[-\s]{0,2}(" + _MONTH_RE + r")(?![a-z])\.?[-\s,]{0,3}(\d{4})(?!\d)")
_RE_MONTH_DAY_YEAR = re.compile(
    r"(?<![a-z])(" + _MONTH_RE + r")(?![a-z])\.?\s{0,2}(\d{1,2})(?:st|nd|rd|th)?\s{0,2},?\s{0,2}(\d{4})(?!\d)")
_RE_MONTH_YEAR = re.compile(
    r"(?<![a-z])(" + _MONTH_RE + r")(?![a-z])\.?\s{0,2},?\s{0,2}(\d{4})(?!\d)")
_RE_NUM_MONTH_YEAR = re.compile(r"(?<![\d.\-/])(\d{1,2})\s?[/.]\s?(\d{4})(?!\d)")

# What stands just before a date and says it is the END (positive weights) ...
_END_PATTERNS = [
    # English
    (r"expir\w*(?:\s*date)?(?:\s*on)?", 10),
    (r"valid\s*(?:until|till|thru|through|to)\b", 10),
    (r"good\s*(?:until|through|thru)", 10),
    (r"renew\w*\s*(?:date|by|on)", 9),
    (r"(?:policy|coverage|cover|term|lease|contract|subscription|membership|warranty|licen[sc]e|certificate"
     r"|registration|permit)\s*(?:period\s*)?(?:ends?|expires?|until|through|thru|to)\b", 10),
    (r"end\s*date", 10),
    (r"(?:next|due)\s*(?:inspection|service|test|renewal|review|calibration|check|payment)\w*", 10),
    (r"\bdue\s*(?:date|by|on)?", 9),
    (r"pay\s*by|payable\s*by|pay\s*before", 8),
    (r"\buntil\b|\btill\b", 6),
    (r"\bthrough\b|\bthru\b", 6),
    (r"\bends?\b", 6),
    (r"(?:^|\W)(?:to|until|through|thru)\s*$", 5),
    (r"\bexp\b\.?", 10),
    # Czech
    (r"platnost\w*[^\n\d]{0,40}\bdo", 9),
    (r"plati\w*\s*(?:az\s*)?do", 10),
    (r"platn[eyaiu]\s*(?:az\s*)?do", 10),
    (r"\b(?:konec|konci|ukonceni|skonceni)\s*(?:platnosti|pojisteni|smlouvy|zaruky|licence|najmu)", 10),
    (r"\bkonec\b", 5),
    (r"\bvyprs\w*", 10),
    (r"(?:pojistn\w*\s*obdobi|pojisteni|zaruka|zaruci\s*doba|smlouva|najem|licence|certifikat)"
     r"\s*(?:je\s*)?(?:sjednan\w*\s*)?(?:na\s*dobu\s*urcitou\s*)?do", 9),
    (r"(?:pristi|dalsi|nasledujici)\s*(?:stk|technick\w*\s*kontrol\w*|prohlidk\w*|kontrol\w*"
     r"|reviz\w*|emis\w*|skoleni|zkousk\w*)", 10),
    (r"(?:termin|datum)\s*(?:pristi|dalsi|nasledujici)\w*", 10),
    (r"\bsplatnost\w*|\bsplatn\w*\s*do|\buhradit\s*do|\bk\s*uhrade\s*do", 9),
    (r"\bplatnost\w*\s*$", 6),
    (r"(?:^|\W)do\s*$", 5),
]
# ... and what says it is a START or some other date (negative weights)
_START_PATTERNS = [
    # English
    (r"effective(?:\s*(?:date|from|on))?", -8),
    (r"\bissued?\b(?:\s*(?:on|date))?|date\s*of\s*issue|\bissue\s*date", -8),
    (r"date\s*of\s*(?:birth|purchase|sale|manufacture|service|signing|inspection|installation|delivery"
     r"|registration)", -8),
    (r"\bdob\b|\bborn\b|birth", -8),
    (r"(?:purchase|order|invoice|statement|billing|print|start|begin|inspection|test|service|install\w*"
     r"|sale|signing|signature)\s*date", -8),
    (r"\bstart\w*|\bbegin\w*|\bcommenc\w*", -9),
    (r"(?:^|\W)from\s*$|\bsince\b", -6),
    (r"\bsigned\b|\bdated\b|\bprinted\b|\bpurchased\b|\binspected\b|\binstalled\b", -5),
    # Czech
    (r"platnost\w*\s*od", -9),
    (r"platn[eyaiu]\s*od", -9),
    (r"(?:pojistn\w*\s*)?obdobi\s*od", -9),
    (r"(?:^|\W)od\s*$", -6),
    (r"datum\s*(?:vystaveni|vydani|podpisu|uzavreni|sepsani|nakupu|prodeje|narozeni|dodani|odeslani)", -8),
    (r"\bvystaven\w*|\bvydan\w*|\bvydal\w*|\bnarozen\w*|\bnar\.", -8),
    (r"\buzavren\w*|\bpodepsan\w*|\bsepsan\w*|\bze\s*dne\b|\bv\s*\w+\s*dne\b|\bdne\s*$", -4),
]
_END_RX = [(re.compile(p), w) for p, w in _END_PATTERNS]
_START_RX = [(re.compile(p), w) for p, w in _START_PATTERNS]
_INTERVAL_RX = re.compile(r"\s*(?:do|az\s*do|az|to|through|thru|until|till|-|–|—)\s*")

_PURCHASE_RX = re.compile(
    r"nakup|prodej|dodani|vystaveni|uskutecneni|duzp|datum\s*(?:plneni|dokladu)|zakoupeno"
    r"|purchase|bought|\bsold\b|\bsale\b|\border(?:ed)?\b|invoice\s*date|deliver|install")
_UNIT = r"(mesic\w*|month\w*|mo\b|let\b|roky|rok\w*|year\w*|yr\w*)"
_RE_WARR = re.compile(
    r"(?:zarucni\s*doba|zaruka|zaruku|zarucni\s*lhuta|warranty|guarantee)(?:\s*(?:period|term|length|of))?"
    r"[^\n\d]{0,40}(\d{1,3})[\s-]*" + _UNIT)
_RE_WARR2 = re.compile(
    r"(\d{1,3})[\s-]*" + _UNIT + r"\s*(?:limited\s*)?(?:zaruka|zaruky|zarucni|warranty|guarantee)")
_RE_PLATE = re.compile(r"\b[0-9][A-Z][A-Z0-9]\s?[0-9]{4}\b")
_GENERIC_STEM = re.compile(
    r"^(img|dsc|dscn|pxl|image|photo|foto|scan|scanned|sken|skenovani|document|dokument|doc|screenshot"
    r"|screen\s*shot|snimek|whatsapp|signal|camera|camscanner|adobe\s*scan|new|untitled|file|download"
    r"|attachment|copy|bez nazvu)[\W_\d]*$")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def fold(text: str) -> str:
    """Lower case without diacritics, character by character (the length stays the same)."""
    out = []
    for ch in text:
        base = "".join(c for c in unicodedata.normalize("NFD", ch) if not unicodedata.combining(c))
        out.append(base.lower()[:1] if base else " ")
    return "".join(out)


def add_months(d: dt.date, n: int) -> dt.date:
    idx = d.year * 12 + (d.month - 1) + n
    y, m = divmod(idx, 12)
    m += 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _mk_date(y: int, m: int, d: int) -> Optional[dt.date]:
    if not (1990 <= y <= 2100):
        return None
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _end_of_month(y: int, m: int) -> Optional[dt.date]:
    if not (1990 <= y <= 2100 and 1 <= m <= 12):
        return None
    return dt.date(y, m, calendar.monthrange(y, m)[1])


def _resolve_numeric(a: int, b: int, year: int, sep: str, order: str):
    """Numbers a, b and a year -> (preferred date, other reading or None).

    Dots always mean day.month.year. With slashes or hyphens 03/04/2027 can be two dates;
    `order` ("mdy" or "dmy") decides which one is preferred, the other is returned as well.
    """
    day_first = _mk_date(year, b, a)
    month_first = _mk_date(year, a, b)
    if sep == ".":
        return day_first, None
    if day_first and month_first and a != b:
        return (month_first, day_first) if order == "mdy" else (day_first, month_first)
    return (day_first or month_first), None


# --------------------------------------------------------------------------
# Finding date candidates ("slots": one place in the text, maybe two readings)
# --------------------------------------------------------------------------
def find_dates(text: str, order: str = "mdy") -> list:
    f = fold(text[:MAX_TEXT])
    taken: list = []
    found: list = []

    def free(s: int, e: int) -> bool:
        return not any(s < e2 and s2 < e for s2, e2 in taken)

    def add(m, date, kind, alt=None):
        # Even an invalid date (31. 2. 2027) keeps its place, so that a piece of it ("2. 2027")
        # can't be re-read as a different, seemingly valid date.
        if free(m.start(), m.end()):
            taken.append((m.start(), m.end()))
            if date:
                found.append({"start": m.start(), "end": m.end(), "date": date, "kind": kind,
                              "alt": alt, "raw": re.sub(r"\s+", " ", text[m.start():m.end()]).strip()})

    for m in _RE_ISO.finditer(f):
        add(m, _mk_date(int(m.group(1)), int(m.group(3)), int(m.group(4))), "day")
    for m in _RE_NUM.finditer(f):
        sep1, sep2 = m.group(2).strip(), m.group(4).strip()
        if sep1 != sep2:
            add(m, None, "day")                  # mixed separators: better no date than a wrong one
            continue
        year = m.group(5)
        year = int(year) if len(year) == 4 else 2000 + int(year)
        primary, alt = _resolve_numeric(int(m.group(1)), int(m.group(3)), year, sep1, order)
        add(m, primary, "day", alt)
    for m in _RE_DAY_MONTH_YEAR.finditer(f):
        add(m, _mk_date(int(m.group(3)), MONTH_WORDS[m.group(2)], int(m.group(1))), "day")
    for m in _RE_MONTH_DAY_YEAR.finditer(f):
        add(m, _mk_date(int(m.group(3)), MONTH_WORDS[m.group(1)], int(m.group(2))), "day")
    for m in _RE_MONTH_YEAR.finditer(f):
        add(m, _end_of_month(int(m.group(2)), MONTH_WORDS[m.group(1)]), "month")
    for m in _RE_NUM_MONTH_YEAR.finditer(f):
        add(m, _end_of_month(int(m.group(2)), int(m.group(1))), "month")

    found.sort(key=lambda c: c["start"])
    return found


def _score_context(ctx: str):
    tail = re.sub(r"[\s:;,.=>\-–—_]+$", "", ctx)
    best_pos, span = 0, None
    for rx, w in _END_RX:
        m = rx.search(tail)
        if m and w > best_pos:
            best_pos, span = w, m.span()
    worst_neg = 0
    for rx, w in _START_RX:
        if rx.search(tail) and w < worst_neg:
            worst_neg = w
    return best_pos + worst_neg, span


def score_slots(text: str, slots: list, today: dt.date) -> list:
    f = fold(text[:MAX_TEXT])
    prev_end = 0
    for i, c in enumerate(slots):
        ctx_start = max(prev_end, c["start"] - 70)
        score, span = _score_context(f[ctx_start:c["start"]])
        c["score"] = float(score)
        c["why"] = re.sub(r"\s+", " ", text[ctx_start + span[0]:ctx_start + span[1]]).strip() if span else ""
        c["interval"] = False
        # a "from X to Y" period: Y is the end, X the start
        if i > 0 and _INTERVAL_RX.fullmatch(f[slots[i - 1]["end"]:c["start"]]):
            c["score"] += 6
            c["interval"] = True
            slots[i - 1]["score"] -= 6
        prev_end = c["end"]
    for c in slots:
        if c["date"].year < 2000:
            c["score"] -= 4
        if c["date"].year > today.year + 40:
            c["score"] -= 3
        if c["date"] >= today:
            c["score"] += 1
    return slots


def _warranty(f: str, slots: list) -> Optional[dict]:
    """'Warranty 24 months' plus a purchase date on the document -> the end of the warranty."""
    if not any(w in f for w in ("zaruc", "zaruk", "warrant", "guarantee")):
        return None
    m = _RE_WARR.search(f) or _RE_WARR2.search(f)
    if not m:
        return None
    n = int(m.group(1))
    months = n * 12 if m.group(2).startswith(("let", "rok", "year", "yr")) else n
    if not (1 <= months <= 600):
        return None
    purchase = None
    for c in slots:
        if c["kind"] != "day":
            continue
        if _PURCHASE_RX.search(f[max(0, c["start"] - 60):c["start"]]):
            purchase = (c, True)
            break
    if purchase is None:
        days = [c for c in slots if c["kind"] == "day"]
        if len(days) == 1:
            purchase = (days[0], False)
    if purchase is None:
        return None
    base, sure = purchase
    return {"date": add_months(base["date"], months), "months": months, "from": base["date"], "sure": sure}


def guess_category(text: str) -> str:
    f = fold(text[:MAX_TEXT])
    best_key, best = "other", 0
    for key, meta in CATEGORIES.items():
        score = 0
        for pat in meta["kw"]:
            hits = len(re.findall(pat, f))
            if hits:
                score += 1 + min(hits - 1, 2)
        if score > best:
            best_key, best = key, score
    return best_key


def guess_title(filename: str, category: str, text: str, lang: str = "en") -> str:
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    clean = re.sub(r"[_\-]+", " ", stem).strip()
    generic = (not clean) or bool(_GENERIC_STEM.match(fold(clean))) \
        or sum(ch.isdigit() for ch in clean) > len(clean) * 0.5
    if not generic:
        return clean[0].upper() + clean[1:]
    label = i18n.category_label(lang, category) if category != "other" else i18n.t(lang, "cat.generic_title")
    if category in ("vehicle", "insurance"):
        plate = _RE_PLATE.search(text.upper())
        if plate:
            return f"{label} – {plate.group(0)}"
    return label


# --------------------------------------------------------------------------
# Main analysis of a text
# --------------------------------------------------------------------------
def analyze_text(text: str, filename: str = "", today: Optional[dt.date] = None,
                 lang: str = "en", date_order: Optional[str] = None) -> dict:
    today = today or dt.date.today()
    order = date_order if date_order in i18n.DATE_ORDERS else i18n.default_date_order(lang)
    text = text or ""
    f = fold(text[:MAX_TEXT])
    slots = score_slots(text, find_dates(text, order), today)
    warr = _warranty(f, slots)

    cands = []
    for i, s in enumerate(slots):
        cands.append({"date": s["date"], "kind": s["kind"], "score": s["score"], "why": s["why"],
                      "interval": s["interval"], "slot": i, "ambiguous": bool(s["alt"])})
        if s["alt"]:
            cands.append({"date": s["alt"], "kind": s["kind"], "score": s["score"] - 0.5, "why": s["why"],
                          "interval": s["interval"], "slot": i, "ambiguous": True})
    ranked = sorted(cands, key=lambda c: (c["score"], c["date"]), reverse=True)
    out_cands = [{"date": c["date"].isoformat(), "kind": c["kind"], "score": c["score"], "why": c["why"],
                  "ambiguous": c["ambiguous"]} for c in ranked[:8]]

    best = ranked[0] if ranked else None
    expires, reason, confidence, score, notes = None, None, "none", 0.0, []
    if best:
        expires, score = best["date"], best["score"]
        if best["interval"]:
            reason = {"code": "interval"}
        elif best["why"]:
            reason = {"code": "label", "text": best["why"]}
        elif best["score"] >= 1:
            reason = {"code": "best_guess"}
        else:
            reason = {"code": "nothing_better"}
    used_warranty = False
    if warr:
        w_score = 10.0 if score < 9 else 7.0
        why = {"code": "warranty", "from": warr["from"].isoformat(), "months": warr["months"],
               "sure": warr["sure"]}
        entry = {"date": warr["date"].isoformat(), "kind": "computed", "score": w_score, "why": "",
                 "ambiguous": False}
        out_cands.insert(0 if w_score >= 10 else len(out_cands), entry)
        if w_score >= 10:
            expires, score, reason, used_warranty = warr["date"], w_score, why, True
    if expires is not None:
        confidence = "high" if score >= 9 else "medium" if score >= 4 else "low"
        if best and best["ambiguous"] and not used_warranty:
            slot = slots[best["slot"]]
            other = slot["alt"] if best["date"] == slot["date"] else slot["date"]
            notes.append({"code": "ambiguous_date", "raw": slot["raw"], "used": best["date"].isoformat(),
                          "other": other.isoformat()})
            if confidence == "high":
                confidence = "medium"

    category = "warranty" if used_warranty else guess_category(text)
    return {
        "category": category,
        "title": guess_title(filename, category, text, lang),
        "expires": expires.isoformat() if expires else None,
        "confidence": confidence,
        "reason": reason,
        "candidates": out_cands,
        "remind_days": CATEGORIES[category]["remind"],
        "notes": notes,
    }


# --------------------------------------------------------------------------
# Tools and reading files
# --------------------------------------------------------------------------
_WIN_PATHS = {
    "tesseract": [r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                  r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"],
}


def find_tool(name: str) -> Optional[str]:
    env = i18n.env(name.upper())                              # WATCHDOG_TESSERACT, WATCHDOG_PDFTOTEXT, ...
    if env and os.path.exists(env):
        return env
    path = shutil.which(name)
    if path:
        return path
    for candidate in _WIN_PATHS.get(name, []):
        if os.path.exists(candidate):
            return candidate
    return None


_langs_cache: dict = {}


def tesseract_langs() -> list:
    exe = find_tool("tesseract")
    if not exe:
        return []
    if exe not in _langs_cache:
        try:
            r = subprocess.run([exe, "--list-langs"], capture_output=True, timeout=20)
            lines = r.stdout.decode("utf-8", "replace").splitlines()
            _langs_cache[exe] = [x.strip() for x in lines[1:] if x.strip()]
        except (OSError, subprocess.SubprocessError):
            _langs_cache[exe] = []
    return _langs_cache[exe]


def wanted_ocr_langs(lang: str) -> list:
    """Tesseract language data the interface language would like to have."""
    return ["ces", "eng"] if lang == "cs" else ["eng"]


def ocr_lang(lang: str = "en") -> str:
    env = i18n.env("OCR_LANG")
    if env:
        return env
    have = tesseract_langs()
    chosen = [x for x in wanted_ocr_langs(lang) if x in have]
    if chosen:
        return "+".join(chosen)
    others = [x for x in have if x != "osd"]
    return others[0] if others else "eng"


def capabilities(lang: str = "en") -> dict:
    langs = tesseract_langs()
    missing = [x for x in wanted_ocr_langs(lang) if langs and x not in langs]
    return {
        "pdf_text": bool(find_tool("pdftotext") or importlib.util.find_spec("pypdf")),
        "ocr_images": bool(find_tool("tesseract")),
        "ocr_pdf": bool(find_tool("tesseract") and find_tool("pdftoppm")),
        "missing_lang": missing[0] if missing else None,
        "langs": langs,
    }


def _decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1250", "latin-2"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_TEXT_NS = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


def _docx_text(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        info = z.getinfo("word/document.xml")
        if info.file_size > 30_000_000:
            raise ValueError("document too large")
        root = ET.fromstring(z.read("word/document.xml"))
    lines = []
    for p in root.iter(_W + "p"):
        parts = []
        for el in p.iter():
            if el.tag == _W + "t":
                parts.append(el.text or "")
            elif el.tag == _W + "tab":
                parts.append("\t")
            elif el.tag in (_W + "br", _W + "cr"):
                parts.append("\n")
        lines.append("".join(parts))
    return "\n".join(lines)


def _odt_text(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        info = z.getinfo("content.xml")
        if info.file_size > 30_000_000:
            raise ValueError("document too large")
        root = ET.fromstring(z.read("content.xml"))
    lines = []
    for el in root.iter():
        if el.tag in (_TEXT_NS + "p", _TEXT_NS + "h"):
            lines.append("".join(el.itertext()))
    return "\n".join(lines)


def _run(cmd: list, timeout: int) -> bytes:
    return subprocess.run(cmd, capture_output=True, timeout=timeout, check=True).stdout


def _note(code: str, **params) -> dict:
    return dict(params, code=code)


def _pdf_text_tool(path: str, notes: list) -> str:
    exe = find_tool("pdftotext")
    if exe:
        try:
            out = _run([exe, "-layout", "-enc", "UTF-8", "-l", "30", path, "-"], 60)
            return out.decode("utf-8", "replace")
        except (OSError, subprocess.SubprocessError):
            notes.append(_note("pdftotext_failed"))
    if importlib.util.find_spec("pypdf"):
        try:
            from pypdf import PdfReader  # type: ignore
            reader = PdfReader(path)
            return "\n".join((pg.extract_text() or "") for pg in reader.pages[:30])
        except Exception:  # noqa: BLE001 - damaged PDF etc.
            notes.append(_note("pdf_unreadable"))
    return ""


def _ocr_image(path: str, psm: int, notes: list, lang: str) -> str:
    exe = find_tool("tesseract")
    if not exe:
        return ""
    try:
        out = _run([exe, path, "stdout", "-l", ocr_lang(lang), "--psm", str(psm)], OCR_TIMEOUT)
        return out.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        notes.append(_note("ocr_timeout"))
    except (OSError, subprocess.SubprocessError):
        notes.append(_note("ocr_failed"))
    return ""


def _ocr_pdf(path: str, psm: int, notes: list, lang: str) -> str:
    pdftoppm = find_tool("pdftoppm")
    if not pdftoppm or not find_tool("tesseract"):
        return ""
    with tempfile.TemporaryDirectory(prefix="watchdog-ocr-") as tmp:
        prefix = os.path.join(tmp, "p")
        try:
            subprocess.run([pdftoppm, "-r", "200", "-f", "1", "-l", str(OCR_PAGES), "-png", path, prefix],
                           capture_output=True, timeout=120, check=True)
        except (OSError, subprocess.SubprocessError):
            notes.append(_note("pdf_convert_failed"))
            return ""
        pages = sorted(x for x in os.listdir(tmp) if x.endswith(".png"))
        return "\n".join(_ocr_image(os.path.join(tmp, x), psm, notes, lang) for x in pages)


def extract_text(path: str, psm: int = 3, name: Optional[str] = None, lang: str = "en") -> dict:
    """-> {'text', 'method', 'notes'}. Never raises because of a bad file.

    The file type comes from the original name (`name`): in-progress uploads are stored
    under other names on disk.
    """
    ext = os.path.splitext(name or path)[1].lower()
    notes: list = []
    text, method = "", "none"
    try:
        if ext in TEXT_EXT:
            with open(path, "rb") as fh:
                text, method = _decode_text(fh.read(2_000_000)), "text"
        elif ext == ".docx":
            text, method = _docx_text(path), "docx"
        elif ext == ".odt":
            text, method = _odt_text(path), "odt"
        elif ext == ".pdf":
            text = _pdf_text_tool(path, notes)
            method = "pdf"
            if len(text.strip()) < MIN_PDF_TEXT:
                if find_tool("tesseract") and find_tool("pdftoppm"):
                    ocr_text = _ocr_pdf(path, psm, notes, lang)
                    if ocr_text.strip():
                        text, method = ocr_text, "ocr"
                else:
                    notes.append(_note("scan_no_tools"))
        elif ext in IMAGE_EXT:
            if find_tool("tesseract"):
                text, method = _ocr_image(path, psm, notes, lang), "ocr"
            else:
                notes.append(_note("photo_no_tool"))
        else:
            notes.append(_note("unsupported"))
    except (OSError, ValueError, zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        notes.append(_note("read_failed", type=type(exc).__name__))
    if method == "ocr":
        have = tesseract_langs()
        missing = [x for x in wanted_ocr_langs(lang) if have and x not in have]
        if missing:
            notes.append(_note("ocr_lang_missing", tess=missing[0]))
    return {"text": text[:MAX_TEXT], "method": method, "notes": notes}


def analyze(path: str, original_name: Optional[str] = None, today: Optional[dt.date] = None,
            lang: str = "en", date_order: Optional[str] = None) -> dict:
    """Reads a file and suggests a title, category and expiry date."""
    name = original_name or os.path.basename(path)
    ex = extract_text(path, name=name, lang=lang)
    result = analyze_text(ex["text"], name, today, lang, date_order)
    # A photo with no date found: try another page-segmentation mode
    if (result["expires"] is None and ex["method"] == "ocr"
            and os.path.splitext(name)[1].lower() in IMAGE_EXT):
        retry = extract_text(path, psm=6, name=name, lang=lang)
        merged = ex["text"] + "\n" + retry["text"]
        again = analyze_text(merged, name, today, lang, date_order)
        if again["expires"]:
            result, ex["text"] = again, merged[:MAX_TEXT]
    result["notes"] = ex["notes"] + result["notes"]
    result.update({"method": ex["method"], "text": ex["text"]})
    return result
