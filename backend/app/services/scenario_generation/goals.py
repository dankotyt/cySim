"""Parser and evaluator for room goal predicates.

Grammar (ADR-0008 / room contract v1)::

    expr    := term ( "||" term )*
    term    := factor ( "&&" factor )*
    factor  := "!" factor | "(" expr ")" | literal
    literal := verb "(" obj ")"

The goal is monotone: facts are never retracted, so evaluation only needs the
set of already performed ``(verb, object)`` pairs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_TOKEN_RE = re.compile(
    r"\s*(?:(?P<op>&&|\|\||!|\(|\))|(?P<lit>[a-z_]+\([A-Za-z0-9_-]+\)))"
)
_LITERAL_RE = re.compile(r"(?P<verb>[a-z_]+)\((?P<obj>[A-Za-z0-9_-]+)\)")

Literal = tuple[str, str]


class GoalSyntaxError(ValueError):
    """Raised when a goal predicate cannot be parsed."""


@dataclass(frozen=True)
class Goal:
    """A parsed goal predicate with its literals split by polarity."""

    text: str
    ast: Any
    literals: frozenset[Literal]
    positive: frozenset[Literal]
    negative: frozenset[Literal]


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    position = 0
    stripped = text.strip()
    while position < len(stripped):
        match = _TOKEN_RE.match(stripped, position)
        if match is None or match.end() == position:
            raise GoalSyntaxError(
                f"unexpected character {stripped[position]!r} at {position}"
            )
        if match.group("op") is not None:
            tokens.append(("op", match.group("op")))
        else:
            tokens.append(("lit", match.group("lit")))
        position = match.end()
    return tokens


class _Parser:
    """Recursive-descent parser over the token list."""

    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self._tokens = tokens
        self._index = 0

    def parse(self) -> Any:
        node = self._expr()
        if self._index != len(self._tokens):
            raise GoalSyntaxError("unexpected trailing tokens")
        return node

    def _peek(self) -> str | None:
        if self._index >= len(self._tokens):
            return None
        kind, value = self._tokens[self._index]
        return value if kind == "op" else None

    def _advance(self) -> tuple[str, str]:
        if self._index >= len(self._tokens):
            raise GoalSyntaxError("unexpected end of goal")
        token = self._tokens[self._index]
        self._index += 1
        return token

    def _expr(self) -> Any:
        node = self._term()
        while self._peek() == "||":
            self._advance()
            node = ("or", node, self._term())
        return node

    def _term(self) -> Any:
        node = self._factor()
        while self._peek() == "&&":
            self._advance()
            node = ("and", node, self._factor())
        return node

    def _factor(self) -> Any:
        if self._peek() == "!":
            self._advance()
            return ("not", self._factor())
        if self._peek() == "(":
            self._advance()
            node = self._expr()
            if self._peek() != ")":
                raise GoalSyntaxError("missing closing parenthesis")
            self._advance()
            return node
        kind, value = self._advance()
        if kind != "lit":
            raise GoalSyntaxError(f"expected a verb(object) literal, got {value!r}")
        match = _LITERAL_RE.fullmatch(value)
        if match is None:
            raise GoalSyntaxError(f"malformed literal {value!r}")
        return ("lit", match.group("verb"), match.group("obj"))


def _split(ast: Any, negated: bool = False) -> tuple[set[Literal], set[Literal]]:
    """Walk the AST collecting literals under positive and negated contexts."""
    key = ast[0]
    if key == "lit":
        literal = (ast[1], ast[2])
        return ({literal} if not negated else set(), {literal} if negated else set())
    if key == "not":
        return _split(ast[1], not negated)
    positive: set[Literal] = set()
    negative: set[Literal] = set()
    for child in ast[1:]:
        child_positive, child_negative = _split(child, negated)
        positive |= child_positive
        negative |= child_negative
    return positive, negative


def parse_goal(text: str) -> Goal:
    """Parse ``text`` into a :class:`Goal`; raise :class:`GoalSyntaxError`."""
    if not text or not text.strip():
        raise GoalSyntaxError("goal is empty")
    node = _Parser(_tokenize(text)).parse()
    positive, negative = _split(node)
    return Goal(
        text=text,
        ast=node,
        literals=frozenset(positive | negative),
        positive=frozenset(positive),
        negative=frozenset(negative),
    )


def _evaluate_node(node: Any, performed: set[Literal]) -> bool:
    key = node[0]
    if key == "lit":
        return (node[1], node[2]) in performed
    if key == "not":
        return not _evaluate_node(node[1], performed)
    if key == "and":
        return _evaluate_node(node[1], performed) and _evaluate_node(
            node[2], performed
        )
    return _evaluate_node(node[1], performed) or _evaluate_node(node[2], performed)


def evaluate_goal(goal: Goal, performed: set[Literal]) -> bool:
    """Return ``True`` when ``performed`` satisfies the goal."""
    return _evaluate_node(goal.ast, performed)
