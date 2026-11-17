"""Event engine: outcomes, penalties and the blind-burst rule."""
from datetime import datetime, timedelta, timezone

from app.models.scenario import AttemptEvent, Room
from app.services.scenario_generation.registry import get_resources
from app.services.scenario_generation.scoring import EventEngine

BASE = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def _room(
    ref: str = "fx:email:em-0001",
    kind: str = "email",
    goal: str = "report(o1)",
    diff: int = 2,
) -> Room:
    return Room(
        v=1,
        title="Тестовая комната",
        brief="На рабочую почту пришло письмо с вложением. Что вы сделаете?",
        diff=diff,
        topic="phishing",
        objs=[{"id": "o1", "kind": kind, "ref": ref}],
        goal=goal,
    )


def _events(*specs: tuple[str, str], gap: float = 5.0) -> list[AttemptEvent]:
    """Build an event log with a fixed interval between actions."""
    return [
        AttemptEvent(
            verb=verb,
            obj=obj,
            at=BASE + timedelta(seconds=gap * index),
        )
        for index, (verb, obj) in enumerate(specs)
    ]


def _engine(room: Room) -> EventEngine:
    return EventEngine(room, get_resources().artifacts)


def test_goal_with_inspection_is_a_full_score():
    evaluation = _engine(_room()).evaluate(
        _events(("inspect", "o1"), ("report", "o1"))
    )

    assert evaluation.outcome == "safe"
    assert evaluation.score == 14
    assert evaluation.blind is False
    assert evaluation.lessons == ()


def test_slow_first_correct_answer_is_not_blind():
    evaluation = _engine(_room()).evaluate(_events(("report", "o1")))

    assert evaluation.outcome == "safe"
    assert evaluation.blind is False
    assert evaluation.score == 14


def test_rapid_clicking_without_inspection_loses_blind_points():
    evaluation = _engine(_room()).evaluate(
        _events(("open", "o1"), ("click", "o1"), ("report", "o1"), gap=0.5)
    )

    assert evaluation.outcome == "safe"
    assert evaluation.blind is True
    assert evaluation.score == 12


def test_a_burst_with_inspection_is_not_blind():
    evaluation = _engine(_room()).evaluate(
        _events(("inspect", "o1"), ("report", "o1"), gap=0.2)
    )

    assert evaluation.outcome == "safe"
    assert evaluation.blind is False
    assert evaluation.score == 14


def test_soft_trap_costs_points_but_goal_still_completes():
    evaluation = _engine(_room()).evaluate(
        _events(("inspect", "o1"), ("reply", "o1"), ("report", "o1"))
    )

    assert evaluation.outcome == "recovered"
    assert evaluation.score == 12
    assert evaluation.lessons == ("L_REPLY_TO",)


def test_hard_trap_ends_the_room_with_one_point():
    evaluation = _engine(_room()).evaluate(
        _events(("inspect", "o1"), ("download", "o1"))
    )

    assert evaluation.outcome == "failed"
    assert evaluation.score == 1
    assert evaluation.lessons == ("L_ATTACH_LNK",)


def test_reporting_a_benign_object_is_a_soft_trap():
    room = _room(ref="fx:site:s-0003", kind="site", goal="dismiss(o1)")

    evaluation = _engine(room).evaluate(
        _events(("inspect", "o1"), ("report", "o1"), ("dismiss", "o1"))
    )

    assert evaluation.outcome == "recovered"
    assert evaluation.lessons == ("L_FALSE_POSITIVE",)
    assert evaluation.score == 12


def test_benign_goal_without_inspection_is_blind_on_a_burst():
    room = _room(ref="fx:site:s-0003", kind="site", goal="dismiss(o1)")

    evaluation = _engine(room).evaluate(
        _events(("open", "o1"), ("click", "o1"), ("dismiss", "o1"), gap=0.5)
    )

    assert evaluation.outcome == "safe"
    assert evaluation.blind is True
    assert evaluation.score == 12


def test_unknown_object_is_neutral_and_does_not_close_the_room():
    evaluation = _engine(_room()).evaluate(_events(("report", "ghost")))

    assert evaluation.outcome == "in_progress"
    assert evaluation.score is None
    assert evaluation.events[0].level is None


def test_repeated_event_is_penalised_once():
    evaluation = _engine(_room()).evaluate(
        _events(("report", "o1"), ("report", "o1"))
    )

    assert len(evaluation.events) == 1
    assert evaluation.score == 14


def test_events_after_a_hard_trap_are_ignored():
    evaluation = _engine(_room()).evaluate(
        _events(("download", "o1"), ("inspect", "o1"), ("report", "o1"))
    )

    assert evaluation.outcome == "failed"
    assert evaluation.score == 1
    assert [event.verb for event in evaluation.events] == ["download"]


def test_higher_difficulty_raises_max_points():
    evaluation = _engine(_room(diff=5)).evaluate(
        _events(("inspect", "o1"), ("report", "o1"))
    )

    assert evaluation.max_points == 20
    assert evaluation.score == 20
