"""
Anthropic SDK wrapper — NavajoAnthropic.

Wraps ``anthropic.Anthropic`` (sync).
Intercepts ``messages.create()`` transparently.

Usage:
    import anthropic
    from navajo_egp import EGPMiddleware

    egp = EGPMiddleware()
    client = egp.wrap(anthropic.Anthropic())

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": "Patient Juan García, DNI 12345678A…"}]
    )
    # message.content[0].text is already de-anonymised
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class _NavajoMessages:
    """Proxy for client.messages with EGP applied."""

    def __init__(self, original_messages: Any, egp: Any) -> None:
        self._original = original_messages
        self._egp = egp

    def create(self, **kwargs: Any) -> Any:
        messages = kwargs.get("messages", [])
        sessions: list = []

        new_messages = []
        for msg in messages:
            content = msg.get("content")
            if msg.get("role") in {"user"} and isinstance(content, str):
                anon_content, session = self._egp.anonymize(content)
                sessions.append(session)
                new_msg = dict(msg)
                new_msg["content"] = anon_content
                new_messages.append(new_msg)
            else:
                new_messages.append(msg)

        kwargs["messages"] = new_messages

        # Anonymise system prompt too if present
        system_sessions: list = []
        if "system" in kwargs and isinstance(kwargs["system"], str):
            anon_sys, sys_session = self._egp.anonymize(kwargs["system"])
            kwargs["system"] = anon_sys
            system_sessions.append(sys_session)

        response = self._original.create(**kwargs)

        try:
            all_sessions = system_sessions + sessions
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    restored = block.text
                    for session in reversed(all_sessions):
                        restored = self._egp.deanonymize(restored, session)
                    block.text = restored
        finally:
            for session in system_sessions + sessions:
                session.destroy()

        return response

    async def acreate(self, **kwargs: Any) -> Any:
        """Async variant (for AsyncAnthropic)."""
        messages = kwargs.get("messages", [])
        sessions: list = []

        new_messages = []
        for msg in messages:
            content = msg.get("content")
            if msg.get("role") == "user" and isinstance(content, str):
                anon_content, session = self._egp.anonymize(content)
                sessions.append(session)
                new_msg = dict(msg)
                new_msg["content"] = anon_content
                new_messages.append(new_msg)
            else:
                new_messages.append(msg)

        kwargs["messages"] = new_messages

        system_sessions: list = []
        if "system" in kwargs and isinstance(kwargs["system"], str):
            anon_sys, sys_session = self._egp.anonymize(kwargs["system"])
            kwargs["system"] = anon_sys
            system_sessions.append(sys_session)

        response = await self._original.acreate(**kwargs)

        try:
            all_sessions = system_sessions + sessions
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    restored = block.text
                    for session in reversed(all_sessions):
                        restored = self._egp.deanonymize(restored, session)
                    block.text = restored
        finally:
            for session in system_sessions + sessions:
                session.destroy()

        return response


class NavajoAnthropic:
    """
    Wraps ``anthropic.Anthropic`` with automatic EGP anonymisation.
    """

    def __init__(self, client: Any, egp: Any) -> None:
        self._client = client
        self._egp = egp
        self.messages = _NavajoMessages(client.messages, egp)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)
