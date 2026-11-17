"""Structural fingerprint of a room, used for cheap duplicate detection.

The fingerprint deliberately ignores titles and briefs: two rooms built from
the same objects with the same goal are the same training exercise even if the
prose differs. Embedding-based near-duplicate search arrives in milestone M9.
"""
from __future__ import annotations

import hashlib
import json

from ...models.scenario import Room


def room_fingerprint(room: Room) -> str:
    """Return a stable hash of the room's structure.

    The intent, not the topic, identifies what the room trains: two rules with
    different analytics topics can still produce the same exercise.
    """
    payload = {
        "intent": " ".join(room.intent.split()).casefold(),
        "goal": " ".join(room.goal.split()).casefold(),
        "objs": sorted(f"{obj.kind}:{obj.ref}" for obj in room.objs),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
