"""
EGPMiddleware — the main entry point for navajo-egp.

Usage pattern A — manual:
    egp = EGPMiddleware()
    anon_text, mapping = egp.anonymize("Juan Garcia, DNI 12345678A ...")
    # ... call LLM with anon_text ...
    final = egp.deanonymize(llm_response, mapping)

Usage pattern B — automatic pipeline:
    egp = EGPMiddleware()
    result = egp.wrap_llm_call(prompt, llm_fn=my_llm_function)

Usage pattern C — wrap an SDK client:
    from openai import OpenAI
    egp = EGPMiddleware()
    private_client = egp.wrap(OpenAI())
    response = private_client.chat.completions.create(...)

Usage pattern D — custom PII patterns:
    egp = EGPMiddleware()
    egp.add_pattern(label="HOSPITAL_ID", pattern=r'\\bHID-\\d{6}\\b', placeholder_prefix="HID_")
    anon, session = egp.anonymize("Patient HID-123456 presented with ...")
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Dict, Optional

from navajo_egp.anonymizer import Anonymizer
from navajo_egp.detector import PIIDetector
from navajo_egp.exceptions import PIILeakageError
from navajo_egp.session import EGPSession

logger = logging.getLogger(__name__)


class EGPMiddleware:
    """
    Privacy middleware implementing the Ephemeral Generalization Protocol.

    Parameters
    ----------
    use_spacy : bool
        Load spaCy NER for improved name detection (default True).
        Falls back gracefully to regex if spaCy is not installed.
    verify_after_anonymize : bool
        Run a hard-rule PII check on the anonymised text before returning
        (default True). Raises PIILeakageError if PII is still present.
    strict : bool
        If True, raises PIILeakageError instead of just logging a warning
        when PII is detected post-anonymisation (default True).
    """

    def __init__(
        self,
        use_spacy: bool = True,
        verify_after_anonymize: bool = True,
        strict: bool = True,
    ) -> None:
        self._detector = PIIDetector(use_spacy=use_spacy)
        self._anonymizer = Anonymizer()
        self._verify = verify_after_anonymize
        self._strict = strict
        # Custom pattern registry: list of (label, compiled_pattern, prefix)
        self._custom_patterns: list[tuple[str, re.Pattern, str]] = []

    # ------------------------------------------------------------------ #
    # Custom pattern registration                                          #
    # ------------------------------------------------------------------ #

    def add_pattern(
        self,
        label: str,
        pattern: str,
        placeholder_prefix: Optional[str] = None,
        flags: int = re.IGNORECASE,
    ) -> None:
        """
        Register a custom regex pattern for domain-specific PII detection.

        Parameters
        ----------
        label : str
            A short identifier for this entity type (e.g. "HOSPITAL_ID").
            Used as the placeholder prefix if *placeholder_prefix* is not given.
        pattern : str
            A Python regex string to match the custom PII.
        placeholder_prefix : str, optional
            Prefix for generated placeholders (e.g. "HID_").
            Defaults to ``label + "_"``.
        flags : int
            Regex flags (default: re.IGNORECASE).

        Example
        -------
        egp.add_pattern(
            label="HOSPITAL_ID",
            pattern=r"\\bHID-\\d{6}\\b",
            placeholder_prefix="HID_",
        )
        """
        prefix = placeholder_prefix or (label.upper().rstrip("_") + "_")
        self._custom_patterns.append((label, re.compile(pattern, flags), prefix))

    def _apply_custom_patterns(self, text: str, session: EGPSession) -> str:
        """Apply all custom patterns in registration order."""
        result = text
        for label, compiled, prefix in self._custom_patterns:
            counter = 0
            def _replacer(m: re.Match, _label=label, _prefix=prefix) -> str:
                nonlocal counter
                matched = m.group()
                existing = session.get_placeholder(matched)
                if existing:
                    return existing
                counter += 1
                ph = f"{_prefix}{counter:03d}"
                session.add(matched, ph)
                return ph
            result = compiled.sub(_replacer, result)
        return result

    # ------------------------------------------------------------------ #
    # Core API                                                             #
    # ------------------------------------------------------------------ #

    def anonymize(self, text: str) -> tuple[str, EGPSession]:
        """
        Detect and replace all PII entities in *text*.

        Returns
        -------
        (anonymised_text, session)
            *session* must be passed to :meth:`deanonymize` and then
            destroyed by calling ``session.destroy()``.

        Raises
        ------
        PIILeakageError
            If *verify_after_anonymize* is True and *strict* is True and
            the anonymised text still contains detectable PII.
        """
        session = EGPSession()
        self._anonymizer.reset_counters()

        # Apply custom patterns FIRST so they take priority and protect
        # their spans from being consumed by the built-in detectors.
        pre_text = text
        if self._custom_patterns:
            pre_text = self._apply_custom_patterns(text, session)

        entities = self._detector.detect(pre_text)
        logger.debug("Detected %d entities in input text.", len(entities))

        anon_text = self._anonymizer.apply(pre_text, entities, session)

        if self._verify:
            violations = self._detector.verify_clean(anon_text)
            if violations:
                if self._strict:
                    session.destroy()
                    raise PIILeakageError(violations)
                else:
                    logger.warning(
                        "PII still present after anonymisation: %s", violations
                    )

        return anon_text, session

    def deanonymize(self, text: str, session: EGPSession) -> str:
        """
        Replace placeholders in *text* with originals stored in *session*.

        After calling this method you should call ``session.destroy()``
        unless you need to reuse the mapping.
        """
        return self._anonymizer.restore(text, session)

    def wrap_llm_call(
        self,
        prompt: str,
        llm_fn: Callable[[str], str],
    ) -> str:
        """
        Complete privacy pipeline:
          1. Anonymise *prompt*
          2. Call *llm_fn(anonymised_prompt)* → response
          3. De-anonymise response
          4. Destroy session

        Parameters
        ----------
        prompt : str
            The original (possibly sensitive) prompt.
        llm_fn : callable
            A function that accepts a string prompt and returns a string response.
            Examples: ``lambda p: openai_client.chat.completions.create(…)``

        Returns
        -------
        str
            The de-anonymised LLM response.
        """
        anon_prompt, session = self.anonymize(prompt)
        logger.info(
            "EGP session %s — %d mappings applied.",
            session.session_id[:8],
            len(session.forward),
        )
        try:
            anon_response = llm_fn(anon_prompt)
            result = self.deanonymize(anon_response, session)
            return result
        finally:
            meta = session.destroy()
            logger.info(
                "EGP session %s destroyed — %d ms, %d mappings.",
                meta.get("session_id", "?")[:8],
                meta.get("duration_ms", 0),
                meta.get("mappings_count", 0),
            )

    # ------------------------------------------------------------------ #
    # SDK wrappers                                                         #
    # ------------------------------------------------------------------ #

    def wrap(self, client: object) -> object:
        """
        Auto-detect the SDK type and return an appropriate privacy wrapper.

        Supports:
          - openai.OpenAI / openai.AsyncOpenAI
          - anthropic.Anthropic / anthropic.AsyncAnthropic
          - Any LangChain BaseChatModel

        Parameters
        ----------
        client
            An instantiated SDK client.

        Returns
        -------
        A wrapped client with the same interface but automatic EGP
        anonymisation/de-anonymisation on every call.
        """
        class_name = type(client).__name__
        module_name = type(client).__module__

        if "openai" in module_name:
            from navajo_egp.integrations.openai_wrapper import NavajoOpenAI
            return NavajoOpenAI(client, self)

        if "anthropic" in module_name:
            from navajo_egp.integrations.anthropic_wrapper import NavajoAnthropic
            return NavajoAnthropic(client, self)

        # LangChain
        try:
            from langchain_core.language_models.chat_models import BaseChatModel  # noqa
            if isinstance(client, BaseChatModel):
                from navajo_egp.integrations.langchain_wrapper import NavajoChatModel
                return NavajoChatModel(llm=client, egp=self)
        except ImportError:
            pass

        raise TypeError(
            f"Cannot auto-wrap {class_name!r}. "
            "Use anonymize()/deanonymize() manually, or pass a supported client "
            "(openai.OpenAI, anthropic.Anthropic, LangChain BaseChatModel)."
        )
