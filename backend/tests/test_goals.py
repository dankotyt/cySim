"""Unit tests for the goal predicate grammar."""
import pytest

from app.services.scenario_generation.goals import (
    GoalSyntaxError,
    evaluate_goal,
    parse_goal,
)


def test_conjunction_requires_every_literal():
    goal = parse_goal("report(m1) && report(w1)")

    assert not evaluate_goal(goal, set())
    assert not evaluate_goal(goal, {("report", "m1")})
    assert evaluate_goal(goal, {("report", "m1"), ("report", "w1")})


def test_disjunction_and_precedence():
    goal = parse_goal("report(m1) || dismiss(m1) && report(w1)")

    assert evaluate_goal(goal, {("report", "m1")})
    assert not evaluate_goal(goal, {("dismiss", "m1")})
    assert evaluate_goal(goal, {("dismiss", "m1"), ("report", "w1")})


def test_parentheses_override_precedence():
    goal = parse_goal("(report(m1) || dismiss(m1)) && report(w1)")

    assert not evaluate_goal(goal, {("report", "m1")})
    assert evaluate_goal(goal, {("report", "m1"), ("report", "w1")})


def test_negated_goal_is_true_before_any_action():
    goal = parse_goal("!download(m1)")

    assert evaluate_goal(goal, set())
    assert not evaluate_goal(goal, {("download", "m1")})


def test_literals_are_split_by_polarity():
    goal = parse_goal("report(m1) && !reply(m1)")

    assert goal.positive == {("report", "m1")}
    assert goal.negative == {("reply", "m1")}
    assert goal.literals == {("report", "m1"), ("reply", "m1")}


@pytest.mark.parametrize(
    "text",
    ["", "report", "report()", "report(m1) &&", "(report(m1)", "REPORT(m1)"],
)
def test_malformed_goals_are_rejected(text):
    with pytest.raises(GoalSyntaxError):
        parse_goal(text)
