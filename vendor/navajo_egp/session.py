"""
EGP Session — ephemeral mapping store.

Each session holds a forward mapping  (original → placeholder)
and reverse mapping (placeholder → original).

Sessions are designed to be short-lived: create one per LLM request,
destroy it (call .destroy()) as soon as the response is de-anonymised.
"""

from __future__ import annotations

import gc
import secrets
import time
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class EGPSession:
    """
    Stores the ephemeral anonymisation dictionary for a single query cycle.

    Attributes
    ----------
    session_id : str
        Randomly generated 32-hex-char session identifier.
    created_at : float
        Unix timestamp of session creation.
    forward : dict[str, str]
        Maps original PII text → placeholder token.
    reverse : dict[str, str]
        Maps placeholder token → original PII text.
    destroyed : bool
        True once .destroy() has been called.
    """

    session_id: str = field(default_factory=lambda: secrets.token_hex(16))
    created_at: float = field(default_factory=time.time)
    forward: Dict[str, str] = field(default_factory=dict)
    reverse: Dict[str, str] = field(default_factory=dict)
    destroyed: bool = False

    # ------------------------------------------------------------------ #
    # Mapping management                                                   #
    # ------------------------------------------------------------------ #

    def add(self, original: str, placeholder: str) -> None:
        """Register a new original→placeholder mapping."""
        self._check_alive()
        self.forward[original] = placeholder
        self.reverse[placeholder] = original

    def get_placeholder(self, original: str) -> str | None:
        """Return the placeholder for a known original, or None."""
        return self.forward.get(original)

    def get_original(self, placeholder: str) -> str | None:
        """Return the original for a known placeholder, or None."""
        return self.reverse.get(placeholder)

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def duration_ms(self) -> int:
        """Milliseconds elapsed since session creation."""
        return int((time.time() - self.created_at) * 1000)

    def destroy(self) -> dict:
        """
        Securely destroy all mappings and mark session as destroyed.

        Returns a metadata summary (no sensitive data) for audit logging.
        """
        if self.destroyed:
            return {}

        summary = {
            "session_id": self.session_id,
            "duration_ms": self.duration_ms(),
            "mappings_count": len(self.forward),
        }

        # Overwrite values in memory before clearing references
        for k in list(self.forward):
            self.forward[k] = "\x00" * max(len(self.forward[k]), 32)
        for k in list(self.reverse):
            self.reverse[k] = "\x00" * max(len(self.reverse[k]), 32)

        self.forward.clear()
        self.reverse.clear()
        self.destroyed = True

        gc.collect()
        return summary

    # ------------------------------------------------------------------ #
    # Internals                                                            #
    # ------------------------------------------------------------------ #

    def _check_alive(self) -> None:
        if self.destroyed:
            raise RuntimeError(
                f"EGPSession {self.session_id} has been destroyed and cannot be used."
            )

    def __repr__(self) -> str:
        status = "DESTROYED" if self.destroyed else f"{len(self.forward)} mappings"
        return f"<EGPSession id={self.session_id[:8]}... {status}>"
