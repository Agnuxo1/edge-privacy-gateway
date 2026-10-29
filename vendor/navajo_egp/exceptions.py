"""Custom exceptions for navajo-egp."""


class EGPError(Exception):
    """Base exception for all EGP errors."""


class PIILeakageError(EGPError):
    """Raised when PII is detected in the anonymized output — safe to send."""

    def __init__(self, violations: list[str] | None = None):
        self.violations = violations or []
        super().__init__(
            f"PII leakage detected after anonymization. "
            f"Violations: {', '.join(self.violations)}"
        )


class DeanonymizationError(EGPError):
    """Raised when a mapping key cannot be found during deanonymization."""
