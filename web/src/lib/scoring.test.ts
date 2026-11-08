import { describe, expect, it } from "vitest";
import { DEFAULT_SCORING, effect, isDefaultScoring, scoringErrors } from "./scoring";

describe("scoring helpers", () => {
  it("recognises the standard scores", () => {
    expect(isDefaultScoring(null)).toBe(true);
    expect(isDefaultScoring({ ...DEFAULT_SCORING })).toBe(true);
    expect(isDefaultScoring({ ...DEFAULT_SCORING, ace: 11 })).toBe(false);
  });

  it("describes what a throw does to the turn", () => {
    expect(effect(100)).toBe("+100");
    expect(effect(0)).toBe("0, the turn ends");
    expect(effect(-300)).toBe("−300, the turn scores −300");
  });

  it("explains unacceptable values", () => {
    const ok = { ace: "10", king: "-5", three_aces: "0", three_kings: "10000", three_tens: "-10000", three_nines: "7" };
    expect(scoringErrors(ok)).toEqual({});
    const bad = { ...ok, ace: "", king: "2.5", three_aces: "abc", three_kings: "10001" };
    expect(Object.keys(scoringErrors(bad)).sort()).toEqual(["ace", "king", "three_aces", "three_kings"]);
  });
});
