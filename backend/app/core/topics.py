"""Single source of truth for security-rule topics and attack types.

``ALLOWED_TOPICS`` is the controlled vocabulary the LLM must pick from when
structuring rules. The first eight values double as the scenario-generation
attack types (``ATTACK_TYPES`` / ``AttackType``), and ``ATTACK_TYPE_TOPICS``
maps each attack type to the rule topics that are relevant to it.
"""
from typing import Literal

# All allowed rule topics. Anything that does not fit is mapped to "other".
ALLOWED_TOPICS: tuple[str, ...] = (
    "phishing",
    "vishing",
    "baiting",
    "pretexting",
    "tailgating",
    "quid_pro_quo",
    "social_media_osint",
    "usb_drop",
    "passwords",
    "physical_security",
    "data_handling",
    "remote_work",
    "insider_threat",
    "supply_chain",
    "leaked_credentials",
    "access_control",
    "incidents",
    "other",
)

# The first eight topics are the attack vectors the generator supports.
ATTACK_TYPES: tuple[str, ...] = ALLOWED_TOPICS[:8]

AttackType = Literal[
    "phishing",
    "vishing",
    "baiting",
    "pretexting",
    "tailgating",
    "quid_pro_quo",
    "social_media_osint",
    "usb_drop",
]

# Per-attack relevant topics. Today this is 1:1 (an attack maps only to its own
# topic); if an attack later spans several topics, extend these tuples.
ATTACK_TYPE_TOPICS: dict[str, tuple[str, ...]] = {
    attack: (attack,) for attack in ATTACK_TYPES
}
