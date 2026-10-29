"""
Streaming support for navajo-egp.

When using OpenAI or Anthropic streaming responses, the LLM returns content
in small chunks. PII placeholders in the response may be split across chunks,
making real-time de-anonymisation impossible chunk-by-chunk.

Strategy: buffer the full streamed response, de-anonymise it, then yield it
as a single chunk (or yield it word-by-word to preserve the streaming UX).

Usage with OpenAI:
    from navajo_egp import EGPMiddleware
    from navajo_egp.streaming import stream_with_egp

    egp = EGPMiddleware()

    for chunk in stream_with_egp(
        prompt="Patient Juan Garcia, DNI 12345678A, has diabetes.",
        egp=egp,
        stream_fn=lambda p: openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": p}],
            stream=True,
        ),
        chunk_text_fn=lambda chunk: chunk.choices[0].delta.content or "",
    ):
        print(chunk, end="", flush=True)
"""

from __future__ import annotations

import logging
from typing import Callable, Generator, Iterable, Iterator, TypeVar

from navajo_egp.middleware import EGPMiddleware

logger = logging.getLogger(__name__)

T = TypeVar("T")


def stream_with_egp(
    prompt: str,
    egp: EGPMiddleware,
    stream_fn: Callable[[str], Iterable[T]],
    chunk_text_fn: Callable[[T], str],
    word_by_word: bool = False,
) -> Generator[str, None, None]:
    """
    Privacy-preserving streaming wrapper.

    Parameters
    ----------
    prompt : str
        The original (possibly sensitive) prompt.
    egp : EGPMiddleware
        An EGPMiddleware instance.
    stream_fn : callable
        A function that accepts an anonymised prompt string and returns
        an iterable of chunks (e.g., an OpenAI streaming response).
    chunk_text_fn : callable
        Extracts the text content from each chunk object.
        Example: ``lambda chunk: chunk.choices[0].delta.content or ""``
    word_by_word : bool
        If True, yield the de-anonymised response word by word to preserve
        a streaming UX. If False (default), yield the full response at once.

    Yields
    ------
    str
        De-anonymised text chunks. With ``word_by_word=False``, only one
        chunk is yielded (the complete response). With ``word_by_word=True``,
        one word (plus trailing space) is yielded at a time.

    Notes
    -----
    The external LLM only ever sees the anonymised prompt. The streamed
    response is buffered internally until complete, then de-anonymised
    before delivery to the caller.
    """
    anon_prompt, session = egp.anonymize(prompt)
    logger.info(
        "EGP streaming session %s — %d mappings.",
        session.session_id[:8],
        len(session.forward),
    )

    # Buffer the streamed response
    buffer: list[str] = []
    try:
        for chunk in stream_fn(anon_prompt):
            text = chunk_text_fn(chunk)
            if text:
                buffer.append(text)
    except Exception:
        session.destroy()
        raise

    full_anon_response = "".join(buffer)
    full_restored = egp.deanonymize(full_anon_response, session)
    session.destroy()

    if word_by_word:
        words = full_restored.split(" ")
        for i, word in enumerate(words):
            yield word + ("" if i == len(words) - 1 else " ")
    else:
        yield full_restored


async def async_stream_with_egp(
    prompt: str,
    egp: EGPMiddleware,
    stream_fn: Callable,
    chunk_text_fn: Callable,
    word_by_word: bool = False,
):
    """
    Async variant of stream_with_egp for AsyncOpenAI / AsyncAnthropic.

    Parameters
    ----------
    prompt : str
        The original sensitive prompt.
    egp : EGPMiddleware
        An EGPMiddleware (or AsyncEGPMiddleware) instance.
    stream_fn : async callable
        Returns an async iterable of chunks.
        Example: ``lambda p: async_client.chat.completions.create(stream=True, ...)``
    chunk_text_fn : callable
        Extracts text from each chunk object.
    word_by_word : bool
        If True, yield one word at a time (async generator).

    Yields
    ------
    str
        De-anonymised text.
    """
    anon_prompt, session = egp.anonymize(prompt)
    logger.info(
        "EGP async-stream session %s — %d mappings.",
        session.session_id[:8],
        len(session.forward),
    )

    buffer: list[str] = []
    try:
        async for chunk in await stream_fn(anon_prompt):
            text = chunk_text_fn(chunk)
            if text:
                buffer.append(text)
    except Exception:
        session.destroy()
        raise

    full_anon_response = "".join(buffer)
    full_restored = egp.deanonymize(full_anon_response, session)
    session.destroy()

    if word_by_word:
        words = full_restored.split(" ")
        for i, word in enumerate(words):
            yield word + ("" if i == len(words) - 1 else " ")
    else:
        yield full_restored
