"""
Core anonymisation / de-anonymisation logic.

Placeholder naming convention per entity type:
  PERSON_NAME   → ENTITY_A, ENTITY_B, …
  EMAIL         → EMAIL_1, EMAIL_2, …
  PHONE         → PHONE_1, …
  NATIONAL_ID   → ID_001, …
  SSN           → SSN_001, …
  PASSPORT      → PASSPORT_001, …
  IBAN          → ACCT_001, …
  CARD_NUMBER   → CARD_001, …
  DATE_OF_BIRTH → DOB_001, …
  ADDRESS       → ADDR_001, …
  MRN           → MRN_001, …
  IP_ADDRESS    → IP_001, …
  URL           → URL_001, …
"""

from __future__ import annotations

import re
import string

from navajo_egp.entities import EntityType, DetectedEntity
from navajo_egp.session import EGPSession


# Map entity type → placeholder prefix and counter format
_PREFIX: dict[EntityType, str] = {
    EntityType.PERSON_NAME: "ENTITY_",
    EntityType.EMAIL: "EMAIL_",
    EntityType.PHONE: "PHONE_",
    EntityType.NATIONAL_ID: "ID_",
    EntityType.SSN: "SSN_",
    EntityType.PASSPORT: "PASSPORT_",
    EntityType.IBAN: "ACCT_",
    EntityType.CARD_NUMBER: "CARD_",
    EntityType.DATE_OF_BIRTH: "DOB_",
    EntityType.ADDRESS: "ADDR_",
    EntityType.MRN: "MRN_",
    EntityType.IP_ADDRESS: "IP_",
    EntityType.URL: "URL_",
}

# Person names use letters (A, B, …, Z, AA, AB, …); others use zero-padded ints
_LETTERS = list(string.ascii_uppercase)


def _letter_id(n: int) -> str:
    """0→A, 1→B, …, 25→Z, 26→AA, 27→AB, …"""
    result = ""
    n += 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = _LETTERS[rem] + result
    return result


class Anonymizer:
    """
    Replaces detected PII entities with stable placeholders within a session.

    If the same original value appears multiple times, the same placeholder
    is reused (consistency across a document).
    """

    def __init__(self) -> None:
        # counters per entity type per session (reset when creating new session)
        self._counters: dict[EntityType, int] = {}

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def apply(
        self,
        text: str,
        entities: list[DetectedEntity],
        session: EGPSession,
    ) -> str:
        """
        Replace every detected entity in *text* with a placeholder.
        Mappings are stored in *session*.
        Returns the anonymised text.
        """
        if not entities:
            return text

        # Process in reverse order to preserve character offsets
        result = list(text)
        for ent in sorted(entities, key=lambda e: e.start, reverse=True):
            placeholder = self._get_or_create_placeholder(ent, session)
            result[ent.start:ent.end] = list(placeholder)

        anonymised = "".join(result)
        # Clean up double-spaces left by removed tokens
        anonymised = re.sub(r"[ \t]{2,}", " ", anonymised)
        anonymised = re.sub(r"(?<=[,;:])[ \t]+(?=[,;:])", "", anonymised)
        return anonymised.strip()

    def restore(self, text: str, session: EGPSession) -> str:
        """
        Reverse the anonymisation: replace every placeholder with its original.
        Works even if the LLM paraphrased the placeholder slightly by doing
        a case-insensitive lookup for each known placeholder.
        """
        restored = text
        # Sort by length descending to avoid partial replacements
        for placeholder, original in sorted(
            session.reverse.items(), key=lambda x: -len(x[0])
        ):
            if placeholder in restored:
                restored = restored.replace(placeholder, original)
            else:
                # Try case-insensitive (LLMs sometimes lowercase placeholders)
                pattern = re.compile(re.escape(placeholder), re.IGNORECASE)
                restored = pattern.sub(original, restored)
        return restored

    # ------------------------------------------------------------------ #
    # Internals                                                            #
    # ------------------------------------------------------------------ #

    def _get_or_create_placeholder(
        self, ent: DetectedEntity, session: EGPSession
    ) -> str:
        # If we've seen this exact original before, reuse the placeholder
        existing = session.get_placeholder(ent.text)
        if existing:
            return existing

        # Mint a new placeholder
        etype = ent.entity_type
        count = self._counters.get(etype, 0)
        self._counters[etype] = count + 1

        prefix = _PREFIX.get(etype, "PII_")
        if etype == EntityType.PERSON_NAME:
            suffix = _letter_id(count)
        else:
            suffix = str(count + 1).zfill(3)

        placeholder = f"{prefix}{suffix}"
        session.add(ent.text, placeholder)
        return placeholder

    def reset_counters(self) -> None:
        """Reset internal counters (call when starting a fresh session)."""
        self._counters.clear()
