"""Choose the artifact catalog offered to the model, and build a fallback room.

The catalog is small and deterministic per ``(tenant, rule, attempt)``: the
model can only reference objects it was shown, and retries see a different
ordering so a rejected room is not re-emitted verbatim.
"""
from __future__ import annotations

import hashlib

from ...models.scenario import Room, RoomObject
from .registry import Artifact, GenerationResources

MAX_CANDIDATES = 12
BENIGN_SLOTS = 3


def _seeded_order(artifacts: list[Artifact], seed: str) -> list[Artifact]:
    """Order artifacts by a seed-derived hash for reproducible variety."""
    return sorted(
        artifacts,
        key=lambda artifact: hashlib.sha256(
            f"{seed}:{artifact.id}".encode("utf-8")
        ).hexdigest(),
    )


def plan_candidates(
    rule_topic: str,
    resources: GenerationResources,
    *,
    seed: str,
    limit: int = MAX_CANDIDATES,
) -> list[Artifact]:
    """Return the artifacts shown to the model for this generation attempt."""
    pool = resources.artifacts.for_topic(rule_topic)
    malicious = [artifact for artifact in pool if not artifact.benign]
    benign = [artifact for artifact in pool if artifact.benign]

    if not malicious:
        malicious = [
            artifact
            for artifact in resources.artifacts.all()
            if not artifact.benign
        ]
    if not benign:
        benign = [artifact for artifact in resources.artifacts.all() if artifact.benign]

    malicious_slots = max(limit - BENIGN_SLOTS, 1)
    selected = _seeded_order(malicious, seed)[:malicious_slots]
    selected += _seeded_order(benign, seed)[:BENIGN_SLOTS]
    return selected[:limit]


def fallback_room(
    rule_topic: str,
    resources: GenerationResources,
    *,
    seed: str,
    offset: int = 0,
) -> Room:
    """Build a guaranteed-valid room without the LLM.

    Used when every generation attempt fails validation or deduplication, so a
    rule always yields a usable exercise instead of an error. ``offset`` walks
    the malicious candidates, letting the caller skip a structural duplicate.
    """
    candidates = plan_candidates(rule_topic, resources, seed=seed)
    malicious = [candidate for candidate in candidates if not candidate.benign]
    if not malicious:
        raise RuntimeError("fixture registry has no malicious artifact")
    artifact = malicious[offset % len(malicious)]

    title = f"Проверка: {artifact.title}"
    if len(title) > 120:
        title = f"{title[:117]}..."
    return Room(
        v=1,
        title=title,
        brief=(
            f"В работе появился объект «{artifact.title}». Проверьте его и "
            "поступите в соответствии с политикой информационной безопасности "
            "компании."
        ),
        diff=2,
        topic=rule_topic,
        objs=[RoomObject(id="o1", kind=artifact.kind, ref=artifact.ref)],
        goal="report(o1)",
    )
