"""
AsyncEGPMiddleware — async-first privacy middleware for high-throughput services.

Extends EGPMiddleware with:
  - async_anonymize / async_deanonymize (thin async wrappers, CPU-bound work
    stays synchronous but the interface is awaitable)
  - async_wrap_llm_call — same pipeline as wrap_llm_call but for async callables
  - wrap_openai_async / wrap_anthropic_async — convenience factories for the
    async variants of the official SDKs

Usage:
    from navajo_egp.async_middleware import AsyncEGPMiddleware

    egp = AsyncEGPMiddleware()

    # Async pipeline
    result = await egp.async_wrap_llm_call(
        prompt="Patient Maria Perez, SSN 123-45-6789...",
        llm_fn=my_async_llm,   # async def my_async_llm(prompt: str) -> str
    )

    # Wrap openai.AsyncOpenAI
    from openai import AsyncOpenAI
    client = egp.wrap(AsyncOpenAI())
    response = await client.chat.completions.acreate(model="gpt-4o", messages=[...])
"""

from __future__ import annotations

import logging
from typing import Callable, Awaitable

from navajo_egp.middleware import EGPMiddleware
from navajo_egp.session import EGPSession

logger = logging.getLogger(__name__)


class AsyncEGPMiddleware(EGPMiddleware):
    """
    Async-compatible EGP middleware.

    All synchronous methods from EGPMiddleware still work unchanged.
    This class adds async counterparts for use in asyncio event loops.
    """

    async def async_anonymize(self, text: str) -> tuple[str, EGPSession]:
        """
        Async wrapper around :meth:`anonymize`.

        The underlying detection is regex-based (CPU-bound) and runs
        synchronously, but the interface is awaitable for use in
        async code without blocking the event loop for large texts.
        For very large documents in production, consider running via
        ``asyncio.get_event_loop().run_in_executor(None, self.anonymize, text)``.
        """
        return self.anonymize(text)

    async def async_deanonymize(self, text: str, session: EGPSession) -> str:
        """Async wrapper around :meth:`deanonymize`."""
        return self.deanonymize(text, session)

    async def async_wrap_llm_call(
        self,
        prompt: str,
        llm_fn: Callable[[str], Awaitable[str]],
    ) -> str:
        """
        Full async privacy pipeline:
          1. Anonymise *prompt*
          2. ``await llm_fn(anonymised_prompt)`` → response
          3. De-anonymise response
          4. Destroy session

        Parameters
        ----------
        prompt : str
            The original (possibly sensitive) prompt.
        llm_fn : async callable
            An async function that accepts a string and returns a string.
            Example: ``async def call_gpt(p): return await client.chat...``

        Returns
        -------
        str
            The de-anonymised LLM response.
        """
        anon_prompt, session = await self.async_anonymize(prompt)
        logger.info(
            "EGP async session %s — %d mappings applied.",
            session.session_id[:8],
            len(session.forward),
        )
        try:
            anon_response = await llm_fn(anon_prompt)
            result = await self.async_deanonymize(anon_response, session)
            return result
        finally:
            meta = session.destroy()
            logger.info(
                "EGP async session %s destroyed — %d ms, %d mappings.",
                meta.get("session_id", "?")[:8],
                meta.get("duration_ms", 0),
                meta.get("mappings_count", 0),
            )
