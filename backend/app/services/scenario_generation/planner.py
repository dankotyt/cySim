"""Choose the artifact catalog offered to the model, and build a fallback room.

The catalog is small and deterministic per ``(tenant, rule, attempt)``: the
model can only reference objects it was shown, and retries see a different
ordering so a rejected room is not re-emitted verbatim.
"""
from __future__ import annotations

import hashlib

from ...models.scenario import Room, RoomObject
from .registry import Artifact, GenerationResources

MAX_CANDIDATES = 10
DISTRACTORS = 2


def _seeded_order(artifacts: list[Artifact], seed: str) -> list[Artifact]:
    """Order artifacts by a seed-derived hash for reproducible variety."""
    return sorted(
        artifacts,
        key=lambda artifact: hashlib.sha256(
            f"{seed}:{artifact.id}".encode("utf-8")
        ).hexdigest(),
    )


def plan_candidates(
    intent: str,
    resources: GenerationResources,
    *,
    benign: bool,
    seed: str,
    exclude_refs: set[str] | None = None,
    limit: int = MAX_CANDIDATES,
) -> list[Artifact]:
    """Return the artifacts shown to the model for this generation attempt.

    Primary artifacts match the requested polarity. A threat room also gets a
    couple of legitimate distractors; a benign room must contain only
    legitimate objects (L3 ``unexpected_threat``), so it is filled from the
    same safe pool instead.
    ``exclude_refs`` removes objects already used by rejected rooms, so a retry
    changes the composition instead of only reshuffling the catalog.
    """
    excluded = exclude_refs or set()
    pool = resources.artifacts.for_intent(intent)
    primary = [
        artifact
        for artifact in pool
        if artifact.benign == benign and artifact.ref not in excluded
    ]
    if not primary:
        primary = [artifact for artifact in pool if artifact.benign == benign]
    if not primary:
        return []

    extra_pool = [
        artifact
        for artifact in pool
        if artifact.benign and artifact.ref not in excluded
    ]

    primary_slots = max(limit - DISTRACTORS, 1)
    selected = _seeded_order(primary, seed)[:primary_slots]
    used = {artifact.ref for artifact in selected}
    selected += [
        artifact
        for artifact in _seeded_order(extra_pool, seed)
        if artifact.ref not in used
    ][:DISTRACTORS]
    return selected[:limit]


def fallback_room(
    intent: str,
    resources: GenerationResources,
    *,
    benign: bool,
    seed: str,
    offset: int = 0,
) -> Room:
    """Build a guaranteed-valid room without the LLM.

    Used when every generation attempt fails validation or deduplication, so a
    rule always yields a usable exercise instead of an error. ``offset`` walks
    the candidates of the requested polarity, letting the caller skip a
    structural duplicate.
    """
    pool = [
        artifact
        for artifact in resources.artifacts.for_intent(intent)
        if artifact.benign == benign
    ]
    if not pool:
        raise RuntimeError(f"no artifact with benign={benign} for intent {intent!r}")
    artifact = _seeded_order(pool, seed)[offset % len(pool)]

    actions = artifact.goal_actions_for(intent)
    if not actions:
        raise RuntimeError(
            f"artifact {artifact.ref!r} declares no goal action for {intent!r}"
        )

    title = f"Проверка: {artifact.title}"
    if len(title) > 120:
        title = f"{title[:117]}..."
    return Room(
        v=1,
        title=title,
        brief=_fallback_brief(artifact),
        diff=2,
        intent=intent,
        objs=[RoomObject(id="o1", kind=artifact.kind, ref=artifact.ref)],
        goal=f"{actions[0]}(o1)",
    )


def _fallback_brief(artifact: Artifact) -> str:
    """Neutral task text built from the artifact's own description."""
    question = " Что вы сделаете в этой ситуации?"
    situation = (artifact.summary or artifact.title).strip()
    limit = 400 - len(question)
    if len(situation) > limit:
        situation = f"{situation[: limit - 3].rstrip()}..."
    return f"{situation}{question}"
