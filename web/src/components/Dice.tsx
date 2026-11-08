import { FACE_SYMBOLS } from "../lib/format";

// Faces 0-5 are 9 10 J Q K A. Their colour says what they do by default:
// A and K score, J and Q are neutral, 9 and 10 are the penalty faces.
const FACE_CLASS = ["face-danger", "face-danger", "face-plain", "face-plain", "face-score", "face-score"];
const FACE_NAME = ["nine", "ten", "jack", "queen", "king", "ace"];

export function Die({ face, size = "md", rolling = false, delay = 0 }: {
  face: number | null;
  size?: "sm" | "md" | "lg";
  rolling?: boolean;
  delay?: number;
}) {
  if (face === null) {
    return <span className={`die die-${size} die-empty`} aria-hidden="true" />;
  }
  return (
    <span
      className={`die die-${size} ${FACE_CLASS[face]} ${face === 1 ? "die-ten" : ""} ${rolling ? "die-rolling" : ""}`}
      style={rolling ? { animationDelay: `${delay}ms` } : undefined}
      role="img"
      aria-label={FACE_NAME[face]}
    >
      {FACE_SYMBOLS[face]}
    </span>
  );
}

export function DiceRow({ dice, size = "sm" }: { dice: number[]; size?: "sm" | "md" }) {
  return (
    <span className="dice-row">
      {dice.map((d, i) => (
        <Die key={i} face={d} size={size} />
      ))}
    </span>
  );
}

/** The leather tray in Play mode: three large dice and the score of the throw. */
export function DiceTray({ dice, rollKey, score, caption }: {
  dice: number[] | null;
  rollKey: number;
  score: number | null;
  caption: string;
}) {
  return (
    <div className="tray" aria-live="polite">
      <div className="tray-dice" key={rollKey}>
        {(dice ?? [null, null, null]).map((d, i) => (
          <Die key={i} face={d} size="lg" rolling={dice !== null} delay={i * 70} />
        ))}
      </div>
      <div className="tray-caption">
        {score !== null && (
          <span className={`tray-score ${score > 0 ? "pos" : score < 0 ? "neg" : "zero"}`}>
            {score > 0 ? `+${score}` : score < 0 ? `−${Math.abs(score)}` : "0"}
          </span>
        )}
        <span>{caption}</span>
      </div>
    </div>
  );
}
