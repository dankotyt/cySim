"""Structural fingerprint used to reject duplicate rooms."""
from app.models.scenario import Room
from app.services.scenario_generation.dedup import room_fingerprint
from tests.fakes import VALID_ROOM


def _room(**overrides) -> Room:
    return Room.model_validate(
        {"topic": "phishing", **VALID_ROOM, **overrides}
    )


def test_identical_structure_has_the_same_fingerprint():
    first = _room()
    second = _room(
        title="Другое название",
        brief="Совершенно другой текст задания, но те же объекты и цель.",
    )

    assert room_fingerprint(first) == room_fingerprint(second)


def test_different_goal_changes_the_fingerprint():
    assert room_fingerprint(_room()) != room_fingerprint(_room(goal="dismiss(o1)"))


def test_different_objects_change_the_fingerprint():
    other = _room(objs=[{"id": "o1", "kind": "email", "ref": "fx:email:em-0003"}])

    assert room_fingerprint(_room()) != room_fingerprint(other)


def test_different_intent_changes_the_fingerprint():
    assert (
        room_fingerprint(_room())
        != room_fingerprint(_room(intent="phishing_email"))
    )


def test_topic_does_not_change_the_fingerprint():
    assert (
        room_fingerprint(_room())
        == room_fingerprint(_room(topic="passwords"))
    )


def test_fingerprint_is_stable_across_calls():
    room = _room()

    assert room_fingerprint(room) == room_fingerprint(room)
