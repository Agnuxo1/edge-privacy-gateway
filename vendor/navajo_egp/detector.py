"""
PII detector — two-tier approach:
  1. Regex patterns (always available, zero dependencies)
  2. spaCy NER (optional, activated if spaCy + a model are installed)

The detector returns a list of DetectedEntity objects sorted by start
position, with overlapping spans de-duplicated (longest span wins).
"""

from __future__ import annotations

import logging
import re
from typing import List

from navajo_egp.entities import (
    DetectedEntity,
    EntityType,
    _PATTERNS,
    _COMMON_NON_NAMES,
    _RAW_PERSON_PATTERN,
)

logger = logging.getLogger(__name__)

# Try to load spaCy lazily
_SPACY_NLP = None
_SPACY_AVAILABLE = False

_SPACY_MODELS = [
    "es_core_news_lg",
    "es_core_news_md",
    "es_core_news_sm",
    "en_core_web_lg",
    "en_core_web_md",
    "en_core_web_sm",
    "xx_ent_wiki_sm",
]


def _load_spacy() -> None:
    global _SPACY_NLP, _SPACY_AVAILABLE
    try:
        import spacy  # noqa: PLC0415
        for model_name in _SPACY_MODELS:
            try:
                _SPACY_NLP = spacy.load(model_name, disable=["parser", "tagger"])
                _SPACY_AVAILABLE = True
                logger.info("spaCy NER loaded: %s", model_name)
                return
            except OSError:
                continue
        logger.info("spaCy installed but no model found — using regex only.")
    except ImportError:
        logger.info("spaCy not installed — using regex-only NER.")


def _spacy_entities(text: str) -> list[DetectedEntity]:
    """Extract PERSON entities via spaCy."""
    if not _SPACY_AVAILABLE or _SPACY_NLP is None:
        return []
    doc = _SPACY_NLP(text)
    results = []
    for ent in doc.ents:
        if ent.label_ in {"PER", "PERSON"}:
            results.append(
                DetectedEntity(
                    text=ent.text,
                    entity_type=EntityType.PERSON_NAME,
                    start=ent.start_char,
                    end=ent.end_char,
                    confidence=0.90,
                )
            )
    return results


def _regex_name_entities(text: str, protected: list[tuple[int, int]]) -> list[DetectedEntity]:
    """
    Extract PERSON_NAME entities via the case-sensitive regex heuristic.

    Filters out:
    - Matches that overlap any protected zone (high-precision patterns).
    - Matches where EVERY word is a common non-name word.

    If the first word is a common non-name word (e.g., "Patient"), the match
    is trimmed: we re-apply the pattern to the remainder of the matched text
    to extract the actual name portion.
    """
    results = []
    seen_spans: set[tuple[int, int]] = set()

    def _try_add(matched: str, start: int, end: int) -> None:
        if (start, end) in seen_spans:
            return
        # Skip if overlaps a protected zone
        if any(not (end <= ps or start >= pe) for ps, pe in protected):
            return
        words = matched.split()
        # If ALL words are non-names, discard
        if all(w.rstrip(".,;:") in _COMMON_NON_NAMES for w in words):
            return
        seen_spans.add((start, end))
        results.append(DetectedEntity(
            text=matched,
            entity_type=EntityType.PERSON_NAME,
            start=start,
            end=end,
            confidence=0.75,
        ))

    for m in _RAW_PERSON_PATTERN.finditer(text):
        start, end = m.start(), m.end()
        matched = m.group()

        words = matched.split()
        first_word = words[0].rstrip(".,;:")

        if first_word in _COMMON_NON_NAMES and len(words) > 1:
            # The leading word is a title/role — trim it and re-match
            # the suffix starting after the first space
            first_space = matched.index(" ")
            suffix = matched[first_space + 1:]
            suffix_start = start + first_space + 1
            # Try to match the suffix as a name
            sub_m = _RAW_PERSON_PATTERN.match(suffix)
            if sub_m:
                _try_add(sub_m.group(), suffix_start, suffix_start + sub_m.end())
            else:
                # suffix didn't match the pattern — just add it raw if >= 2 words
                suffix_words = suffix.split()
                if len(suffix_words) >= 2:
                    _try_add(suffix, suffix_start, start + end - start)
        else:
            _try_add(matched, start, end)

    return results


