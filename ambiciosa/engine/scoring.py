"""Scoring of a single throw (spec section 2.2, decisions 4, 11 and 12).

Default rules:
  three Aces   +100    three Kings  +50
  three 10s    -100    three 9s     -300
  otherwise    +10 per Ace and +5 per King (0 if neither)

Every one of those six values can be changed per game (decision 11) with a
`Scoring`. What stays fixed: special combinations take precedence over
per-die scoring, three Jacks and three Queens are not special, and any
other throw without Aces or Kings scores 0.

There are only 6**3 = 216 ordered throws, so each `Scoring` precomputes
every score into a table indexed by 36*d1 + 6*d2 + d3 using the Face codes;
a custom scoring is exactly as fast as the default.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields

from .dice import Face, Throw

SCORE_LIMIT = 10_000  # each value within ±10,000, so a throw always fits the SMALLINT throw_score column


@dataclass(frozen=True)
class Scoring:
    """The configurable points of each scoring combination."""

    ace: int = 10            # each Ace, when the throw is not a special combination
    king: int = 5            # each King, likewise
    three_aces: int = 100
    three_kings: int = 50
    three_tens: int = -100
    three_nines: int = -300
    table: tuple[int, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        for f in fields(self):
            if f.name == "table":
                continue
            value = getattr(self, f.name)
            if isinstance(value, bool) or not isinstance(value, int):
                if isinstance(value, float) and value.is_integer():
                    object.__setattr__(self, f.name, int(value))
                    value = int(value)
                else:
                    raise ValueError(f"score {f.name!r} must be a whole number, got {value!r}")
            if not -SCORE_LIMIT <= value <= SCORE_LIMIT:
                raise ValueError(f"score {f.name!r} must be between {-SCORE_LIMIT} and {SCORE_LIMIT}, got {value}")
        object.__setattr__(self, "table", tuple(
            self._score_rule(Face(a), Face(b), Face(c)) for a in range(6) for b in range(6) for c in range(6)
        ))

    @property
    def specials(self) -> dict[Face, int]:
        return {Face.ACE: self.three_aces, Face.KING: self.three_kings,
                Face.TEN: self.three_tens, Face.NINE: self.three_nines}

    def _score_rule(self, d1: Face, d2: Face, d3: Face) -> int:
        specials = self.specials
        if d1 == d2 == d3 and d1 in specials:
            return specials[d1]
        dice = (d1, d2, d3)
        return self.ace * dice.count(Face.ACE) + self.king * dice.count(Face.KING)

    def score(self, throw: Throw) -> int:
        a, b, c = throw
        return self.table[36 * a + 6 * b + c]

    def as_dict(self) -> dict[str, int]:
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "table"}

    @property
    def is_default(self) -> bool:
        return self == DEFAULT_SCORING

    @classmethod
    def from_dict(cls, data: dict[str, int] | None) -> Scoring:
        if not data:
            return DEFAULT_SCORING
        unknown = set(data) - {f.name for f in fields(cls) if f.name != "table"}
        if unknown:
            raise ValueError(f"unknown score names {sorted(unknown)}; known: ace, king, three_aces, three_kings, "
                             "three_tens, three_nines")
        return cls(**data)


DEFAULT_SCORING = Scoring()

# Kept for the default rules, as before.
ACE_POINTS = DEFAULT_SCORING.ace
KING_POINTS = DEFAULT_SCORING.king
SPECIALS: dict[Face, int] = DEFAULT_SCORING.specials
SCORE_TABLE: tuple[int, ...] = DEFAULT_SCORING.table


def score_throw(throw: Throw, scoring: Scoring = DEFAULT_SCORING) -> int:
    """Score one throw of three dice (default rules unless a Scoring is given)."""
    a, b, c = throw
    return scoring.table[36 * a + 6 * b + c]
