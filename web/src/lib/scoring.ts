// Configurable scoring (decision 11). Defaults match ambiciosa.engine.scoring.DEFAULT_SCORING.

export type Scoring = {
  ace: number;
  king: number;
  three_aces: number;
  three_kings: number;
  three_tens: number;
  three_nines: number;
};

export const DEFAULT_SCORING: Scoring = {
  ace: 10,
  king: 5,
  three_aces: 100,
  three_kings: 50,
  three_tens: -100,
  three_nines: -300,
};

export const SCORE_LIMIT = 10_000;

// Face codes: 0 = 9, 1 = 10, 2 = J, 3 = Q, 4 = K, 5 = A.
export const SCORE_FIELDS: { key: keyof Scoring; label: string; dice: number[] }[] = [
  { key: "ace", label: "Each Ace", dice: [5] },
  { key: "king", label: "Each King", dice: [4] },
  { key: "three_aces", label: "Three Aces", dice: [5, 5, 5] },
  { key: "three_kings", label: "Three Kings", dice: [4, 4, 4] },
  { key: "three_tens", label: "Three 10s", dice: [1, 1, 1] },
  { key: "three_nines", label: "Three 9s", dice: [0, 0, 0] },
];

export function isDefaultScoring(s: Scoring | null | undefined): boolean {
  return !s || SCORE_FIELDS.every((f) => s[f.key] === DEFAULT_SCORING[f.key]);
}

/** What a throw worth `v` does to the turn. */
export function effect(v: number): string {
  if (v > 0) return `+${v}`;
  if (v === 0) return "0, the turn ends";
  return `−${Math.abs(v)}, the turn scores −${Math.abs(v)}`;
}

/** Check every value; returns a message per field that is not acceptable. */
export function scoringErrors(s: Record<keyof Scoring, string | number>): Partial<Record<keyof Scoring, string>> {
  const errors: Partial<Record<keyof Scoring, string>> = {};
  for (const f of SCORE_FIELDS) {
    const raw = String(s[f.key]).trim();
    const n = Number(raw);
    if (raw === "" || !Number.isFinite(n)) errors[f.key] = "Enter a whole number.";
    else if (!Number.isInteger(n)) errors[f.key] = "Enter a whole number.";
    else if (Math.abs(n) > SCORE_LIMIT) errors[f.key] = `Between −${SCORE_LIMIT.toLocaleString("en-GB")} and ${SCORE_LIMIT.toLocaleString("en-GB")}.`;
  }
  return errors;
}
