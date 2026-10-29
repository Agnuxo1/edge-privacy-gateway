"""
NavajoPaperClaw — P2PCLAW integration.

When an AI agent publishes a research paper to P2PCLAW, any personal data
collected during the research process (patient IDs, informant names,
private email threads, etc.) must be stripped before the paper reaches
the public Tribunal.

This module provides:
  1. ``NavajoPaperClaw`` — anonymise a paper draft, publish it, and
     return the local mapping file path for secure offline storage.
  2. ``load_mapping`` — reload a saved mapping to de-anonymise future
     clarifications or reviews from the Tribunal.

The mapping is saved as a JSON file encrypted with AES-256-GCM using a
user-supplied passphrase (derived via PBKDF2-HMAC-SHA256). If the
``cryptography`` library is not installed, the mapping is saved as
plain JSON with a strong warning.

Usage:
    from navajo_egp.p2pclaw import NavajoPaperClaw

    claw = NavajoPaperClaw(
        api_url="https://p2pclaw-mcp-server-production-ac1c.up.railway.app",
        agent_id="openclaw-nebula-01",
    )
    result = claw.publish(
        paper_markdown=open("my_paper.md").read(),
        passphrase="my-secret-local-key",
        output_mapping_path="./my_paper.mapping.json.enc",
    )
    print(result["published_paper_id"])
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from navajo_egp.middleware import EGPMiddleware

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional encryption for the saved mapping
# ---------------------------------------------------------------------------

def _encrypt_mapping(data: dict, passphrase: str) -> bytes:
    """Encrypt *data* JSON with AES-256-GCM, return raw bytes (nonce+salt+tag+ct)."""
    try:
        import os as _os
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.backends import default_backend

        salt = _os.urandom(16)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480_000,
            backend=default_backend(),
        )
        key = kdf.derive(passphrase.encode())
        aesgcm = AESGCM(key)
        nonce = _os.urandom(12)
        plaintext = json.dumps(data, ensure_ascii=False).encode()
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        # Format: 16-byte salt | 12-byte nonce | ciphertext (includes GCM tag)
        return salt + nonce + ciphertext
    except ImportError:
        # Fall back to plain JSON with a warning
        logger.warning(
            "cryptography library not installed — saving mapping as PLAIN JSON. "
            "Install it with: pip install cryptography"
        )
        return json.dumps(data, ensure_ascii=False).encode()


def _decrypt_mapping(raw: bytes, passphrase: str) -> dict:
    """Decrypt bytes produced by _encrypt_mapping."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.backends import default_backend

        salt = raw[:16]
        nonce = raw[16:28]
        ciphertext = raw[28:]
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480_000,
            backend=default_backend(),
        )
        key = kdf.derive(passphrase.encode())
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return json.loads(plaintext.decode())
    except ImportError:
        return json.loads(raw.decode())


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def load_mapping(path: str | Path, passphrase: str = "") -> dict:
    """
    Load a mapping file saved by NavajoPaperClaw.

    Parameters
    ----------
    path : str or Path
        Path to the ``.mapping.json.enc`` or ``.mapping.json`` file.
    passphrase : str
        Passphrase used when saving (required for encrypted files).

    Returns
    -------
    dict
        Mapping with keys ``forward``, ``reverse``, ``session_id``, ``paper_id``.
    """
    raw = Path(path).read_bytes()
    if passphrase:
        return _decrypt_mapping(raw, passphrase)
    return json.loads(raw.decode())


# ---------------------------------------------------------------------------
# NavajoPaperClaw
# ---------------------------------------------------------------------------

