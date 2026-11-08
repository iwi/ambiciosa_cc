import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { END_REASON, int, signed } from "../../lib/format";
import type { Analysis, GameHistory, GameRow } from "../../lib/types";
import { DiceRow } from "../Dice";
import { Notice } from "../Forms";
import { SeatSwatch } from "./RunDetail";

const PAGE = 25;
const SORTS: [string, string][] = [["index", "In order"], ["longest", "Longest first"], ["shortest", "Shortest first"], ["closest", "Closest finish"]];

/** The games of a run, and the turn-by-turn record of the chosen one. */
export function GamesBrowser({ data }: { data: Analysis }) {
  const sim = data.simulation;
  const [winner, setWinner] = useState<number | null>(null);
  const [sort, setSort] = useState("index");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<{ total: number; games: GameRow[] } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.games(sim.simulation_id, { limit: PAGE, offset, winner, sort }).then((p) => {
      setPage(p);
      if (p.games.length && !p.games.some((g) => g.game_id === selected)) setSelected(p.games[0].game_id);
    }).catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sim.simulation_id, winner, sort, offset]);

  const names = sim.players.map((p) => p.name);

  return (
    <div className="games">
      <div className="list-head filters">
        <label className="inline"><span>Won by</span>
          <select value={winner ?? ""} onChange={(e) => { setOffset(0); setWinner(e.target.value === "" ? null : Number(e.target.value)); }}>
            <option value="">Anyone</option>
            {sim.players.map((p) => <option key={p.seat} value={p.seat}>{p.name}</option>)}
          </select>
        </label>
        <label className="inline"><span>Order</span>
          <select value={sort} onChange={(e) => { setOffset(0); setSort(e.target.value); }}>
            {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        {page && <span className="sub">{int(page.total)} games</span>}
      </div>
      {error && <Notice>{error}</Notice>}
      <div className="games-grid">
        <div>
          <div className="table-wrap">
            <table className="data games-table">
              <thead><tr><th scope="col" className="n">Game</th><th scope="col">Winner</th><th scope="col" className="n">Rounds</th><th scope="col">Final scores</th></tr></thead>
              <tbody>
                {page?.games.map((g) => (
                  <tr key={g.game_id} className={selected === g.game_id ? "selected" : undefined}>
                    <td className="n"><button className="link" onClick={() => setSelected(g.game_id)} aria-pressed={selected === g.game_id}>{g.game_index + 1}</button></td>
                    <td>{g.winners?.join(" and ") ?? (g.status === "unfinished" ? "None (turn limit)" : "None")}</td>
                    <td className="n">{int(g.n_rounds)}</td>
                    <td className="scores">{g.scores.map((s, i) => <span key={i} title={names[i]}>{int(s)}</span>)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {page && page.total > PAGE && (
            <div className="pager">
              <button className="quiet" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button>
              <span className="sub">{int(offset + 1)} to {int(Math.min(offset + PAGE, page.total))} of {int(page.total)}</span>
              <button className="quiet" disabled={offset + PAGE >= page.total} onClick={() => setOffset(offset + PAGE)}>Next</button>
            </div>
          )}
        </div>
        <div>{selected && <GameRecord key={selected} gameId={selected} level={sim.record_level} />}</div>
      </div>
    </div>
  );
}

function GameRecord({ gameId, level }: { gameId: string; level: string }) {
  const [h, setH] = useState<GameHistory | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.gameHistory(gameId).then(setH).catch((e) => setError(e.message));
  }, [gameId]);
  if (error) return <Notice>{error}</Notice>;
  if (!h) return <p className="sub">Loading game…</p>;
  const order = [...h.players].sort((a, b) => a.play_order - b.play_order);
  const name = (seat: number) => h.players.find((p) => p.seat === seat)!.display_name;
  return (
    <article className="game-record" aria-label={`Game ${h.game.game_index + 1}`}>
      <h3>Game {int(h.game.game_index + 1)}</h3>
      <ol className="record-players">
        {order.map((p) => (
          <li key={p.seat} className={p.is_winner ? "winner" : undefined}>
            <span><SeatSwatch seat={p.seat} />{p.display_name}{p.is_winner && <span className="tag">winner</span>}</span>
            <span className="sub">{p.turns_taken} turns, {p.total_throws} throws, {p.busts} lost</span>
            <strong>{int(p.final_score)}</strong>
          </li>
        ))}
      </ol>
      {level === "summary" ? (
        <p className="sub">This run kept totals only, so there is no turn-by-turn record. Run it again with more detail and the same seed to see this game's throws.</p>
      ) : (
        <ol className="record-turns">
          {h.turns.map((t) => (
            <li key={`${t.seat}-${t.turn_number}`}>
              <div className="log-head">
                <span className="log-who">{name(t.seat)}</span>
                <span className="sub">turn {t.turn_number}</span>
                <span className={`log-result ${t.turn_score < 0 ? "neg" : ""}`}>{signed(t.turn_score)}, {END_REASON[t.end_reason]}; total {int(t.banked_after)}</span>
              </div>
              {t.throws.length > 0 && (
                <ul className="log-throws">
                  {t.throws.map((th) => (
                    <li key={th.throw_number}>
                      <DiceRow dice={[th.die1, th.die2, th.die3]} />
                      <span className="log-score">{signed(th.throw_score)}</span>
                      {th.decision && <span className="log-reason">{th.decision === "STOP" ? "Banks" : "Continues"}{th.reason ? `: ${th.reason}` : ""}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ol>
      )}
    </article>
  );
}
