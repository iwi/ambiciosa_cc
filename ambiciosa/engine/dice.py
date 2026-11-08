"""Poker dice and the sources that roll them.

Random number generation is kept apart from scoring: the game only asks a
`DiceSource` for the next throw, so tests can supply predetermined throws
with `ScriptedDice`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from enum import IntEnum
from typing import Protocol

import numpy as np


class Face(IntEnum):
    """The six faces of a poker die. The integer codes are stored in the database.

    Codes 0 and 1 were the 7 and the 8 until decision 12 renamed them 9 and 10;
    the codes, and so stored games, are unchanged.
    """

    NINE = 0
    TEN = 1
    JACK = 2
    QUEEN = 3
    KING = 4
    ACE = 5

    @property
    def symbol(self) -> str:
        return _SYMBOLS[self]

    @classmethod
    def from_symbol(cls, symbol: str) -> Face:
        try:
            return _FROM_SYMBOL[symbol.upper()]
        except KeyError:
            raise ValueError(f"unknown face symbol {symbol!r}; expected one of 9 10 (or T) J Q K A") from None


_SYMBOLS = {
    Face.NINE: "9",
    Face.TEN: "10",
    Face.JACK: "J",
    Face.QUEEN: "Q",
    Face.KING: "K",
    Face.ACE: "A",
}
_FROM_SYMBOL = {v: k for k, v in _SYMBOLS.items()} | {"T": Face.TEN}

Throw = tuple[Face, Face, Face]


_TOKEN = re.compile(r"10|\S")


def parse_throw(text: str) -> Throw:
    """Parse a compact throw such as "AAK", "9TQ" or "9 10 Q" (useful in tests); T stands for 10."""
    symbols = _TOKEN.findall(text)
    if len(symbols) != 3:
        raise ValueError(f"a throw needs exactly three dice, got {text!r}")
    return tuple(Face.from_symbol(s) for s in symbols)  # type: ignore[return-value]


class DiceSource(Protocol):
    def roll(self) -> Throw: ...


def normalise_weights(weights: Sequence[float] | None) -> tuple[float, ...]:
    """Validate face weights (order: 9, 10, J, Q, K, A) and scale them to sum to 1."""
    if weights is None:
        return (1 / 6,) * 6
    w = tuple(float(x) for x in weights)
    if len(w) != 6:
        raise ValueError(f"need one weight per face (6), got {len(w)}")
    if any(not np.isfinite(x) or x < 0 for x in w):
        raise ValueError("face weights must be finite and non-negative")
    total = sum(w)
    if total <= 0:
        raise ValueError("at least one face weight must be positive")
    return tuple(x / total for x in w)


_FACES: tuple[Face, ...] = tuple(Face)


class RandomDice:
    """Three dice with shared face weights, driven by a seeded NumPy generator.

    When the dice own their generator (built from a seed), faces are drawn in
    blocks of `BLOCK` throws, which avoids NumPy's per-call overhead. NumPy
    produces the same values whether they are drawn three at a time or in a
    block, so the throws are identical either way; only the generator's
    internal position runs ahead, which is harmless because nothing else
    draws from it. A generator passed in by the caller may be shared, so it is
    always drawn from one throw at a time.
    """

    BLOCK = 256  # throws per block draw

    def __init__(
        self,
        seed: int | np.random.SeedSequence | np.random.Generator,
        weights: Sequence[float] | None = None,
    ) -> None:
        shared = isinstance(seed, np.random.Generator)
        self._rng = seed if shared else np.random.default_rng(seed)
        self.weights = normalise_weights(weights)
        self._uniform = all(abs(x - 1 / 6) < 1e-12 for x in self.weights)
        self._p = np.array(self.weights)
        self._block = 1 if shared else self.BLOCK
        self._buffer: list[int] = []
        self._pos = 0

    def _refill(self) -> None:
        n = 3 * self._block
        if self._uniform:
            codes = self._rng.integers(0, 6, size=n)
        else:
            codes = self._rng.choice(6, size=n, p=self._p)
        self._buffer = codes.tolist()
        self._pos = 0

    def roll(self) -> Throw:
        if self._pos >= len(self._buffer):
            self._refill()
        i = self._pos
        self._pos = i + 3
        b = self._buffer
        return (_FACES[b[i]], _FACES[b[i + 1]], _FACES[b[i + 2]])


class ScriptedDice:
    """Returns predetermined throws in order; raises if the script runs out."""

    def __init__(self, throws: Iterable[Throw | str]) -> None:
        self._throws = [parse_throw(t) if isinstance(t, str) else tuple(t) for t in throws]
        self._next = 0

    def roll(self) -> Throw:
        if self._next >= len(self._throws):
            raise RuntimeError(f"ScriptedDice exhausted after {len(self._throws)} throws")
        throw = self._throws[self._next]
        self._next += 1
        return throw  # type: ignore[return-value]

    @property
    def remaining(self) -> int:
        return len(self._throws) - self._next
