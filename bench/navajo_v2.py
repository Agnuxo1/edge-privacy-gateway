"""NAVAJO-v2 detector: clinical-context layer on top of navajo_egp v1.

Pure Python + regex, no model weights, runs on any CPU. Developed only on the
Nemotron-PII *train* health subset; the test subset is scored once.

Layers
  1. v1 high-precision patterns (email, phone, SSN, card, IP, URL, MRN, ISO dates)
  2. key-value fields: an identifier label followed by its value
  3. shape rules: mixed alphanumeric IDs, UUID/hex, MAC, coordinates, dates/times
  4. names: lexicon (built from train gold spans, see build_lexicon) + titles/fields
"""
from __future__ import annotations

import json
import re
import sys

import os
sys.path.insert(0, os.environ.get("NAVAJO_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vendor")))
from navajo_egp.entities import _PATTERNS, EntityType  # noqa: E402

# v1 patterns kept, minus the over-broad postcode/address/passport ones that
# fire on clinical numbers; v2 re-adds addresses with a stricter rule.
_V1_KEEP = {EntityType.EMAIL, EntityType.PHONE, EntityType.SSN, EntityType.CARD_NUMBER,
            EntityType.IP_ADDRESS, EntityType.URL, EntityType.MRN, EntityType.DATE_OF_BIRTH,
            EntityType.IBAN, EntityType.NATIONAL_ID}
V1 = [p for t, p in _PATTERNS if t in _V1_KEEP]

SEP = r"(?:\*\*)?\s*(?:[:#|=\-–]|is|of|number|no\.?|was|as|such as|like)?\s*(?:\*\*)?\s*(?:[:#|]\s*)?"
ID_LABELS = (
    r"medical record (?:number|no\.?|#)|mrn|patient id|record (?:number|id)|chart (?:number|no\.?)|"
    r"health plan (?:beneficiary )?(?:number|id)|beneficiary (?:number|id)|member (?:id|number)|"
    r"insurance (?:id|number)|policy (?:number|id)|subscriber id|"
    r"employee (?:id|number)|staff id|badge (?:id|number)|"
    r"(?:certificate )?licen[cs]e (?:number|no\.?|#)|certificate (?:number|no\.?)|npi|dea (?:number|no\.?)|"
    r"biometric (?:identifier|id)|unique (?:id|identifier)|device (?:id|identifier|serial)|serial (?:number|no\.?)|"
    r"customer (?:id|number)|account (?:number|no\.?|id)|routing number|tax id|ein|"
    r"national id|ssn|social security number|passport (?:number|no\.?)|"
    r"user ?name|login|handle|license plate(?: number)?|vin|vehicle (?:id|identification number)|"
    r"pin|cvv|password|api key"
)
KV = re.compile(r"(?i)\b(?:" + ID_LABELS + r")\b" + SEP + r"([A-Za-z0-9][A-Za-z0-9._@\-/]{2,63})")

