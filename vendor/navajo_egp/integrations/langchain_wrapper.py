"""
LangChain wrapper — NavajoChatModel.

Wraps any ``langchain_core.language_models.chat_models.BaseChatModel``
and applies EGP anonymisation on every ``invoke()`` / ``ainvoke()`` call.

Usage:
    from langchain_openai import ChatOpenAI
    from navajo_egp import EGPMiddleware

    egp = EGPMiddleware()
    llm = egp.wrap(ChatOpenAI(model="gpt-4o"))

    response = llm.invoke("Paciente Juan García, DNI 12345678A tiene diabetes…")
    # response.content is already de-anonymised
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Sequence

logger = logging.getLogger(__name__)


class NavajoChatModel:
    """
    LangChain-compatible chat model that applies EGP to every call.

    Implements the subset of BaseChatModel API used most frequently:
      - invoke(input)
      - ainvoke(input)
      - __call__(messages)
    """

    def __init__(self, llm: Any, egp: Any) -> None:
        self._llm = llm
        self._egp = egp

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _extract_text(self, input_: Any) -> str:
        """Extract plain string from various LangChain input shapes."""
        if isinstance(input_, str):
            return input_
        if isinstance(input_, list):
            # List of BaseMessage or dicts
            parts = []
            for msg in input_:
                if hasattr(msg, "content"):
                    parts.append(str(msg.content))
                elif isinstance(msg, dict):
                    parts.append(str(msg.get("content", "")))
            return "\n".join(parts)
        if hasattr(input_, "content"):
            return str(input_.content)
        return str(input_)

    def _patch_content(self, response: Any, restored: str) -> Any:
        """Write back the de-anonymised text into the response object."""
        if hasattr(response, "content"):
            try:
                response.content = restored
            except AttributeError:
                pass  # frozen / read-only
        return response

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def invoke(self, input_: Any, **kwargs: Any) -> Any:
        text = self._extract_text(input_)
        anon_text, session = self._egp.anonymize(text)

        # Rebuild input preserving original type
        if isinstance(input_, str):
            anon_input = anon_text
        elif isinstance(input_, list):
            anon_input = []
            idx = 0
            for msg in input_:
                if hasattr(msg, "content"):
                    # Try to create a copy with patched content
                    try:
                        msg = msg.copy(update={"content": anon_text})
                    except Exception:
                        pass
                anon_input.append(msg)
        else:
            anon_input = input_

        try:
            response = self._llm.invoke(anon_input, **kwargs)
            restored = self._egp.deanonymize(self._extract_text(response), session)
            return self._patch_content(response, restored)
        finally:
            session.destroy()

    async def ainvoke(self, input_: Any, **kwargs: Any) -> Any:
        text = self._extract_text(input_)
        anon_text, session = self._egp.anonymize(text)

        if isinstance(input_, str):
            anon_input = anon_text
        else:
            anon_input = input_

        try:
            response = await self._llm.ainvoke(anon_input, **kwargs)
            restored = self._egp.deanonymize(self._extract_text(response), session)
            return self._patch_content(response, restored)
        finally:
            session.destroy()

    def __call__(self, messages: Any, **kwargs: Any) -> Any:
        return self.invoke(messages, **kwargs)

    # Pass through everything else (temperature, streaming, bind_tools, etc.)
    def __getattr__(self, name: str) -> Any:
        return getattr(self._llm, name)
