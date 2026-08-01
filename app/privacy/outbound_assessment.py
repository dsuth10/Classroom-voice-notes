"""Outbound Privacy Assessment Dataclass and Types."""
from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class OutboundAssessment:
    """Structured assessment of outbound content for privacy and risk.

    Attributes:
        automatic_classification: Classification from local classifier (e.g., 'non_sensitive').
        risk_level: Overall privacy risk ('low', 'medium', 'high').
        findings: Non-sensitive finding codes describing detected privacy flags.
        checks_passed: List of PolicyGate check identifiers passed.
        suggested_redactions: Non-sensitive suggestions for redacting content.
        safe_auto_allowed: Whether content meets all rules for automatic v1 dispatch.
    """

    automatic_classification: str
    risk_level: str
    findings: List[str] = field(default_factory=list)
    checks_passed: List[str] = field(default_factory=list)
    suggested_redactions: List[str] = field(default_factory=list)
    safe_auto_allowed: bool = False
