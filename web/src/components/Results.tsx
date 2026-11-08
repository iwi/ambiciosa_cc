import { int, num, pct } from "../lib/format";
import type { Stats } from "../lib/types";

/** Headline numbers per player for one run. */
export function SummaryTable({ stats }: { stats: Stats }) {
  const { overview, players } = stats;
  const best = Math.max(...players.map((p) => p.win_rate));
  return (
    <div className="summary">
      <table className="data">
        <caption>
          {int(overview.games)} games, {int(overview.finished)} finished
          {overview.unfinished ? `, ${int(overview.unfinished)} stopped at the turn limit` : ""}
          {overview.shared_wins ? `, ${int(overview.shared_wins)} shared wins` : ""}
          {overview.mean_rounds !== null ? `; ${num(overview.mean_rounds, 1)} rounds on average` : ""}
        </caption>
        <thead>
          <tr>
            <th scope="col">Player</th>
            <th scope="col" className="n">Win rate</th>
            <th scope="col" className="n">Wins</th>
            <th scope="col" className="n">Turns to win</th>
            <th scope="col" className="n">Points per turn</th>
            <th scope="col" className="n">Throws per turn</th>
            <th scope="col" className="n">Bust rate</th>
          </tr>
        </thead>
        <tbody>
          {players.map((p) => (
            <tr key={p.seat} className={p.win_rate === best && players.length > 1 ? "leader" : undefined}>
              <th scope="row">
                <span className="who">{p.display_name}</span>
                {p.strategy_name && p.strategy_name !== p.display_name && (
                  <span className="sub">{p.strategy_name}{p.strategy_version && p.strategy_version > 1 ? ` (v${p.strategy_version})` : ""}</span>
                )}
                {!p.strategy_name && <span className="sub">Human</span>}
              </th>
              <td className="n">
                <span className="bar" style={{ ["--w" as string]: `${p.win_rate * 100}%` }}>{pct(p.win_rate)}</span>
              </td>
              <td className="n">{Number.isInteger(p.wins) ? int(p.wins) : num(p.wins, 1)}</td>
              <td className="n">{num(p.mean_turns_to_win, 1)}</td>
              <td className="n">{num(p.points_per_turn)}</td>
              <td className="n">{num(p.throws_per_turn)}</td>
              <td className="n">{pct(p.bust_rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
