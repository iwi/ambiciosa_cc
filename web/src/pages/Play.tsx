import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { DiceRow, DiceTray } from "../components/Dice";
import { DEFAULT_RULES, Notice, RulesFields, rulesBody, SeatsEditor, type SeatDraft } from "../components/Forms";
import { api } from "../lib/api";
import { END_REASON, int, signed } from "../lib/format";
import type { GameState, Rules, ThrowEvent, TurnView } from "../lib/types";
import { DEFAULT_SCORING, effect, isDefaultScoring, type Scoring } from "../lib/scoring";
import { useStrategies } from "../lib/useStrategies";

const BOT_DELAY = { slow: 1100, normal: 600, fast: 120 } as const;
type Speed = keyof typeof BOT_DELAY;

export default function Play() {
  const { strategies, error: loadError } = useStrategies();
  const [seats, setSeats] = useState<SeatDraft[] | null>(null);
  const [rules, setRules] = useState<Rules>(DEFAULT_RULES);
  const [seed, setSeed] = useState("");
  const [game, setGame] = useState<GameState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [unfinished, setUnfinished] = useState<Awaited<ReturnType<typeof api.liveGames>>>([]);

  useEffect(() => {
    if (!game) api.liveGames().then((g) => setUnfinished(g.filter((x) => x.status === "in_progress"))).catch(() => undefined);
  }, [game]);

  const resume = async (id: string) => {
    try {
      setGame(await api.game(id));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const endUnfinished = async (id: string) => {
    try {
      await api.abandon(id);
      setUnfinished((u) => u.filter((g) => g.game_id !== id));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  useEffect(() => {
    if (strategies && strategies.length && seats === null) {
      const bot = strategies.find((s) => s.name === "Stop at 30") ?? strategies[0];
      setSeats([
        { name: "You", player_type: "human", strategy_version_id: bot.strategy_version_id },
        { name: bot.name, player_type: "automated", strategy_version_id: bot.strategy_version_id },
      ]);
    }
  }, [strategies, seats]);

  const start = async () => {
    if (!seats) return;
    setError(null);
    try {
      const g = await api.createGame({
        ...rulesBody(rules),
        ...(seed.trim() ? { seed: Number(seed) } : {}),
        players: seats.map((s) => ({
          name: s.name.trim() || "Player",
          player_type: s.player_type,
          strategy_version_id: s.player_type === "automated" ? s.strategy_version_id : null,
        })),
      });
      setGame(g);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (game) {
    return <Table initial={game} onLeave={() => setGame(null)} onRematch={start} />;
  }

  return (
    <div className="page">
      <header className="page-head">
        <h1>Play</h1>
        <p className="lede">Throw three poker dice, build up points, and bank them before a bad throw wipes out the turn. First to the target wins.</p>
      </header>
      {loadError && <Notice>{loadError}</Notice>}
      {unfinished.length > 0 && (
        <section className="resume" aria-label="Unfinished games">
          <h2>Unfinished games</h2>
          <ul>
            {unfinished.map((g) => (
              <li key={g.game_id}>
                <span>{g.players.map((p) => `${p.name} ${int(p.score)}`).join(", ")}</span>
                <span className="sub">round {g.round_number}</span>
                <button className="primary" onClick={() => resume(g.game_id)}>Resume</button>
                <button className="quiet" onClick={() => endUnfinished(g.game_id)}>End it</button>
              </li>
            ))}
          </ul>
        </section>
      )}
      {strategies && seats && (
        <div className="setup-grid">
          <form className="setup" onSubmit={(e) => { e.preventDefault(); start(); }}>
            <SeatsEditor seats={seats} strategies={strategies} onChange={setSeats} allowHumans />
            <RulesFields rules={rules} onChange={setRules} />
            <details className="more">
              <summary>Seed</summary>
              <label className="inline">
                <span>Seed for this game</span>
                <input type="number" min={0} value={seed} placeholder="random" onChange={(e) => setSeed(e.target.value)} />
              </label>
              <p className="field-help">The same seed and players replay the same dice.</p>
            </details>
            {error && <Notice>{error}</Notice>}
            <div className="actions">
              <button type="submit" className="primary">Start game</button>
            </div>
          </form>
          <ScoringCard scoring={rules.scoring ?? DEFAULT_SCORING} />
        </div>
      )}
    </div>
  );
}

function ScoringCard({ scoring }: { scoring: Scoring }) {
  const s = scoring;
  const cls = (v: number) => (v > 0 ? "pos" : v < 0 ? "neg" : "");
  const perDieNote = s.ace <= 0 || s.king <= 0 ? "; a throw totalling 0 or less ends the turn" : "";
  const sign = (v: number) => (v < 0 ? `−${Math.abs(v)}` : `+${v}`);
  return (
    <aside className="scoring" aria-label="Scoring">
      <h2>Scoring{isDefaultScoring(s) ? "" : " in this game"}</h2>
      <table>
        <tbody>
          <tr><td><DiceRow dice={[5, 5, 5]} /></td><td className={`n ${cls(s.three_aces)}`}>{effect(s.three_aces)}</td></tr>
          <tr><td><DiceRow dice={[4, 4, 4]} /></td><td className={`n ${cls(s.three_kings)}`}>{effect(s.three_kings)}</td></tr>
          <tr><td><DiceRow dice={[5, 4, 2]} /></td><td className="n">{sign(s.ace)} per A, {sign(s.king)} per K{perDieNote}</td></tr>
          <tr><td><DiceRow dice={[2, 3, 2]} /></td><td className="n">0, the turn ends</td></tr>
          <tr><td><DiceRow dice={[1, 1, 1]} /></td><td className={`n ${cls(s.three_tens)}`}>{effect(s.three_tens)}</td></tr>
          <tr><td><DiceRow dice={[0, 0, 0]} /></td><td className={`n ${cls(s.three_nines)}`}>{effect(s.three_nines)}</td></tr>
        </tbody>
      </table>
    </aside>
  );
}

function Table({ initial, onLeave, onRematch }: { initial: GameState; onLeave: () => void; onRematch: () => void }) {
  const [game, setGame] = useState(initial);
  const [last, setLast] = useState<ThrowEvent | null>(null);
  const [rollKey, setRollKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const [speed, setSpeed] = useState<Speed>("normal");
  const [paused, setPaused] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const busyRef = useRef(false);

  const run = useCallback(async (action: () => Promise<void>) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }, []);

  const doThrow = useCallback(() => run(async () => {
    const r = await api.throwDice(game.game_id);
    setLast(r.event);
    setRollKey((k) => k + 1);
    setGame(r.state);
  }), [game.game_id, run]);

  const throwAgain = () => run(async () => {
    await api.decide(game.game_id, "CONTINUE");
    const r = await api.throwDice(game.game_id);
    setLast(r.event);
    setRollKey((k) => k + 1);
    setGame(r.state);
  });

  const bank = () => run(async () => {
    const r = await api.decide(game.game_id, "STOP");
    setGame(r.state);
  });

  const abandon = () => run(async () => {
    const r = await api.abandon(game.game_id);
    setGame(r.state);
  });

  const over = game.awaiting === "finished";
  const current = game.current_seat === null ? null : game.players[game.current_seat];
  const botTurn = !over && game.current_player_type === "automated";

  // Bots throw by themselves at a watchable pace.
  useEffect(() => {
    if (!botTurn || paused || busy || error) return;
    const t = window.setTimeout(doThrow, last === null ? 500 : BOT_DELAY[speed]);
    return () => window.clearTimeout(t);
  }, [botTurn, paused, busy, error, doThrow, speed, last, game]);

  const turn = game.current_turn;
  const caption = describe(last, game);
  const humanDeciding = !over && game.awaiting === "decision" && game.current_player_type === "human";
  const humanToThrow = !over && game.awaiting === "throw" && game.current_player_type === "human";

  return (
    <div className="page play">
      <header className="page-head row">
        <h1>Play</h1>
        <p className="round">
          {over ? "Game over" : `Round ${game.round_number}`} <span className="sub">of up to {int(game.max_turns)}, target {int(game.target)}</span>
        </p>
      </header>

      <div className="play-grid">
        <section className="play-main" aria-label="Table">
          <DiceTray dice={last?.throw.dice ?? null} rollKey={rollKey} score={last?.throw.score ?? null} caption={caption} />

          <div className="turn-line" aria-live="polite">
            {over ? (
              <Outcome game={game} />
            ) : (
              <>
                <span className="turn-who">{current?.name}</span>
                <span className="turn-total">
                  <span className="sub">Turn total</span> <strong>{int(turn?.points ?? 0)}</strong>
                </span>
                <span className="sub">
                  {current && `banked ${int(current.score)}, needs ${int(Math.max(0, game.target - current.score))}`}
                </span>
              </>
            )}
          </div>

          <div className="controls">
            {humanToThrow && <button className="primary big" onClick={doThrow} disabled={busy} autoFocus>Throw</button>}
            {humanDeciding && (
              <>
                <button className="primary big" onClick={bank} disabled={busy} autoFocus>Bank {int(turn?.points ?? 0)}</button>
                <button className="big" onClick={throwAgain} disabled={busy}>Throw again</button>
              </>
            )}
            {botTurn && (
              <div className="bot-controls">
                <span className="sub">{current?.name} is playing</span>
                <label className="inline">
                  <span>Speed</span>
                  <select value={speed} onChange={(e) => setSpeed(e.target.value as Speed)}>
                    <option value="slow">Slow</option>
                    <option value="normal">Normal</option>
                    <option value="fast">Fast</option>
                  </select>
                </label>
                <button className="quiet" onClick={() => setPaused((p) => !p)}>{paused ? "Resume" : "Pause"}</button>
                {paused && <button className="quiet" onClick={doThrow} disabled={busy}>Next throw</button>}
              </div>
            )}
            {over && (
              <>
                <button className="primary big" onClick={onRematch}>Play again</button>
                <button className="big" onClick={onLeave}>Change players</button>
              </>
            )}
          </div>
          {error && <Notice>{error}</Notice>}
          {!over && (
            <p className="leave">
              <button className="quiet" onClick={abandon} disabled={busy}>End this game</button>
              <span className="sub">It is saved with your runs as abandoned.</span>
            </p>
          )}
          {over && (
            <p className="leave sub">
              Saved with your runs. <Link to={`/analyse?run=${game.simulation_id}`}>See it in Analyse</Link>
            </p>
          )}
          <ScoringCard scoring={game.scoring} />
        </section>

        <aside className="play-side">
          <Scoreboard game={game} />
          <TurnLog game={game} />
        </aside>
      </div>
    </div>
  );
}

function describe(last: ThrowEvent | null, game: GameState): string {
  if (!last) return game.current_player_type === "human" ? "Your throw" : "Waiting for the first throw";
  const who = game.players[last.seat].name;
  const t = last.throw;
  if (last.turn_ended && last.turn) {
    const r = last.turn.end_reason;
    if (r === "bust_zero") return `${who} scored nothing; the turn is lost`;
    if (r === "bust_negative") return `${who} threw a penalty; the turn scores ${signed(t.score)}`;
    if (r === "reached_target") return `${who} reached the target`;
    if (r === "stop") return `${who} banks ${t.turn_points_after}`;
  }
  if (last.bot_decision) {
    return `${who}: turn total ${t.turn_points_after}, ${last.bot_decision.decision === "STOP" ? "banks" : "throws again"}`;
  }
  return `${who}: turn total ${t.turn_points_after}`;
}

function Outcome({ game }: { game: GameState }) {
  if (game.status === "abandoned") return <span className="outcome">Game ended early</span>;
  if (game.status === "unfinished") return <span className="outcome">Turn limit reached; no winner</span>;
  const names = game.winners.map((s) => game.players[s].name);
  const score = game.players[game.winners[0]].score;
  return (
    <span className="outcome">
      {names.length === 1 ? `${names[0]} wins` : `${names.join(" and ")} share the win`} with {int(score)}
    </span>
  );
}

function Scoreboard({ game }: { game: GameState }) {
  const winners = new Set(game.winners);
  return (
    <section className="scoreboard" aria-label="Scores">
      <ol>
        {game.play_order.map((seat) => {
          const p = game.players[seat];
          const share = Math.max(0, Math.min(1, p.score / game.target));
          const active = seat === game.current_seat && game.awaiting !== "finished";
          return (
            <li key={seat} className={`${active ? "active" : ""} ${winners.has(seat) ? "winner" : ""}`}
              aria-current={active ? "true" : undefined}>
              <div className="sb-name">
                <span>{p.name}</span>
                <span className="sub">{p.player_type === "human" ? "Human" : p.strategy?.name}</span>
              </div>
              <div className={`sb-score ${p.score < 0 ? "neg" : ""}`}>{int(p.score)}</div>
              <div className="sb-track" aria-hidden="true"><span style={{ width: `${share * 100}%` }} /></div>
              <div className="sb-meta sub">{p.turns_taken} turns, {p.busts} lost</div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function TurnLog({ game }: { game: GameState }) {
  const turns: TurnView[] = [...game.history].reverse();
  if (game.current_turn && game.current_turn.throws.length) turns.unshift(game.current_turn);
  return (
    <section className="log" aria-label="Recent turns">
      <h2>Recent turns</h2>
      {turns.length === 0 && <p className="sub">Nothing thrown yet.</p>}
      <ol>
        {turns.slice(0, 12).map((t) => {
          const p = game.players[t.seat];
          const live = t.end_reason === null;
          return (
            <li key={`${t.seat}-${t.turn_number}`} className={live ? "live" : ""}>
              <div className="log-head">
                <span className="log-who">{p.name}</span>
                <span className="sub">turn {t.turn_number}</span>
                <span className={`log-result ${(t.turn_score ?? 0) < 0 ? "neg" : ""}`}>
                  {live ? `${t.points} so far` : `${signed(t.turn_score ?? 0)}, ${END_REASON[t.end_reason ?? ""] ?? ""}`}
                </span>
              </div>
              <ul className="log-throws">
                {t.throws.map((th) => (
                  <li key={th.throw_number}>
                    <DiceRow dice={th.dice} />
                    <span className="log-score">{signed(th.score)}</span>
                    {th.decision && p.player_type === "automated" && th.reason && (
                      <span className="log-reason">{th.decision === "STOP" ? "Banks" : "Continues"}: {th.reason}</span>
                    )}
                  </li>
                ))}
              </ul>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