# Mixed IDs: >= 3 digits plus a letter or a dash/dot group; excludes measurements.
MIXED = re.compile(r"\b(?=[A-Za-z0-9\-]*\d[A-Za-z0-9\-]*\d[A-Za-z0-9\-]*\d)(?=[A-Za-z0-9\-]*[A-Za-z\-])"
                   r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+\b|\b(?=\w*\d{3})(?=\w*[A-Z])[A-Z0-9]{6,}\b")
HEX = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{16,}\b", re.I)
MAC = re.compile(r"\b(?:[0-9A-F]{2}[:-]){5}[0-9A-F]{2}\b", re.I)
COORD = re.compile(r"\(?\s*(?:Latitude:\s*)?-?\d{1,3}\.\d{3,}\s*°?\s*[NS]?\s*[, ]\s*(?:Longitude:\s*)?-?\d{1,3}\.\d{3,}\s*°?\s*[EW]?\s*\)?")
LONGNUM = re.compile(r"(?<![\d.])\d{6,}(?![\d.])")
MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
DATES = [
    re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?\b"),
    re.compile(r"\b\d{1,2}[/.\-]\d{1,2}[/.\-](?:19|20)?\d{2}\b(?:\s+(?:at\s+)?\d{1,2}:\d{2}(?::\d{2})?\s*(?:[AP]\.?M\.?)?)?", re.I),
    re.compile(r"\b(?:19|20)\d{2}/\d{1,2}/\d{1,2}\b"),
    re.compile(r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?" + MONTH + r",?\s+(?:19|20)\d{2}\b", re.I),
    re.compile(r"\b" + MONTH + r"\s+\d{1,2}(?:st|nd|rd|th)?,?\s+(?:19|20)\d{2}\b", re.I),
]
STREET = re.compile(r"\b\d{1,6}\s+(?:[NSEW]\.?\s+)?(?:[A-Z0-9][a-zA-Z0-9]*\.?\s+){0,4}"
                    r"(?:St|Street|Ave|Avenue|Rd|Road|Ln|Lane|Dr|Drive|Blvd|Boulevard|Ct|Court|Cir|Circle|"
                    r"Way|Pl|Place|Pkwy|Parkway|Ter|Terrace|Trl|Trail|Hwy|Highway|Sq|Loop|Run|Pass|Path|Row|View Road)\b\.?"
                    r"|\b\d{1,6}\s+[NSEW]\s+\d{1,6}\s+[NSEW]\b")
ZIP = re.compile(r"(?i)(?:\b[A-Z]{2}\s+|zip(?: code)?:?\s*|postal code:?\s*|postcode:?\s*)(\d{5}(?:-\d{4})?)\b")
NAME_FIELD = re.compile(r"(?i)\b(?:first name|last name|surname|given name|full name|patient name|name|"
                        r"recipient name|contact|physician|attending|nurse|caregiver)\b" + SEP +
                        r"((?-i:[A-Z][a-zA-Z'\-]+)(?:\s+(?-i:[A-Z][a-zA-Z'\-]+)){0,2})")
TITLE = re.compile(r"\b(?:Dr|Mr|Mrs|Ms|Miss|Prof|Nurse)\.?\s+((?:[A-Z][a-zA-Z'\-]+\s?){1,3})")
CITY_FIELD = re.compile(r"(?i)\b(?:city|town|location|lives in|resides in|located in)\b" + SEP +
                        r"((?-i:[A-Z][a-zA-Z]+)(?:\s(?-i:[A-Z][a-zA-Z]+)){0,2})")
CAPWORD = re.compile(r"\b[A-Z][a-zA-Z'\-]{1,}\b")

PHONE_INTL = re.compile(r"\+\d{1,3}(?:[\s\-.]?\(?\d{1,4}\)?){2,5}\d")
COUNTY = re.compile(r"(?:[A-Z][a-z]+\s){1,2}(?:County|Parish|Borough)")
CITY_AFTER = re.compile(r"(?:St|Street|Ave|Avenue|Rd|Road|Ln|Lane|Dr|Drive|Blvd|Ct|Cir|Way|Pl|Place|\d)\.?,\s*"
                        r"([A-Z][a-z]+(?:\s[A-Z][a-z]+){0,2}),\s*(?:[A-Z]{2}|USA|[A-Z][a-z]+)")
TLD = {"com", "org", "net", "edu", "gov", "io", "dk", "ru", "de", "uk", "fr", "es", "it", "nl", "ca", "au", "in",
       "jp", "cn", "br", "mx", "ch", "se", "no", "fi", "pl", "be", "at", "co", "us", "info", "biz", "health", "txt",
       "pdf", "csv", "json", "xml", "html", "py", "doc", "docx", "xlsx", "png", "jpg"}
HANDLE = re.compile(r"(?<![@\w.])([a-z][a-z0-9]*[._][a-z][a-z0-9]*|[a-z]+_[a-z0-9_]+|[a-z]{2,}\d{2,4})(?![\w@]|\.\w)")
RANGE = re.compile(r"^\d{1,3}(?:\.\d+)?-\d{1,3}(?:\.\d+)?$")
NEXTCAP = re.compile(r"\s+([A-Z][a-zA-Z'\-]+)")
UNITS = re.compile(r"(?i)^\d+(?:mg|mcg|ml|kg|g|mmhg|bpm|iu|units?|mmol|dl|cm|mm|hrs?|h|min|s|x)$")


STOP = {"The", "This", "Patient", "Medical", "Record", "Number", "Date", "Blood", "Type", "Health", "Plan",
        "Employee", "County", "Street", "Road", "Hospital", "Clinic", "Center", "Pharma", "Pharmaceuticals",
        "Inc", "LLC", "Ltd", "Corp", "Group", "University", "Department", "Unit", "ID", "MRN", "Email", "Phone"}


class NavajoV2:
    def __init__(self, lexicon_path=None, use_v1=True, use_kv=True, use_shape=True,
                 use_names=True, use_dates=True):
        self.lex = set()
        if lexicon_path:
            with open(lexicon_path, encoding="utf8") as f:
                self.lex = set(json.load(f))
        self.use_v1, self.use_kv, self.use_shape = use_v1, use_kv, use_shape
        self.use_names, self.use_dates = use_names, use_dates

    def detect(self, text):
        out = []
        add = out.append
        if self.use_v1:
            for p in V1:
                for m in p.finditer(text):
                    add(m.span())
        if self.use_kv:
            for m in KV.finditer(text):
                add(m.span(1))
            for m in ZIP.finditer(text):
                add(m.span(1))
        if self.use_shape:
            for p in (HEX, MAC, COORD, STREET):
                for m in p.finditer(text):
                    add(m.span())
            for m in PHONE_INTL.finditer(text):
                add(m.span())
            for m in HANDLE.finditer(text):
                g = m.group(1)
                if g.rsplit(".", 1)[-1] not in TLD and not g.isdigit():
                    add(m.span(1))
            for m in MIXED.finditer(text):
                if not UNITS.match(m.group()) and not RANGE.match(m.group()):
                    add(m.span())
            for m in LONGNUM.finditer(text):
                add(m.span())
        if self.use_dates:
            for p in DATES:
                for m in p.finditer(text):
                    add(m.span())
        if self.use_names:
            for m in COUNTY.finditer(text):
                add(m.span())
            for m in CITY_AFTER.finditer(text):
                add(m.span(1))
            for p in (NAME_FIELD, TITLE, CITY_FIELD):
                for m in p.finditer(text):
                    add(m.span(1))
            if self.lex:
                for m in CAPWORD.finditer(text):
                    if m.group() in self.lex:
                        add(m.span())
                        n = NEXTCAP.match(text, m.end())
                        if n and n.group(1) not in STOP:
                            add(n.span(1))
        return _merge(out)


def _merge(spans):
    spans = sorted(s for s in spans if s[1] > s[0])
    res = []
    for s, e in spans:
        if res and s <= res[-1][1]:
            res[-1] = (res[-1][0], max(res[-1][1], e))
        else:
            res.append((s, e))
    return res


NAME_LABELS = {"first_name", "last_name", "city", "county"}


def build_lexicon(train_jsonl, out_path, stop_path=None, min_count=1):
    """Name/place lexicon from train gold spans, minus words that appear in train
    more often outside PHI spans than inside (common words such as 'Patient')."""
    from collections import Counter
    inside, outside = Counter(), Counter()
    with open(train_jsonl, encoding="utf8") as f:
        for line in f:
            r = json.loads(line)
            t = r["text"]
            mask = bytearray(len(t))
            for g in r["spans"]:
                mask[g["start"]:g["end"]] = b"\x01" * (g["end"] - g["start"])
                if g["label"] in NAME_LABELS:
                    for w in CAPWORD.findall(t[g["start"]:g["end"]]):
                        inside[w] += 1
            for m in CAPWORD.finditer(t):
                if not any(mask[m.start():m.end()]):
                    outside[m.group()] += 1
    lex = sorted(w for w, c in inside.items() if c >= min_count and outside[w] <= c and len(w) > 2)
    with open(out_path, "w", encoding="utf8") as f:
        json.dump(lex, f)
    return len(lex)
