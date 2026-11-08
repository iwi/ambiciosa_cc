import { useId, useState, type ReactNode } from "react";
import { FACE_SYMBOLS } from "../lib/format";
import { DEFAULT_SCORING, isDefaultScoring, SCORE_FIELDS, SCORE_LIMIT, scoringErrors, type Scoring } from "../lib/scoring";
import { DiceRow } from "./Dice";
import type { Field, FormValues } from "../lib/schemaForm";
import type { Rules, Strategy } from "../lib/types";

export function FieldRow({ label, help, error, children, htmlFor }: {
  label: string;
  help?: string;
  error?: string;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className={`field ${error ? "has-error" : ""}`}>
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {error ? <p className="field-error">{error}</p> : help ? <p className="field-help">{help}</p> : null}
    </div>
  );
}

/** Inputs generated from a strategy type's parameter schema. */
export function SchemaFields({ fields, values, errors, onChange }: {
  fields: Field[];
  values: FormValues;
  errors: Record<string, string>;
  onChange: (values: FormValues) => void;
}) {
  const base = useId();
  return (
    <>
      {fields.map((f) => {
        const id = `${base}-${f.key}`;
        const set = (v: string | boolean) => onChange({ ...values, [f.key]: v });
        const help = f.help;
        let input: ReactNode;
        if (f.kind === "choice") {
          input = (
            <select id={id} value={String(values[f.key] ?? "")} onChange={(e) => set(e.target.value)}>
              {f.choices?.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          );
        } else if (f.kind === "boolean") {
          input = <input id={id} type="checkbox" checked={Boolean(values[f.key])} onChange={(e) => set(e.target.checked)} />;
        } else {
          input = (
            <input
              id={id}
              type={f.kind === "text" ? "text" : "number"}
              inputMode={f.kind === "integer" ? "numeric" : f.kind === "number" ? "decimal" : undefined}
              step={f.kind === "integer" ? 1 : f.kind === "number" ? "any" : undefined}
              min={f.min}
              max={f.max}
              value={String(values[f.key] ?? "")}
              placeholder={f.optional ? "none" : undefined}
              onChange={(e) => set(e.target.value)}
            />
          );
        }
        return (
          <FieldRow key={f.key} label={f.label} help={help} error={errors[f.key]} htmlFor={id}>
            {input}
          </FieldRow>
        );
      })}
    </>
  );
}

export const DEFAULT_RULES: Rules = { target: 1000, end_rule: "first_to_target", max_turns: 500, face_weights: null, scoring: null };

/** Game rules shared by Play and Simulate. */
export function RulesFields({ rules, onChange }: { rules: Rules; onChange: (r: Rules) => void }) {
  const id = useId();
  return (
    <fieldset className="rules">
      <legend>Rules</legend>
      <div className="field-grid">
        <FieldRow label="Target" htmlFor={`${id}-t`} help="Points needed to win">
          <input id={`${id}-t`} type="number" min={1} step={1} value={rules.target}
            onChange={(e) => onChange({ ...rules, target: Number(e.target.value) })} />
        </FieldRow>
        <FieldRow label="Game ends" htmlFor={`${id}-e`}
          help={rules.end_rule === "first_to_target" ? "As soon as someone reaches the target" : "After the round is finished, so everyone has the same turns"}>
          <select id={`${id}-e`} value={rules.end_rule}
            onChange={(e) => onChange({ ...rules, end_rule: e.target.value as Rules["end_rule"] })}>
            <option value="first_to_target">First to the target</option>
            <option value="equal_turns">Equal turns</option>
          </select>
        </FieldRow>
        <FieldRow label="Turn limit" htmlFor={`${id}-m`} help="Turns per player before the game stops unfinished">
          <input id={`${id}-m`} type="number" min={1} value={rules.max_turns}
            onChange={(e) => onChange({ ...rules, max_turns: Number(e.target.value) })} />
        </FieldRow>
      </div>
      <FaceWeights weights={rules.face_weights} onChange={(w) => onChange({ ...rules, face_weights: w })} />
      <ScoringFields scoring={rules.scoring} onChange={(sc) => onChange({ ...rules, scoring: sc })} />
    </fieldset>
  );
}

function FaceWeights({ weights, onChange }: { weights: number[] | null; onChange: (w: number[] | null) => void }) {
  const id = useId();
  const loaded = weights !== null;
  return (
    <div className="weights">
      <label className="check">
        <input type="checkbox" checked={loaded} onChange={(e) => onChange(e.target.checked ? [1, 1, 1, 1, 1, 1] : null)} />
        Loaded dice
      </label>
      {loaded && (
        <div className="weights-grid" role="group" aria-label="Face weights">
          {FACE_SYMBOLS.map((face, i) => (
            <label key={face} htmlFor={`${id}-${i}`} className="weight">
              <span className="weight-face">{face}</span>
              <input id={`${id}-${i}`} type="number" min={0} step={0.1} value={weights[i]}
                onChange={(e) => {
                  const next = [...weights];
                  next[i] = Number(e.target.value);
                  onChange(next);
                }} />
            </label>
          ))}
          <p className="field-help">Relative weights, the same for all three dice. Equal weights are fair dice.</p>
        </div>
      )}
    </div>
  );
}

/** "Change the scores": the six configurable values (decision 11). */
function ScoringFields({ scoring, onChange }: { scoring: Scoring | null; onChange: (s: Scoring | null) => void }) {
  const id = useId();
  const custom = scoring !== null;
  // Inputs keep their own text so a value can pass through "" or "-" while being typed.
  const [text, setText] = useState<Record<keyof Scoring, string>>(() => toText(scoring ?? DEFAULT_SCORING));
  const errors = custom ? scoringErrors(text) : {};
  const set = (key: keyof Scoring, value: string) => {
    const next = { ...text, [key]: value };
    setText(next);
    onChange(Object.fromEntries(SCORE_FIELDS.map((f) => [f.key, Number(next[f.key])])) as Scoring);
  };
  return (
    <div className="weights">
      <label className="check">
        <input type="checkbox" checked={custom} onChange={(e) => {
          if (e.target.checked) {
            onChange({ ...DEFAULT_SCORING });
            setText(toText(DEFAULT_SCORING));
          } else onChange(null);
        }} />
        Change the scores
      </label>
      {custom && (
        <div className="scoring-grid" role="group" aria-label="Scores">
          {SCORE_FIELDS.map((f) => (
            <label key={f.key} htmlFor={`${id}-${f.key}`} className={`score-field ${errors[f.key] ? "has-error" : ""}`}>
              <span className="score-label"><DiceRow dice={f.dice} />{f.label}</span>
              <input id={`${id}-${f.key}`} type="number" step={1} min={-SCORE_LIMIT} max={SCORE_LIMIT} required
                value={text[f.key]} onChange={(e) => set(f.key, e.target.value)} />
              {errors[f.key] && <span className="field-error">{errors[f.key]}</span>}
            </label>
          ))}
          <p className="field-help">
            Whole numbers from −10,000 to 10,000. Three of a kind uses its own value instead of the per-die values.
            Any throw that scores 0 or less ends the turn, whatever the values.
            <button type="button" className="link" onClick={() => { onChange({ ...DEFAULT_SCORING }); setText(toText(DEFAULT_SCORING)); }}>
              Reset to the standard scores
            </button>
          </p>
        </div>
      )}
    </div>
  );
}

function toText(s: Scoring): Record<keyof Scoring, string> {
  return Object.fromEntries(SCORE_FIELDS.map((f) => [f.key, String(s[f.key])])) as Record<keyof Scoring, string>;
}

export type SeatDraft = { name: string; player_type: "human" | "automated"; strategy_version_id: string };

/** The list of players: name, human or bot, and the bot's strategy. */
export function SeatsEditor({ seats, strategies, onChange, allowHumans }: {
  seats: SeatDraft[];
  strategies: Strategy[];
  onChange: (s: SeatDraft[]) => void;
  allowHumans: boolean;
}) {
  const id = useId();
  const update = (i: number, patch: Partial<SeatDraft>) =>
    onChange(seats.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const byId = new Map(strategies.map((s) => [s.strategy_version_id, s]));
  return (
    <fieldset className="seats">
      <legend>Players</legend>
      <ol className="seat-list">
        {seats.map((s, i) => (
          <li key={i} className="seat">
            <input aria-label={`Player ${i + 1} name`} value={s.name} maxLength={50}
              onChange={(e) => update(i, { name: e.target.value })} />
            {allowHumans && (
              <select aria-label={`Player ${i + 1} type`} value={s.player_type}
                onChange={(e) => update(i, { player_type: e.target.value as SeatDraft["player_type"] })}>
                <option value="human">Human</option>
                <option value="automated">Bot</option>
              </select>
            )}
            {s.player_type === "automated" ? (
              <select aria-label={`Player ${i + 1} strategy`} value={s.strategy_version_id}
                onChange={(e) => {
                  const old = byId.get(s.strategy_version_id);
                  const next = byId.get(e.target.value);
                  // Keep a custom name; follow the strategy when the name was just the old strategy's.
                  const rename = !s.name.trim() || (old && s.name === old.name);
                  update(i, { strategy_version_id: e.target.value, ...(rename && next ? { name: next.name } : {}) });
                }}>
                {strategies.map((st) => (
                  <option key={st.strategy_version_id} value={st.strategy_version_id}>{st.label}</option>
                ))}
              </select>
            ) : (
              <span className="seat-note">Makes their own decisions</span>
            )}
            <button type="button" className="quiet" disabled={seats.length <= 1}
              onClick={() => onChange(seats.filter((_, j) => j !== i))} aria-label={`Remove player ${i + 1}`}>
              Remove
            </button>
          </li>
        ))}
      </ol>
      <button type="button" className="quiet" id={`${id}-add`} disabled={seats.length >= 6 || strategies.length === 0}
        onClick={() => {
          const st = strategies[seats.length % strategies.length];
          onChange([...seats, { name: st.name, player_type: "automated", strategy_version_id: st.strategy_version_id }]);
        }}>
        Add player
      </button>
      <p className="field-help">Up to six players. The playing order is drawn at random for each game.</p>
    </fieldset>
  );
}

export function rulesBody(rules: Rules) {
  return {
    ...(rules.scoring && !isDefaultScoring(rules.scoring) ? { scoring: rules.scoring } : {}),
    target: rules.target,
    end_rule: rules.end_rule,
    max_turns: rules.max_turns,
    ...(rules.face_weights ? { face_weights: rules.face_weights } : {}),
  };
}

export function Notice({ kind = "error", children }: { kind?: "error" | "info"; children: ReactNode }) {
  return <p className={`notice notice-${kind}`} role={kind === "error" ? "alert" : "status"}>{children}</p>;
}
