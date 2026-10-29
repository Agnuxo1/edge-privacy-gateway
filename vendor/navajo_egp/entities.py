"""
Entity type definitions and regex patterns for PII detection.

Supports:
  - Names (NER via spaCy if installed, fallback to capitalised-word heuristic)
  - Emails
  - Phone numbers (international E.164 + common national formats)
  - Spanish DNI / NIE / EU-style national IDs
  - US SSN
  - UK NIN
  - IBAN (international bank account)
  - Credit/debit card numbers (Luhn pattern)
  - Dates of birth (ISO, European, US)
  - Physical addresses (street/avenue/postal patterns)
  - Medical record numbers (MRN)
  - IP addresses (v4 and v6)
  - URLs (to avoid leaking internal endpoints)
  - Passport numbers
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class EntityType(str, Enum):
    PERSON_NAME = "PERSON_NAME"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    NATIONAL_ID = "NATIONAL_ID"       # DNI, NIE, SSN, NIN, passport
    SSN = "SSN"                        # US Social Security Number
    PASSPORT = "PASSPORT"
    IBAN = "IBAN"
    CARD_NUMBER = "CARD_NUMBER"        # Credit/debit card (Luhn pattern)
    DATE_OF_BIRTH = "DATE_OF_BIRTH"
    ADDRESS = "ADDRESS"
    MRN = "MRN"                        # Medical record number
    IP_ADDRESS = "IP_ADDRESS"
    URL = "URL"


@dataclass
class DetectedEntity:
    text: str
    entity_type: EntityType
    start: int
    end: int
    placeholder: str = ""
    confidence: float = 1.0


# ---------------------------------------------------------------------------
# Compiled regex patterns — order matters (more specific before more generic)
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[EntityType, re.Pattern]] = []


def _add(entity_type: EntityType, pattern: str, flags: int = re.IGNORECASE) -> None:
    _PATTERNS.append((entity_type, re.compile(pattern, flags)))


# ---- Financial ----
# IBAN: up to 34 alphanum chars, optional spaces every 4
_add(EntityType.IBAN,
     r'\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){4,7}(?:[ ]?[A-Z0-9]{1,4})?\b',
     re.ASCII | re.IGNORECASE)

# Visa/Mastercard/Amex (simple Luhn-ish pattern: 13-19 digits, optional separators)
_add(EntityType.CARD_NUMBER,
     r'\b(?:\d[ -]?){13,19}\b')

# ---- National IDs ----
# Spanish DNI (8 digits + letter)
_add(EntityType.NATIONAL_ID, r'\b\d{8}[A-HJ-NP-TV-Z]\b')
# Spanish NIE (X/Y/Z + 7 digits + letter)
_add(EntityType.NATIONAL_ID, r'\b[XYZ]\d{7}[A-HJ-NP-TV-Z]\b')
# US SSN
_add(EntityType.SSN, r'\b\d{3}[-\s]\d{2}[-\s]\d{4}\b')
# UK NIN (e.g. AB 12 34 56 C)
_add(EntityType.NATIONAL_ID,
     r'\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b')
# Passport number (generic: 1-2 letters + 6-9 digits)
_add(EntityType.PASSPORT, r'\b[A-Z]{1,2}\d{6,9}\b')

# ---- Dates ----
# ISO: 1900-2099
_add(EntityType.DATE_OF_BIRTH,
     r'\b(19|20)\d{2}[-/\.](0[1-9]|1[0-2])[-/\.](0[1-9]|[12]\d|3[01])\b')
# DD/MM/YYYY or MM/DD/YYYY
_add(EntityType.DATE_OF_BIRTH,
     r'\b(0[1-9]|[12]\d|3[01])[/\-\.](0[1-9]|1[0-2])[/\-\.](19|20)\d{2}\b')

# ---- Contact ----
# Email
_add(EntityType.EMAIL,
     r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b')

# Phone: international (+XX) and local (various separators)
_add(EntityType.PHONE,
     r'(?:\+?\d{1,3}[\s\-\.]?)?\(?\d{2,4}\)?[\s\-\.]?\d{3,4}[\s\-\.]?\d{3,4}')

# ---- URLs ----
_add(EntityType.URL,
     r'https?://[^\s<>"\']+|www\.[^\s<>"\']+')

# ---- IP addresses ----
# IPv4
_add(EntityType.IP_ADDRESS,
     r'\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b')
# IPv6 (simplified)
_add(EntityType.IP_ADDRESS,
     r'\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b')

# ---- Address hints ----
# Matches "Calle X", "Av. Y", "C/ Z nº 12", street-number combos
_add(EntityType.ADDRESS,
     r'\b(?:calle|c\/|c\.|av\.|avda\.?|avenida|plaza|pza\.?|paseo|p\.?o\.?|'
     r'carretera|crta\.?|camino|ronda|glorieta|'
     r'street|st\.?|avenue|ave\.?|boulevard|blvd\.?|road|rd\.?|'
     r'lane|ln\.?|drive|dr\.?|court|ct\.?|place|pl\.?)'
     r'[\s]+[^\n,;]{2,60}',
     re.IGNORECASE)

# Postal codes (Spanish CP 5 digits; UK; US ZIP)
_add(EntityType.ADDRESS,
     r'\b(?:\d{5}(?:-\d{4})?|[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b')

# ---- Medical record numbers (generic: MRN + digits) ----
_add(EntityType.MRN,
     r'\bMR[N#]?\s*:?\s*\d{4,10}\b')

# ---- PERSON_NAME: capitalised first + last (basic heuristic) ----
# This is a broad fallback; spaCy NER (if available) takes priority.
# NO re.IGNORECASE — capitalisation is the key signal for names.
# Matches 2-4 capitalised words (First [Middle …] Last).
# Excludes common non-name words that appear capitalised in sentences.
_COMMON_NON_NAMES = {
    # English
    "The", "This", "That", "These", "Those", "There", "Their", "They",
    "Patient", "Doctor", "Nurse", "Mr", "Mrs", "Ms", "Dr", "Prof",
    "Dear", "Hello", "Hi", "Please", "Thank", "Thanks",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
    "Contact", "Email", "Phone", "Address", "Name", "Date", "Note",
    "Send", "Call", "Dear", "From", "Subject", "Regarding",
    # Spanish
    "El", "La", "Los", "Las", "Un", "Una", "De", "Del", "En", "Con",
    "Paciente", "Doctor", "Doctora", "Señor", "Señora",
    "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo",
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
}

_RAW_PERSON_PATTERN = re.compile(
    r'\b(?:[A-ZÁÉÍÓÚÜÑÀÂÊÎÔÛÇÆŒ][a-záéíóúüñàâêîôûçæœ\'-]+\s+){1,3}'
    r'[A-ZÁÉÍÓÚÜÑÀÂÊÎÔÛÇÆŒ][a-záéíóúüñàâêîôûçæœ\'-]+\b',
    0,  # case-sensitive
)
