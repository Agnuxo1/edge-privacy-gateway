"""
navajo_egp — Ephemeral Generalization Protocol
Privacy-preserving middleware for LLM queries.

Anonymizes sensitive data (names, IDs, emails, phones, addresses,
financial accounts, medical record numbers) before sending to external
LLM APIs, then de-anonymizes the response.

Quick start:
    from navajo_egp import EGPMiddleware
    egp = EGPMiddleware()
    anon, session = egp.anonymize("Patient Juan Garcia, DNI 12345678A...")
    response = call_llm(anon)
    final = egp.deanonymize(response, session)
    session.destroy()

Async quick start:
    from navajo_egp.async_middleware import AsyncEGPMiddleware
    egp = AsyncEGPMiddleware()
    result = await egp.async_wrap_llm_call(prompt, llm_fn=my_async_fn)

Streaming quick start:
    from navajo_egp.streaming import stream_with_egp
    for chunk in stream_with_egp(prompt, egp, stream_fn, chunk_text_fn):
        print(chunk, end="")
"""

from navajo_egp.middleware import EGPMiddleware
from navajo_egp.async_middleware import AsyncEGPMiddleware
from navajo_egp.entities import EntityType, DetectedEntity
from navajo_egp.session import EGPSession
from navajo_egp.exceptions import PIILeakageError, EGPError
from navajo_egp.streaming import stream_with_egp, async_stream_with_egp

__version__ = "0.1.0"
__author__ = "Francisco Angulo de Lafuente"
__all__ = [
    "EGPMiddleware",
    "AsyncEGPMiddleware",
    "EGPSession",
    "EntityType",
    "DetectedEntity",
    "PIILeakageError",
    "EGPError",
    "stream_with_egp",
    "async_stream_with_egp",
]
