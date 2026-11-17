"""L0-L3 invariants for generated rooms."""
from app.models.scenario import Room
from app.services.scenario_generation.registry import (
    Artifact,
    ArtifactRegistry,
    ArtifactRisk,
    GenerationResources,
    Lesson,
    LessonCatalog,
)
from app.services.scenario_generation.validators import validate_room
from tests.fakes import VALID_ROOM


def _room(**overrides) -> Room:
    return Room.model_validate({**VALID_ROOM, **overrides})


def _codes(result) -> set[str]:
    return {problem.code for problem in result.problems}


def _custom_resources(artifacts: list[Artifact]) -> GenerationResources:
    lesson = Lesson(id="L_TEST", title="Урок", text="Текст урока.")
    return GenerationResources(
        artifacts=ArtifactRegistry(artifacts),
        lessons=LessonCatalog([lesson]),
    )


def test_valid_room_passes_every_level():
    from app.services.scenario_generation.registry import get_resources

    result = validate_room(
        _room(), intent="attachment_macro", benign=False, resources=get_resources()
    )

    assert result.ok, result.summary()


def test_unsupported_contract_version_is_l0():
    from app.services.scenario_generation.registry import get_resources

    result = validate_room(
        _room(v=4), intent="attachment_macro", benign=False, resources=get_resources()
    )

    assert "unsupported_version" in _codes(result)


def test_unknown_ref_is_l1():
    from app.services.scenario_generation.registry import get_resources

    result = validate_room(
        _room(objs=[{"id": "o1", "kind": "email", "ref": "fx:email:nope"}]),
        intent="attachment_macro",
        benign=False,
        resources=get_resources(),
    )

    assert "unknown_ref" in _codes(result)


def test_kind_mismatch_is_l1():
    from app.services.scenario_generation.registry import get_resources

    result = validate_room(
        _room(objs=[{"id": "o1", "kind": "site", "ref": "fx:email:em-0001"}]),
        intent="attachment_macro",
        benign=False,
        resources=get_resources(),
    )

    assert "kind_mismatch" in _codes(result)


def test_goal_verb_must_be_available_on_kind():
    from app.services.scenario_generation.registry import get_resources

    room = _room(
        objs=[{"id": "o1", "kind": "site", "ref": "fx:site:s-0001"}],
        goal="reply(o1)",
    )
    result = validate_room(room, intent="attachment_macro", benign=False, resources=get_resources())

    assert "goal_bad_verb" in _codes(result)


def test_via_index_must_exist():
    from app.services.scenario_generation.registry import get_resources

    room = _room(
        objs=[
            {"id": "o1", "kind": "email", "ref": "fx:email:em-0001"},
            {
                "id": "w1",
                "kind": "site",
                "ref": "fx:site:s-0001",
                "via": "o1:link:0",
            },
        ]
    )
    result = validate_room(room, intent="attachment_macro", benign=False, resources=get_resources())

    assert "via_bad_index" in _codes(result)


def test_via_target_must_match_link():
    from app.services.scenario_generation.registry import get_resources

    room = _room(
        objs=[
            {"id": "o1", "kind": "email", "ref": "fx:email:em-0002"},
            {
                "id": "w1",
                "kind": "site",
                "ref": "fx:site:s-0003",
                "via": "o1:link:0",
            },
        ]
    )
    result = validate_room(room, intent="attachment_macro", benign=False, resources=get_resources())

    assert "via_mismatch" in _codes(result)


def test_room_must_be_grounded_in_rule_topic():
    from app.services.scenario_generation.registry import get_resources

    room = _room(
        objs=[{"id": "o1", "kind": "site", "ref": "fx:site:s-0001"}],
        goal="report(o1)",
    )
    result = validate_room(room, intent="usb_found", benign=False, resources=get_resources())

    assert "ungrounded_trap" in _codes(result)
    assert "ungrounded_room" in _codes(result)


def test_reporting_a_benign_object_is_rejected():
    from app.services.scenario_generation.registry import get_resources

    room = _room(
        objs=[{"id": "o1", "kind": "site", "ref": "fx:site:s-0003"}],
        goal="report(o1)",
    )
    result = validate_room(room, intent="attachment_macro", benign=True, resources=get_resources())

    assert "report_on_benign" in _codes(result)
    assert "no_required_action" in _codes(result)


def test_goal_cannot_hold_before_any_action():
    from app.services.scenario_generation.registry import get_resources

    result = validate_room(
        _room(goal="!report(o1)"),
        intent="attachment_macro",
        benign=False,
        resources=get_resources(),
    )

    assert "goal_trivially_true" in _codes(result)


def test_goal_cannot_require_a_hard_trap():
    from app.services.scenario_generation.registry import get_resources

    result = validate_room(
        _room(goal="download(o1) && report(o1)"),
        intent="attachment_macro",
        benign=False,
        resources=get_resources(),
    )

    assert "goal_blocked_by_trap" in _codes(result)


def test_malicious_artifact_needs_a_hard_trap():
    resources = _custom_resources(
        [
            Artifact(
                id="x1",
                kind="email",
                benign=False,
                intents=["attachment_macro"],
                title="Без ловушки",
            )
        ]
    )
    room = _room(objs=[{"id": "o1", "kind": "email", "ref": "fx:email:x1"}])

    result = validate_room(room, intent="attachment_macro", benign=False, resources=resources)

    assert "malicious_without_hard" in _codes(result)


def test_benign_artifact_cannot_have_a_hard_trap():
    resources = _custom_resources(
        [
            Artifact(
                id="x2",
                kind="site",
                benign=True,
                intents=["attachment_macro"],
                title="Легитимный с ловушкой",
                risk=[
                    ArtifactRisk(
                        on="submit", level="hard", pen=10, lesson="L_TEST"
                    )
                ],
            )
        ]
    )
    room = _room(
        objs=[{"id": "o1", "kind": "site", "ref": "fx:site:x2"}],
        goal="dismiss(o1)",
    )

    result = validate_room(room, intent="attachment_macro", benign=True, resources=resources)

    assert "benign_with_hard" in _codes(result)


def test_goal_uses_the_action_declared_by_the_artifact():
    from app.services.scenario_generation.registry import get_resources

    resources = get_resources()
    objects = [{"id": "o1", "kind": "door", "ref": "fx:door:dr-0003"}]

    wrong = _room(
        intent="visitor_handling",
        objs=objects,
        goal="escort(o1)",
    )
    result = validate_room(
        wrong, intent="visitor_handling", benign=False, resources=resources
    )
    assert "no_required_action" in _codes(result)

    right = _room(
        intent="visitor_handling",
        objs=objects,
        goal="report(o1)",
    )
    result = validate_room(
        right, intent="visitor_handling", benign=False, resources=resources
    )
    assert result.ok, result.summary()
