"""Single source of truth for security-rule topics.

``ALLOWED_TOPICS`` is the controlled vocabulary the LLM must pick from when
structuring rules, and the same vocabulary drives scenario generation.
"""

# All allowed rule topics. Anything that does not fit is mapped to "other".
ALLOWED_TOPICS: tuple[str, ...] = (
    "passwords", "phishing", "internet", "authentication", "access_control",
    "incident", "backup", "email_security", "remote_access",
    "physical_security", "training", "personal_data", "management",
    "contractors_security", "monitoring", "audit", "misuse", "other",
)