def _regex_entities(text: str) -> list[DetectedEntity]:
    """
    Extract entities via compiled regex patterns.

    High-precision patterns are collected first and define "protected zones".
    PERSON_NAME regex matches that overlap any protected zone — or start with
    a common non-name word — are discarded.
    """
    high_confidence: list[DetectedEntity] = []

    for entity_type, pattern in _PATTERNS:
        # _PATTERNS no longer contains PERSON_NAME (handled separately)
        for m in pattern.finditer(text):
            high_confidence.append(DetectedEntity(
                text=m.group(),
                entity_type=entity_type,
                start=m.start(),
                end=m.end(),
                confidence=0.85,
            ))

    # Build protected intervals from high-confidence matches
    protected: list[tuple[int, int]] = [(e.start, e.end) for e in high_confidence]

    # Add name candidates only for unprotected spans
    name_ents = _regex_name_entities(text, protected)

    return high_confidence + name_ents


def _deduplicate(entities: list[DetectedEntity]) -> list[DetectedEntity]:
    """Remove overlapping spans, keeping the highest-confidence / longest one."""
    if not entities:
        return []
    # Sort by start, then by length descending
    entities.sort(key=lambda e: (e.start, -(e.end - e.start)))
    kept: list[DetectedEntity] = []
    last_end = -1
    for ent in entities:
        if ent.start >= last_end:
            kept.append(ent)
            last_end = ent.end
    return kept


class PIIDetector:
    """
    Detects PII entities in text.

    Parameters
    ----------
    use_spacy : bool
        If True (default), attempt to load spaCy for better name detection.
    """

    def __init__(self, use_spacy: bool = True) -> None:
        if use_spacy:
            _load_spacy()

    def detect(self, text: str) -> list[DetectedEntity]:
        """
        Return all detected PII entities, deduplicated and sorted by position.
        """
        entities: list[DetectedEntity] = []

        # spaCy first (higher precision for person names)
        if _SPACY_AVAILABLE:
            entities.extend(_spacy_entities(text))

        # Regex for everything else
        regex_ents = _regex_entities(text)

        # If spaCy already found a PERSON span, skip regex PERSON_NAME overlaps
        spacy_spans = {(e.start, e.end) for e in entities if e.entity_type == EntityType.PERSON_NAME}
        for ent in regex_ents:
            if ent.entity_type == EntityType.PERSON_NAME and spacy_spans:
                # Only add if it doesn't overlap with any spaCy person span
                overlaps = any(
                    not (ent.end <= s or ent.start >= e)
                    for s, e in spacy_spans
                )
                if overlaps:
                    continue
            entities.append(ent)

        return _deduplicate(sorted(entities, key=lambda x: x.start))

    def verify_clean(self, text: str) -> list[str]:
        """
        Run a quick rule-based check to verify no obvious PII remains.
        Returns a list of violation descriptions (empty = clean).
        """
        violations: list[str] = []
        # Only check the hard patterns (IDs, emails, phones, cards, IBAN)
        hard_types = {
            EntityType.EMAIL,
            EntityType.SSN,
            EntityType.NATIONAL_ID,
            EntityType.PASSPORT,
            EntityType.IBAN,
            EntityType.CARD_NUMBER,
        }
        for entity_type, pattern in _PATTERNS:
            if entity_type not in hard_types:
                continue
            m = pattern.search(text)
            if m:
                violations.append(f"{entity_type.value} detected: {m.group()!r}")
        return violations
