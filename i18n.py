# Deadline Watchdog – author: jproucil-byte – https://github.com/jproucil-byte/Deadline-Watchdog
"""Translations and locale helpers. English is the primary language, Czech the second.

Everything the user reads goes through t() / tn(). The reader (docparse) and the store
return language-neutral codes, and the UI / CLI turn them into text here.
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Optional

APP_NAME = "Deadline Watchdog"
APP_SLUG = "deadline-watchdog"          # file names, calendar ids
APP_AUTHOR = "jproucil-byte"
APP_URL = "https://github.com/jproucil-byte/Deadline-Watchdog"
# Environment variables: WATCHDOG_DATA, WATCHDOG_LANG, ... KEEPER_ and HLIDAC_ are names used by earlier versions.
ENV_PREFIXES = ("WATCHDOG_", "KEEPER_", "HLIDAC_")
LANGS = {"en": "English", "cs": "Čeština"}
DEFAULT_LANG = "en"
DATE_ORDERS = ("mdy", "dmy")
MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def env(name: str) -> Optional[str]:
    """Value of WATCHDOG_<name> (or the name used by an earlier version), if set and not empty."""
    for prefix in ENV_PREFIXES:
        value = os.environ.get(prefix + name)
        if value:
            return value
    return None


def norm_lang(value) -> str:
    return value if value in LANGS else DEFAULT_LANG


def default_date_order(lang: str) -> str:
    """Order for numeric dates such as 03/04/2027 when the user has not chosen one."""
    return "dmy" if lang == "cs" else "mdy"


# --------------------------------------------------------------------------
# Strings. A tuple is a plural entry: (one, other) in English, (one, few, many) in Czech.
# --------------------------------------------------------------------------
EN = {
    # navigation / chrome
    "nav.overview": "Overview", "nav.add": "Add", "nav.export": "Export",
    "nav.settings": "Settings",
    "footer": "Your data stays on this computer ({path}). Nothing is sent anywhere.",
    "footer_by": "by",
    "common.back": "← Overview", "common.cancel": "Cancel",
    # status
    "status.expired": "Expired", "status.soon": "Soon", "status.today": "Today",
    "status.ok": "OK", "status.none": "No end date",
    "tile.expired": "Expired", "tile.soon": "Expiring soon", "tile.ok": "All good",
    # overview
    "ov.title": "Deadlines", "ov.add": "Add document",
    "ov.search_ph": "Search documents…", "ov.search_label": "Search", "ov.cat_label": "Category",
    "ov.all_categories": "All categories", "ov.search_btn": "Search",
    "ov.empty_title": "Nothing here yet",
    "ov.empty_text": "Upload a photo or PDF of an insurance policy, vehicle inspection, warranty or contract. "
                     "The app reads the expiry date and reminds you in time.",
    "ov.empty_btn": "Add your first document",
    "ov.no_match": "Nothing found. Try changing the search or the filter.",
    "ov.no_date": "no end date",
    "files.count": ("{n} file", "{n} files"),
    # add document
    "new.title": "Add document", "new.drop_main": "Choose or drop a file here",
    "new.drop_sub": "PDF, photo, Word… (up to 40 MB)", "new.read_btn": "Read document",
    "new.manual": "Add without a file",
    "new.reading": "Reading the document… (photos and scans can take up to half a minute)",
    "new.cap_title": "What can be read on this computer",
    "new.cap_note": "I always show what I found so you can check it first. Anything I can't read, you enter by hand.",
    "new.err_nofile": "Choose a file first.",
    "cap.docx": "Word (DOCX), ODT and text files", "cap.pdf": "PDFs with text",
    "cap.ocr": "Photos and scans (OCR)", "cap.ocrpdf": "Scanned PDFs (OCR)",
    "cap.need_pdf": "pdftotext (or the pypdf library) is missing",
    "cap.need_tess": "Tesseract is missing", "cap.need_tesspdf": "Tesseract or pdftoppm is missing",
    "cap.lang_missing": "Tesseract has no “{tess}” language data, so text recognition will be less accurate.",
    # review
    "review.title": "Check the details",
    "review.file": "The file {name} will be saved with the document.",
    "review.found": "Expiry date: {date} (confidence: {conf}; {reason}).",
    "review.none": "I couldn't find an expiry date in the document. Please enter it yourself.",
    "review.check_date": "Please check the date against the document.",
    "review.others": "Other dates found – click one to use it:",
    "review.text_summary": "Text I read from the document",
    "review.fix": "Something needs fixing:",
    "cand.month_end": "(end of month)",
    # form
    "form.title": "Title", "form.category": "Category", "form.expires": "Expiry date",
    "form.expires_hint": "(leave empty if it doesn't expire)", "form.remind": "Remind me in advance",
    "form.remind_hint": "(days before, separated by commas)", "form.note": "Note",
    "form.save": "Save", "form.save_changes": "Save changes",
    # detail
    "detail.no_end": "No end date", "detail.data": "Details",
    "detail.ics": "Add to calendar (.ics)", "detail.text": "Text read from the document",
    "renew.title": "Renewed?",
    "renew.help": "If you've renewed the document, move the end date. Reminders then start counting again.",
    "renew.y1": "+ 1 year", "renew.y2": "+ 2 years", "renew.exact": "Or set the new end date exactly",
    "renew.set": "Set date",
    "files.title": "Files", "files.none": "No files yet.", "files.add": "Add another file",
    "files.upload": "Upload", "files.open": "Open", "files.download": "Download",
    "files.delete": "Delete", "files.confirm": "Delete this file?", "files.preview": "Preview: {name}",
    "del.title": "Delete", "del.help": "Deletes the document and all of its files.",
    "del.btn": "Delete document",
    "del.confirm": "Really delete the whole document including its files? This can't be undone.",
    # flash messages
    "flash.saved": "Saved.", "flash.created": "Document added.", "flash.deleted": "Document deleted.",
    "flash.renewed": "Expiry date updated.", "flash.uploaded": "File added.",
    "flash.filedeleted": "File deleted.", "flash.settings": "Settings saved.",
    # http errors
    "http.title.403": "Not allowed", "http.title.404": "Not found", "http.title.413": "File too large",
    "http.title.default": "Error",
    "http.bad_host": "Invalid address. Open the app using the address printed when it started.",
    "http.cross_site": "The request came from another site, so it was not processed.",
    "http.stale": "This page is out of date (the app restarted in the meantime). "
                  "Go back, reload the page and try again.",
    "http.not_found": "This page doesn't exist.", "http.no_length": "Missing request length.",
    "http.bad_request": "Invalid request.", "http.too_big": "The file is too large (40 MB at most).",
    "http.unsupported": "Unsupported way of sending data.", "http.form_unreadable": "The form could not be read.",
    "http.server_error": "Something went wrong. Details are in the window where the program is running.",
    "http.bad_action": "Unknown action.", "http.no_file": "That file doesn't exist.",
    "http.file_missing": "The file is missing on disk.",
    "http.no_doc": "That document doesn't exist (it may have been deleted).",
    "http.back": "Back to overview",
    # export
    "export.title": "Export & backup",
    "export.cal_title": "Calendar (reminders on your phone)",
    "export.cal_text": "Download the file with your deadlines and open it in the calendar you use (Google Calendar, "
                       "Apple Calendar, Outlook…). Each document becomes an all-day event on its expiry date, and your "
                       "calendar notifies you at 9:00, as many days ahead as you set for the document.",
    "export.cal_note": "This is a one-time export. Download it again after changes. Most calendars update existing "
                       "events instead of duplicating them (in some programs it's safer to delete the old events "
                       "before importing).",
    "export.cal_btn": "Download calendar (.ics)",
    "export.desk_title": "Desktop notifications",
    "export.desk_text": "The app can check your deadlines every day by itself and show a desktop notification "
                        "when something is coming up, even when the app isn't open.",
    "export.bk_title": "Backup",
    "export.bk_text": "The backup file contains the database and every uploaded document. Keep it somewhere other "
                      "than this computer (disk, cloud). To restore, close the app and run this in a terminal:",
    "export.bk_btn": "Download backup (.zip)",
    # settings
    "set.title": "Settings", "set.lang": "Language", "set.date_order": "Numeric dates such as 03/04/2027",
    "set.mdy": "Month first – 03/04/2027 is March 4 (US)",
    "set.dmy": "Day first – 03/04/2027 is 3 April (UK, EU, most of the world)",
    "set.date_help": "Used only when a document's date can be read two ways. The app always shows you the date "
                     "it understood in an unambiguous form so you can check it.",
    "set.save": "Save settings",
    # reader notes
    "note.scan_no_tools": "This PDF looks like a scan (it has no text). Reading scans needs Tesseract and "
                          "pdftoppm – see the README. Enter the date by hand.",
    "note.photo_no_tool": "Reading photos needs Tesseract – see the README. Enter the date by hand.",
    "note.unsupported": "I can't read this file type automatically. Enter the details by hand; "
                        "the file is still saved.",
    "note.read_failed": "The file could not be read ({type}). Enter the details by hand.",
    "note.ocr_timeout": "Text recognition took too long and was stopped.",
    "note.ocr_failed": "Tesseract could not be started.",
    "note.pdftotext_failed": "pdftotext failed, trying another method.",
    "note.pdf_unreadable": "The PDF could not be read as text.",
    "note.ocr_lang_missing": "Tesseract has no “{tess}” language data, so text recognition will be less "
                             "accurate. Numbers and dates usually still read fine – check the date anyway.",
    "note.pdf_convert_failed": "Converting the PDF pages to images failed.",
    "note.ambiguous_date": "“{raw}” can be read two ways: {used} or {other}. I used {used} "
                           "(you can change the default in Settings).",
    "reason.label": "found next to “{text}”", "reason.interval": "end of a “from … to …” period",
    "reason.warranty": "purchase date {from_} + {months} months of warranty",
    "reason.warranty_guess": "purchase date {from_} + {months} months of warranty "
                             "(assuming that is the purchase date)",
    "reason.best_guess": "the most likely of the dates found", "reason.nothing_better": "nothing better found",
    "conf.high": "high", "conf.medium": "medium", "conf.low": "low", "conf.none": "none",
    # categories
    "cat.insurance": "Insurance", "cat.vehicle": "Vehicle inspection / registration",
    "cat.inspection": "Safety inspection", "cat.warranty": "Warranty",
    "cat.contract": "Contract / lease / subscription", "cat.id": "ID / travel document",
    "cat.license": "License / certification", "cat.medical": "Medical",
    "cat.invoice": "Invoice / due date", "cat.other": "Other", "cat.generic_title": "Document",
    # validation errors
    "err.title_required": "Enter a title for the document.",
    "err.title_long": "The title is too long (200 characters at most).",
    "err.bad_category": "Unknown category.",
    "err.note_long": "The note is too long (5000 characters at most).",
    "err.bad_date": "Enter the date like 2026-12-31 (or 31. 12. 2026).",
    "err.remind_format": "Enter reminders as numbers of days before the end, for example 60, 30, 14, 7.",
    "err.remind_max": "A reminder can be at most 3650 days ahead.",
    "err.remind_count": "At most 12 reminders are allowed.",
    "err.file_type": "That file type isn't supported. Allowed: PDF, photos (JPG, PNG, TIFF…), Word (DOCX), "
                     "text and spreadsheet files.",
    "err.file_empty": "The file is empty.", "err.file_big": "The file is too large (40 MB at most).",
    "err.upload_gone": "The uploaded file is no longer available. Please upload it again.",
    "err.restore_nodb": "The backup has no database – it isn't a {app} backup.",
    "err.restore_unexpected": "The backup contains an unexpected item “{name}”, so I'm cancelling the restore.",
    "err.restore_big": "The backup is unusually large.",
    "err.restore_struct": "The database in the backup doesn't have the expected structure.",
    "err.restore_notzip": "That isn't a valid zip file with a backup.",
    "err.restore_corrupt": "The database in the backup is damaged, so I'm cancelling the restore.",
    # calendar
    "ics.summary": "Expires: {title}", "ics.category": "Category: {cat}",
    "ics.alarm": "{title} – expires {when} ({date})",
    # item lines (CLI / notifications)
    "item.expired": "{title} – expired {when} ({date})",
    "item.today": "{title} – expires today ({date})",
    "item.expires": "{title} – expires {when} ({date})",
    # CLI
    "cli.title": "{app} – {date} ({docs})",
    "cli.docs": ("{n} document", "{n} documents"),
    "cli.g.expired": "EXPIRED", "cli.g.soon": "DUE SOON", "cli.g.ok": "ALL GOOD", "cli.g.none": "NO END DATE",
    "cli.more": "{label}: {n} (show with --all)",
    "cli.empty": "No documents saved yet. Run the program without a command and add your first one.",
    "cli.nothing_due": "Nothing is coming up, so there is nothing to notify about.",
    "cli.dry_run": "(dry run – nothing was announced or marked)",
    "cli.test_ok": "Notification sent.",
    "cli.test_fail": "Desktop notifications can't be shown here (see the README).",
    "cli.test_text": "Test notification – if you can see this, it works.",
    "cli.notify_title": ("{app}: {n} deadline", "{app}: {n} deadlines"),
    "cli.notify_more": "… and {n} more",
    "cli.notify_unavailable": "Desktop notifications can't be shown here, so the list above has to do. The items "
                              "stay marked as not announced and will be listed again next time.",
    "cli.exported": "Calendar saved: {path}",
    "cli.backup": "Backup saved: {path} ({kb} kB)",
    "cli.no_file": "File {path} doesn't exist.",
    "cli.restore_warn1": "Restoring replaces all current data with the data from the backup. Current data isn't "
                         "deleted – it's moved next to it into a folder ending in “-before-restore-…”.",
    "cli.restore_warn2": "Close any running {app} first (otherwise the database may be locked). "
                         "Then run the command again with --yes.",
    "cli.restored": "Restored. The previous data is in this folder:",
    "cli.a.method": "Read by:", "cli.a.title": "Suggested title:", "cli.a.category": "Category:",
    "cli.a.expires": "Expiry date:", "cli.a.none": "not found", "cli.a.cand": "candidate",
    "cli.a.note": "Note:", "cli.a.conf": "confidence",
    "srv.running": "{app} is running at {url}", "srv.data": "Data: {path}",
    "srv.stop": "Stop it with Ctrl+C (or by closing this window).", "srv.bye": "Stopping.",
    "cli.error": "Error: {msg}",
    # --- added in 1.2 ---
    "ov.tags_label": "Tags", "ov.archive_link": ("Archive ({n} document)", "Archive ({n} documents)"),
    "ov.archive_title": "Archive", "ov.archive_back": "← Back to active documents",
    "ov.archive_empty": "The archive is empty.",
    "arch.title": "Archive",
    "arch.help": "Archived documents keep their files but don't appear in the overview, don't send reminders and "
                 "aren't in the calendar export. Handy for things you no longer need (a sold car, a cancelled contract).",
    "arch.btn": "Move to archive", "arch.restore_btn": "Move back from archive",
    "arch.banner": "This document is archived: it doesn't send reminders and isn't exported to the calendar.",
    "recur.none": "Doesn't repeat", "recur.months": ("every month", "every {n} months"),
    "recur.years": ("every year", "every {n} years"),
    "form.recur": "Repeats", "form.recur_hint": "(for renewing with one click)",
    "form.tags": "Tags", "form.tags_hint": "(separated by commas, e.g. car, Jane)",
    "renew.recur": "Renew for the next period ({every})",
    "sched.on": "Automatic reminders are on.", "sched.off": "Automatic reminders are off.",
    "sched.how.windows": "Windows Task Scheduler checks your deadlines every day at 9:00 and when you sign in "
                         "(if the computer was off at 9:00, it checks as soon as it can).",
    "sched.how.mac": "macOS checks your deadlines every day at 9:00 and when you log in.",
    "sched.how.linux": "The check runs every time you log in to your desktop.",
    "sched.enable": "Turn on automatic reminders", "sched.disable": "Turn off automatic reminders",
    "sched.test": "Send a test notification",
    "sched.unsupported": "Reminders can't be scheduled automatically on this system. Run the command below "
                         "regularly yourself (see README.md).",
    "sched.manual": "Command for running the check by hand",
    "set.cat_title": "Your own categories",
    "set.cat_help": "Add categories that the built-in ones don't cover. Deleting one moves its documents to “Other”.",
    "set.cat_none": "No categories of your own yet.", "set.cat_label": "Name of the new category",
    "set.cat_remind": "Default reminders (days before)", "set.cat_add": "Add category",
    "set.cat_delete": "Delete", "set.cat_confirm": "Delete this category? Its documents will move to “Other”.",
    "set.cat_used": ("used by {n} document", "used by {n} documents"),
    "set.ab_title": "Automatic backup",
    "set.ab_help": "The app regularly saves a backup (database and all files) into a folder you choose, ideally one "
                   "synced to the cloud or on another disk, and keeps only the newest ones. It runs while the app is "
                   "open and during the daily reminder check.",
    "set.ab_suggest": "Suggestion: {path}",
    "set.ab_dir": "Folder for backups", "set.ab_dir_hint": "(empty = off)",
    "set.ab_days": "Back up every … days", "set.ab_keep": "Number of backups to keep",
    "set.ab_save": "Save backup settings", "set.ab_now": "Back up now",
    "set.ab_off": "Automatic backup is off.", "set.ab_never": "No automatic backup has been made yet.",
    "set.ab_last": "Last automatic backup: {when}", "set.ab_error": "The last attempt failed: {msg}",
    "flash.archived": "Moved to the archive.", "flash.unarchived": "Moved back from the archive.",
    "flash.cat_added": "Category added.", "flash.cat_deleted": "Category deleted.",
    "flash.ab_saved": "Backup settings saved.", "flash.ab_done": "Backup saved.",
    "flash.sched_on": "Automatic reminders are on.", "flash.sched_off": "Automatic reminders are off.",
    "flash.test_sent": "Test notification sent. Can you see it?",
    "err.tag_long": "A tag can have at most {n} characters.", "err.tag_count": "At most {n} tags are allowed.",
    "err.bad_recur": "Choose how often the deadline repeats.",
    "err.no_recur": "This document doesn't repeat. Set “Repeats” first.",
    "err.cat_label_required": "Enter a name for the category.",
    "err.cat_label_long": "The category name is too long (60 characters at most).",
    "err.cat_exists": "A category with that name already exists.",
    "err.ab_relative": "Enter the full path of the folder (for example D:\\Backups or /home/me/backups).",
    "err.ab_inside": "The backup folder can't be inside the app's own data folder.",
    "err.ab_numbers": "Back up every 1 to 365 days and keep 1 to 100 backups.",
    "err.ab_failed": "The backup failed: {msg}",
    "err.sched_failed": "Automatic reminders could not be set up: {msg}",
    "srv.already": "{app} is already running at {url} – opening it in the browser.",
    "cli.ab_done": "Automatic backup saved: {path}",
    "cli.sched_removed": "Automatic reminders are off.",
    "cli.sched_test": "Try it now with: watchdog.py notify --test",
}

CS = {
    "nav.overview": "Přehled", "nav.add": "Přidat", "nav.export": "Export",
    "nav.settings": "Nastavení",
    "footer": "Data jsou jen na tomhle počítači ({path}). Nic se nikam neodesílá.",
    "footer_by": "od",
    "common.back": "← Přehled", "common.cancel": "Zrušit",
    "status.expired": "Prošlo", "status.soon": "Brzy", "status.today": "Dnes",
    "status.ok": "V pořádku", "status.none": "Bez konce",
    "tile.expired": "Prošlo", "tile.soon": "Brzy vyprší", "tile.ok": "V pořádku",
    "ov.title": "Přehled termínů", "ov.add": "Přidat dokument",
    "ov.search_ph": "Hledat v dokumentech…", "ov.search_label": "Hledat", "ov.cat_label": "Kategorie",
    "ov.all_categories": "Všechny kategorie", "ov.search_btn": "Hledat",
    "ov.empty_title": "Zatím tu nic není",
    "ov.empty_text": "Nahraj fotku nebo PDF pojistky, STK, revize, záruky nebo smlouvy. Program z něj vyčte "
                     "datum konce platnosti a včas ti dá vědět.",
    "ov.empty_btn": "Přidat první dokument",
    "ov.no_match": "Nic jsem nenašel. Zkus upravit hledání nebo filtr.",
    "ov.no_date": "bez termínu",
    "files.count": ("{n} soubor", "{n} soubory", "{n} souborů"),
    "new.title": "Přidat dokument", "new.drop_main": "Vyber nebo sem přetáhni soubor",
    "new.drop_sub": "PDF, fotka, Word… (do 40 MB)", "new.read_btn": "Přečíst dokument",
    "new.manual": "Přidat bez souboru",
    "new.reading": "Čtu dokument… (u fotek a skenů to může trvat i půl minuty)",
    "new.cap_title": "Co umím přečíst na tomhle počítači",
    "new.cap_note": "Údaje, které najdu, ti vždy nejdřív ukážu ke kontrole. Co přečíst neumím, zadáš ručně.",
    "new.err_nofile": "Nejdřív vyber soubor.",
    "cap.docx": "Word (DOCX), ODT a textové soubory", "cap.pdf": "PDF s textem",
    "cap.ocr": "Fotky a skeny (OCR)", "cap.ocrpdf": "Skenovaná PDF (OCR)",
    "cap.need_pdf": "chybí pdftotext (nebo knihovna pypdf)",
    "cap.need_tess": "chybí Tesseract", "cap.need_tesspdf": "chybí Tesseract nebo pdftoppm",
    "cap.lang_missing": "Tesseract nemá jazykový balíček „{tess}“, takže rozpoznávání bude horší.",
    "review.title": "Zkontroluj údaje",
    "review.file": "Soubor {name} se uloží k dokumentu.",
    "review.found": "Konec platnosti: {date} (jistota: {conf}; {reason}).",
    "review.none": "V dokumentu jsem žádné datum konce platnosti nenašel. Doplň ho ručně.",
    "review.check_date": "Datum si prosím zkontroluj podle dokumentu.",
    "review.others": "Jiná nalezená data – kliknutím je použiješ:",
    "review.text_summary": "Text, který jsem v dokumentu přečetl",
    "review.fix": "Něco je potřeba opravit:",
    "cand.month_end": "(konec měsíce)",
    "form.title": "Název", "form.category": "Kategorie", "form.expires": "Konec platnosti",
    "form.expires_hint": "(prázdné = nevyprší)", "form.remind": "Upozornit předem",
    "form.remind_hint": "(dny, oddělené čárkou)", "form.note": "Poznámka",
    "form.save": "Uložit", "form.save_changes": "Uložit změny",
    "detail.no_end": "Bez konce platnosti", "detail.data": "Údaje",
    "detail.ics": "Přidat do kalendáře (.ics)", "detail.text": "Přečtený text dokumentu",
    "renew.title": "Prodlouženo?",
    "renew.help": "Když jsi dokument obnovil, posuň konec platnosti. Upozornění se pak začnou počítat znovu.",
    "renew.y1": "+ 1 rok", "renew.y2": "+ 2 roky", "renew.exact": "Nebo nový konec přesně",
    "renew.set": "Nastavit datum",
    "files.title": "Soubory", "files.none": "Zatím žádný soubor.", "files.add": "Přidat další soubor",
    "files.upload": "Nahrát", "files.open": "Otevřít", "files.download": "Stáhnout",
    "files.delete": "Smazat", "files.confirm": "Smazat tenhle soubor?", "files.preview": "Náhled: {name}",
    "del.title": "Smazání", "del.help": "Smaže dokument i všechny jeho soubory.",
    "del.btn": "Smazat dokument",
    "del.confirm": "Opravdu smazat celý dokument včetně souborů? Nejde to vrátit.",
    "flash.saved": "Uloženo.", "flash.created": "Dokument je přidaný.", "flash.deleted": "Dokument je smazaný.",
    "flash.renewed": "Konec platnosti je změněn.", "flash.uploaded": "Soubor je přidaný.",
    "flash.filedeleted": "Soubor je smazaný.", "flash.settings": "Nastavení je uloženo.",
    "http.title.403": "Zamítnuto", "http.title.404": "Nenalezeno", "http.title.413": "Moc velký soubor",
    "http.title.default": "Chyba",
    "http.bad_host": "Neplatná adresa. Otevři aplikaci přes adresu, kterou vypsala při spuštění.",
    "http.cross_site": "Požadavek přišel z cizí stránky, a proto ho nezpracuji.",
    "http.stale": "Stránka je zastaralá (aplikace se mezitím restartovala). "
                  "Vrať se zpět, načti ji znovu a zkus to ještě jednou.",
    "http.not_found": "Tahle stránka neexistuje.", "http.no_length": "Chybí délka požadavku.",
    "http.bad_request": "Neplatný požadavek.", "http.too_big": "Soubor je moc velký (nejvýš 40 MB).",
    "http.unsupported": "Nepodporovaný způsob odeslání.", "http.form_unreadable": "Formulář se nepodařilo přečíst.",
    "http.server_error": "Něco se pokazilo. Podrobnosti jsou v okně, kde program běží.",
    "http.bad_action": "Neznámá akce.", "http.no_file": "Takový soubor neexistuje.",
    "http.file_missing": "Soubor chybí na disku.",
    "http.no_doc": "Takový dokument neexistuje (možná je smazaný).",
    "http.back": "Zpět na přehled",
    "export.title": "Export a záloha",
    "export.cal_title": "Kalendář (připomínky v telefonu)",
    "export.cal_text": "Stáhni soubor s termíny a otevři ho v kalendáři, který používáš (Google Kalendář, Apple "
                       "Kalendář, Outlook…). Každý dokument se objeví jako celodenní událost v den konce platnosti "
                       "a kalendář ti ráno v 9:00 pošle upozornění v předstihu, který jsi u dokumentu nastavil.",
    "export.cal_note": "Je to jednorázový export. Po změnách ho stáhni znovu – kalendáře většinou existující "
                       "události aktualizují, ne duplikují (u některých programů je lepší staré události před "
                       "novým importem smazat).",
    "export.cal_btn": "Stáhnout kalendář (.ics)",
    "export.desk_title": "Upozornění na ploše",
    "export.desk_text": "Aplikace umí sama každý den zkontrolovat termíny a ukázat oznámení na ploše, když se "
                        "něco blíží – i když zrovna není otevřená.",
    "export.bk_title": "Záloha",
    "export.bk_text": "Zálohový soubor obsahuje databázi i všechny nahrané dokumenty. Ukládej ho mimo tenhle počítač "
                      "(disk, cloud). Obnova: zavři aplikaci a v terminálu spusť:",
    "export.bk_btn": "Stáhnout zálohu (.zip)",
    "set.title": "Nastavení", "set.lang": "Jazyk", "set.date_order": "Číselná data jako 03/04/2027",
    "set.mdy": "Nejdřív měsíc – 03/04/2027 je 4. března (USA)",
    "set.dmy": "Nejdřív den – 03/04/2027 je 3. dubna (Evropa a většina světa)",
    "set.date_help": "Použije se jen tehdy, když jde datum v dokumentu přečíst dvěma způsoby. Program ti vždy "
                     "ukáže, jak datum pochopil, v jednoznačném tvaru, ať ho můžeš zkontrolovat.",
    "set.save": "Uložit nastavení",
    "note.scan_no_tools": "PDF vypadá jako sken (bez textu). Na čtení skenů je potřeba Tesseract a pdftoppm – "
                          "viz README. Datum zadej ručně.",
    "note.photo_no_tool": "Na čtení fotek je potřeba Tesseract – viz README. Datum zadej ručně.",
    "note.unsupported": "Tenhle typ souboru neumím přečíst automaticky. Údaje zadej ručně, "
                        "soubor se ale uloží.",
    "note.read_failed": "Soubor se nepodařilo přečíst ({type}). Údaje zadej ručně.",
    "note.ocr_timeout": "Rozpoznávání textu trvalo příliš dlouho a bylo přerušeno.",
    "note.ocr_failed": "Tesseract se nepodařilo spustit.",
    "note.pdftotext_failed": "pdftotext selhal, zkouším jiný způsob.",
    "note.pdf_unreadable": "PDF se nepodařilo přečíst jako text.",
    "note.ocr_lang_missing": "Tesseract nemá jazykový balíček „{tess}“, takže rozpoznávání bude méně přesné. "
                             "Čísla a data to většinou nevadí – přesto datum zkontroluj.",
    "note.pdf_convert_failed": "Převod stránek PDF na obrázek selhal.",
    "note.ambiguous_date": "„{raw}“ jde přečíst dvěma způsoby: {used} nebo {other}. Použil jsem {used} "
                           "(výchozí pořadí změníš v Nastavení).",
    "reason.label": "před datem stojí „{text}“", "reason.interval": "konec intervalu „od … do …“",
    "reason.warranty": "datum nákupu {from_} + {months} měsíců záruky",
    "reason.warranty_guess": "datum nákupu {from_} + {months} měsíců záruky "
                             "(předpokládám, že jde o datum nákupu)",
    "reason.best_guess": "nejpravděpodobnější z nalezených dat", "reason.nothing_better": "nic lepšího jsem nenašel",
    "conf.high": "vysoká", "conf.medium": "střední", "conf.low": "nízká", "conf.none": "žádná",
    "cat.insurance": "Pojištění", "cat.vehicle": "STK / emise / registrace vozidla",
    "cat.inspection": "Revize / kontrola", "cat.warranty": "Záruka",
    "cat.contract": "Smlouva / nájem / předplatné", "cat.id": "Osobní / cestovní doklad",
    "cat.license": "Osvědčení / školení", "cat.medical": "Zdravotní",
    "cat.invoice": "Faktura / splatnost", "cat.other": "Ostatní", "cat.generic_title": "Dokument",
    "err.title_required": "Vyplň název dokumentu.",
    "err.title_long": "Název je moc dlouhý (nejvýš 200 znaků).",
    "err.bad_category": "Neznámá kategorie.",
    "err.note_long": "Poznámka je moc dlouhá (nejvýš 5000 znaků).",
    "err.bad_date": "Datum zadej ve tvaru 31. 12. 2026 (nebo 2026-12-31).",
    "err.remind_format": "Připomínky zadej jako počty dnů před koncem, např. 60, 30, 14, 7.",
    "err.remind_max": "Připomínka může být nejvýš 3650 dní předem.",
    "err.remind_count": "Připomínek může být nejvýš 12.",
    "err.file_type": "Tenhle typ souboru nepodporuji. Povolené: PDF, fotky (JPG, PNG, TIFF…), "
                     "Word (DOCX), textové a tabulkové soubory.",
    "err.file_empty": "Soubor je prázdný.", "err.file_big": "Soubor je moc velký (nejvýš 40 MB).",
    "err.upload_gone": "Nahraný soubor už není k dispozici, nahraj ho prosím znovu.",
    "err.restore_nodb": "V záloze chybí databáze – není to záloha aplikace {app}.",
    "err.restore_unexpected": "Záloha obsahuje nečekanou položku „{name}“, obnovu ruším.",
    "err.restore_big": "Záloha je neobvykle velká.",
    "err.restore_struct": "Databáze v záloze nemá očekávanou strukturu.",
    "err.restore_notzip": "Tohle není platný zip soubor se zálohou.",
    "err.restore_corrupt": "Databáze v záloze je poškozená, obnovu ruším.",
    "ics.summary": "Konec platnosti: {title}", "ics.category": "Kategorie: {cat}",
    "ics.alarm": "{title} – konec platnosti {when} ({date})",
    "item.expired": "{title} – prošlo {when} ({date})",
    "item.today": "{title} – vyprší dnes ({date})",
    "item.expires": "{title} – vyprší {when} ({date})",
    "cli.title": "{app} – {date} ({docs})",
    "cli.docs": ("{n} dokument", "{n} dokumenty", "{n} dokumentů"),
    "cli.g.expired": "PROŠLO", "cli.g.soon": "BRZY", "cli.g.ok": "V POŘÁDKU", "cli.g.none": "BEZ KONCE PLATNOSTI",
    "cli.more": "{label}: {n} (zobrazíš přes --all)",
    "cli.empty": "Zatím nejsou uložené žádné dokumenty. Spusť program bez příkazu a přidej první.",
    "cli.nothing_due": "Nic se neblíží, není o čem upozorňovat.",
    "cli.dry_run": "(zkušební běh – nic se neoznámilo ani neoznačilo)",
    "cli.test_ok": "Oznámení odesláno.",
    "cli.test_fail": "Oznámení na ploše tady nejdou zobrazit (viz README).",
    "cli.test_text": "Zkouška oznámení – tohle vidíš, takže to funguje.",
    "cli.notify_title": ("{app}: {n} termín", "{app}: {n} termíny", "{app}: {n} termínů"),
    "cli.notify_more": "… a další ({n})",
    "cli.notify_unavailable": "Oznámení na ploše tady nejdou zobrazit, výpis nahoře ti musí stačit. Termíny zůstanou "
                              "označené jako neoznámené a vypíšou se znovu při příštím spuštění.",
    "cli.exported": "Kalendář uložen: {path}",
    "cli.backup": "Záloha uložena: {path} ({kb} kB)",
    "cli.no_file": "Soubor {path} neexistuje.",
    "cli.restore_warn1": "Obnova nahradí všechna současná data daty ze zálohy. Současná data se nesmažou, "
                         "přesunou se vedle do složky s příponou „-before-restore-…“.",
    "cli.restore_warn2": "Nejdřív ukonči běžící {app} (jinak může být databáze zamčená). "
                         "Pak spusť příkaz znovu s přepínačem --yes.",
    "cli.restored": "Obnoveno. Předchozí data jsou ve složce:",
    "cli.a.method": "Způsob čtení:", "cli.a.title": "Název (návrh):", "cli.a.category": "Kategorie:",
    "cli.a.expires": "Konec platnosti:", "cli.a.none": "nenalezeno", "cli.a.cand": "kandidát",
    "cli.a.note": "Poznámka:", "cli.a.conf": "jistota",
    "srv.running": "{app} běží na {url}", "srv.data": "Data: {path}",
    "srv.stop": "Ukončíš ho klávesami Ctrl+C (nebo zavřením tohoto okna).", "srv.bye": "Končím.",
    "cli.error": "Chyba: {msg}",
    # --- přidáno ve verzi 1.2 ---
    "ov.tags_label": "Štítky",
    "ov.archive_link": ("Archiv ({n} dokument)", "Archiv ({n} dokumenty)", "Archiv ({n} dokumentů)"),
    "ov.archive_title": "Archiv", "ov.archive_back": "← Zpět na aktivní dokumenty",
    "ov.archive_empty": "Archiv je prázdný.",
    "arch.title": "Archiv",
    "arch.help": "Archivované dokumenty si nechají soubory, ale nezobrazují se v přehledu, neposílají upozornění "
                 "a nejsou v exportu do kalendáře. Hodí se pro věci, které už nepotřebuješ (prodané auto, zrušená smlouva).",
    "arch.btn": "Přesunout do archivu", "arch.restore_btn": "Vrátit z archivu",
    "arch.banner": "Dokument je v archivu: neposílá upozornění a neexportuje se do kalendáře.",
    "recur.none": "Neopakuje se",
    "recur.months": ("každý měsíc", "každé {n} měsíce", "každých {n} měsíců"),
    "recur.years": ("každý rok", "každé {n} roky", "každých {n} let"),
    "form.recur": "Opakuje se", "form.recur_hint": "(pro prodloužení jedním klikem)",
    "form.tags": "Štítky", "form.tags_hint": "(oddělené čárkou, např. auto, Jana)",
    "renew.recur": "Prodloužit o další období ({every})",
    "sched.on": "Automatická upozornění jsou zapnutá.", "sched.off": "Automatická upozornění jsou vypnutá.",
    "sched.how.windows": "Plánovač úloh Windows zkontroluje termíny každý den v 9:00 a po přihlášení "
                         "(když byl počítač v 9:00 vypnutý, udělá to hned, jak to půjde).",
    "sched.how.mac": "macOS zkontroluje termíny každý den v 9:00 a po přihlášení.",
    "sched.how.linux": "Kontrola proběhne při každém přihlášení do plochy.",
    "sched.enable": "Zapnout automatická upozornění", "sched.disable": "Vypnout automatická upozornění",
    "sched.test": "Poslat zkušební oznámení",
    "sched.unsupported": "Na tomhle systému nejde upozornění naplánovat automaticky. Spouštěj příkaz níže "
                         "pravidelně sám (viz README.md).",
    "sched.manual": "Příkaz pro ruční spuštění kontroly",
    "set.cat_title": "Vlastní kategorie",
    "set.cat_help": "Přidej kategorie, které vestavěné nepokrývají. Když nějakou smažeš, její dokumenty se "
                    "přesunou do „Ostatní“.",
    "set.cat_none": "Zatím žádné vlastní kategorie.", "set.cat_label": "Název nové kategorie",
    "set.cat_remind": "Výchozí upozornění (dny předem)", "set.cat_add": "Přidat kategorii",
    "set.cat_delete": "Smazat", "set.cat_confirm": "Smazat tuhle kategorii? Její dokumenty se přesunou do „Ostatní“.",
    "set.cat_used": ("používá ji {n} dokument", "používají ji {n} dokumenty", "používá ji {n} dokumentů"),
    "set.ab_title": "Automatická záloha",
    "set.ab_help": "Aplikace bude pravidelně ukládat zálohu (databázi i všechny soubory) do složky, kterou zvolíš – "
                   "nejlépe synchronizované do cloudu nebo na jiném disku – a nechá si jen ty nejnovější. Záloha se "
                   "dělá, když aplikace běží, a při denní kontrole upozornění.",
    "set.ab_suggest": "Návrh: {path}",
    "set.ab_dir": "Složka pro zálohy", "set.ab_dir_hint": "(prázdné = vypnuto)",
    "set.ab_days": "Zálohovat každých … dní", "set.ab_keep": "Kolik záloh nechat",
    "set.ab_save": "Uložit nastavení zálohy", "set.ab_now": "Zálohovat teď",
    "set.ab_off": "Automatická záloha je vypnutá.", "set.ab_never": "Zatím neproběhla žádná automatická záloha.",
    "set.ab_last": "Poslední automatická záloha: {when}", "set.ab_error": "Poslední pokus se nepovedl: {msg}",
    "flash.archived": "Přesunuto do archivu.", "flash.unarchived": "Vráceno z archivu.",
    "flash.cat_added": "Kategorie je přidaná.", "flash.cat_deleted": "Kategorie je smazaná.",
    "flash.ab_saved": "Nastavení zálohy je uloženo.", "flash.ab_done": "Záloha je uložená.",
    "flash.sched_on": "Automatická upozornění jsou zapnutá.", "flash.sched_off": "Automatická upozornění jsou vypnutá.",
    "flash.test_sent": "Zkušební oznámení odesláno. Vidíš ho?",
    "err.tag_long": "Štítek může mít nejvýš {n} znaků.", "err.tag_count": "Štítků může být nejvýš {n}.",
    "err.bad_recur": "Vyber, jak často se termín opakuje.",
    "err.no_recur": "Tenhle dokument se neopakuje. Nejdřív nastav „Opakuje se“.",
    "err.cat_label_required": "Vyplň název kategorie.",
    "err.cat_label_long": "Název kategorie je moc dlouhý (nejvýš 60 znaků).",
    "err.cat_exists": "Kategorie s tímhle názvem už existuje.",
    "err.ab_relative": "Zadej celou cestu ke složce (např. D:\\Zalohy nebo /home/ja/zalohy).",
    "err.ab_inside": "Složka pro zálohy nemůže být uvnitř datové složky aplikace.",
    "err.ab_numbers": "Zálohovat jde každých 1 až 365 dní a nechat si 1 až 100 záloh.",
    "err.ab_failed": "Záloha se nepovedla: {msg}",
    "err.sched_failed": "Automatická upozornění se nepodařilo nastavit: {msg}",
    "srv.already": "{app} už běží na {url} – otevírám ho v prohlížeči.",
    "cli.ab_done": "Automatická záloha uložena: {path}",
    "cli.sched_removed": "Automatická upozornění jsou vypnutá.",
    "cli.sched_test": "Vyzkoušej to hned: watchdog.py notify --test",
}

STRINGS = {"en": EN, "cs": CS}


def plural_index(lang: str, n: int) -> int:
    if lang == "cs":
        return 0 if n == 1 else 1 if 2 <= n <= 4 else 2
    return 0 if n == 1 else 1


def raw(lang: str, key: str, /) -> str:
    """The untouched template (placeholders not filled in) for callers that insert escaped HTML themselves."""
    entry = STRINGS.get(lang, EN).get(key)
    if entry is None:
        entry = EN.get(key, key)
    return entry[0] if isinstance(entry, tuple) else entry


def t(lang: str, key: str, /, **kw) -> str:
    kw.setdefault("app", APP_NAME)
    return raw(lang, key).format(**kw)


def tn(lang: str, key: str, n: int, /, **kw) -> str:
    entry = STRINGS.get(lang, EN).get(key)
    if entry is None:
        entry = EN.get(key, key)
    if not isinstance(entry, tuple):
        entry = (entry,)
    kw.setdefault("app", APP_NAME)
    return entry[min(plural_index(lang, n), len(entry) - 1)].format(n=n, **kw)


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------
def _as_date(value) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(value)


def fmt_date(value, lang: str = "en") -> str:
    """Always unambiguous: 'Mar 4, 2027' (English) or '4. 3. 2027' (Czech)."""
    d = _as_date(value)
    if lang == "cs":
        return f"{d.day}. {d.month}. {d.year}"
    return f"{MONTHS_EN[d.month - 1]} {d.day}, {d.year}"


def days_phrase(lang: str, d: Optional[int]) -> str:
    if d is None:
        return "bez termínu" if lang == "cs" else "no deadline"
    if lang == "cs":
        if d == 0:
            return "dnes"
        if d == 1:
            return "zítra"
        if d == -1:
            return "včera"
        n = abs(d)
        if n >= 100:
            months = round(n / 30.44)
            if months >= 24:
                years = round(months / 12)
                if d > 0:
                    return "za %d %s" % (years, ("rok", "roky", "let")[plural_index("cs", years)])
                return "před rokem" if years == 1 else "před %d lety" % years
            if d > 0:
                return "za %d %s" % (months, ("měsíc", "měsíce", "měsíců")[plural_index("cs", months)])
            return "před měsícem" if months == 1 else "před %d měsíci" % months
        if d > 0:
            return "za %d %s" % (n, ("den", "dny", "dní")[plural_index("cs", n)])
        return "před %d dny" % n
    if d == 0:
        return "today"
    if d == 1:
        return "tomorrow"
    if d == -1:
        return "yesterday"
    n = abs(d)
    if n >= 100:
        months = round(n / 30.44)
        if months >= 24:
            years = round(months / 12)
            return "in %d years" % years if d > 0 else "%d years ago" % years
        return "in %d months" % months if d > 0 else "%d months ago" % months
    return "in %d days" % n if d > 0 else "%d days ago" % n


# --------------------------------------------------------------------------
# Turning the reader's neutral codes into text
# --------------------------------------------------------------------------
def category_label(lang: str, key: str) -> str:
    return t(lang, "cat." + key)


def conf_label(lang: str, level: str) -> str:
    return t(lang, "conf." + level)


def status_label(lang: str, status: dict) -> str:
    key = status["key"]
    if key == "soon" and status.get("days") == 0:
        return t(lang, "status.today")
    return t(lang, "status." + key)


def reason_text(lang: str, reason: Optional[dict]) -> str:
    if not reason:
        return ""
    code = reason["code"]
    if code == "label":
        return t(lang, "reason.label", text=reason["text"])
    if code == "warranty":
        key = "reason.warranty" if reason.get("sure", True) else "reason.warranty_guess"
        return t(lang, key, from_=fmt_date(reason["from"], lang), months=reason["months"])
    return t(lang, "reason." + code)


def note_text(lang: str, note: dict) -> str:
    code = note["code"]
    if code == "ambiguous_date":
        return t(lang, "note.ambiguous_date", raw=note["raw"],
                 used=fmt_date(note["used"], lang), other=fmt_date(note["other"], lang))
    params = {k: v for k, v in note.items() if k != "code"}
    return t(lang, "note." + code, **params)


def item_line(lang: str, title: str, expires: str, days: int) -> str:
    date = fmt_date(expires, lang)
    if days < 0:
        return t(lang, "item.expired", title=title, when=days_phrase(lang, days), date=date)
    if days == 0:
        return t(lang, "item.today", title=title, date=date)
    return t(lang, "item.expires", title=title, when=days_phrase(lang, days), date=date)