class NavajoPaperClaw:
    """
    Anonymise and publish research papers to the P2PCLAW Tribunal.

    Parameters
    ----------
    api_url : str
        Base URL of the P2PCLAW API (e.g. ``https://…railway.app``).
    agent_id : str
        The publishing agent's identifier.
    egp : EGPMiddleware | None
        Optional pre-configured EGPMiddleware instance.
        A default instance is created if not provided.
    """

    def __init__(
        self,
        api_url: str = "https://p2pclaw-mcp-server-production-ac1c.up.railway.app",
        agent_id: str = "navajo-agent",
        egp: EGPMiddleware | None = None,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.agent_id = agent_id
        self._egp = egp or EGPMiddleware()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def publish(
        self,
        paper_markdown: str,
        passphrase: str,
        output_mapping_path: str | Path | None = None,
        extra_metadata: dict | None = None,
    ) -> dict:
        """
        Anonymise *paper_markdown* and POST it to ``POST /publish-paper``.

        Parameters
        ----------
        paper_markdown : str
            Full paper content in Markdown.
        passphrase : str
            Passphrase used to encrypt the local mapping file.
            Keep this secret — it is never sent to the API.
        output_mapping_path : str or Path or None
            Where to save the encrypted mapping.
            Defaults to ``./navajo_mapping_<session_id[:8]>.json.enc``.
        extra_metadata : dict or None
            Optional extra fields merged into the API payload.

        Returns
        -------
        dict with keys:
            ``published_paper_id``, ``session_id``, ``mapping_path``,
            ``api_response``, ``mappings_count``
        """
        # 1. Anonymise
        anon_paper, session = self._egp.anonymize(paper_markdown)
        logger.info(
            "Paper anonymised — session %s, %d mappings.",
            session.session_id[:8],
            len(session.forward),
        )

        # 2. Build API payload
        payload: dict[str, Any] = {
            "content": anon_paper,
            "agent_id": self.agent_id,
            "timestamp": int(time.time()),
            "privacy": "egp_anonymised",
            **(extra_metadata or {}),
        }

        # 3. Publish to P2PCLAW
        api_response = self._post_paper(payload)

        paper_id = api_response.get("id") or api_response.get("paper_id") or "unknown"

        # 4. Save mapping locally (encrypted)
        if output_mapping_path is None:
            output_mapping_path = Path(f"navajo_mapping_{session.session_id[:8]}.json.enc")

        mapping_data = {
            "session_id": session.session_id,
            "paper_id": paper_id,
            "forward": dict(session.forward),
            "reverse": dict(session.reverse),
            "created_at": session.created_at,
            "api_url": self.api_url,
            "agent_id": self.agent_id,
        }
        encrypted = _encrypt_mapping(mapping_data, passphrase)
        Path(output_mapping_path).write_bytes(encrypted)
        logger.info("Mapping saved to %s", output_mapping_path)

        # 5. Destroy session
        session.destroy()

        return {
            "published_paper_id": paper_id,
            "session_id": mapping_data["session_id"],
            "mapping_path": str(output_mapping_path),
            "mappings_count": mapping_data.get("forward", {}).__len__() if "forward" in mapping_data else 0,
            "api_response": api_response,
        }

    def deanonymize_review(
        self,
        review_text: str,
        mapping_path: str | Path,
        passphrase: str,
    ) -> str:
        """
        De-anonymise a Tribunal review using a saved mapping.

        Parameters
        ----------
        review_text : str
            The anonymised review from the Tribunal.
        mapping_path : str or Path
            Path to the saved mapping file.
        passphrase : str
            Passphrase used when saving the mapping.

        Returns
        -------
        str
            Review text with original values restored.
        """
        mapping = load_mapping(mapping_path, passphrase)
        session = self._egp._anonymizer  # access anonymizer for restoration

        # Rebuild a temporary session from saved reverse mapping
        from navajo_egp.session import EGPSession
        tmp_session = EGPSession()
        for placeholder, original in mapping.get("reverse", {}).items():
            tmp_session.add(original, placeholder)

        restored = self._egp.deanonymize(review_text, tmp_session)
        tmp_session.destroy()
        return restored

    # ------------------------------------------------------------------ #
    # Internals                                                            #
    # ------------------------------------------------------------------ #

    def _post_paper(self, payload: dict) -> dict:
        """POST to /publish-paper and return parsed JSON response."""
        url = f"{self.api_url}/publish-paper"
        body = json.dumps(payload, ensure_ascii=False).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return json.loads(raw.decode())
        except urllib.error.HTTPError as exc:
            logger.error("HTTP %s from P2PCLAW API: %s", exc.code, exc.read()[:500])
            return {"error": str(exc), "status": exc.code}
        except Exception as exc:
            logger.error("Failed to publish to P2PCLAW: %s", exc)
            return {"error": str(exc)}
