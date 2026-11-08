import { useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";
import { int, num, pct } from "../../lib/format";
import type { Comparison } from "../../lib/types";
import { Chart, type Series } from "../Chart";
import { Notice } from "../Forms";

const MAX_CHART_RUNS = 6; // one palette colour per run

/** Several runs side by side, and each strategy's result in each run (never pooled across runs). */
export function Compare({ ids }: { ids: string[] }) {
  const [data, setData] = useState<Comparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.compare(ids).then(setData).catch((e) => setError(e.message));
  }, [ids.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  const runs = data?.runs ?? [];
  const charted = runs.slice(0, MAX_CHART_RUNS);
  const label = (s: Comparison["strategies"][number]) => `${s.strategy_name}${s.strategy_version && s.strategy_version > 1 ? ` (v${s.strategy_version})` : ""}`;
  const strategies = data?.strategies ?? [];
  const multiRuns = charted.filter((r) => r.simulation.n_players > 1);

  // One bar per strategy and run it played in, so no empty slots; colour and legend show the run.
  const pairLabel = (s: Comparison["strategies"][number], run: Comparison["runs"][number]) =>
    `${label(s)}<br>${run.simulation.name}`;
  const pairs = (rs: Comparison["runs"]) =>
    strategies.flatMap((s) => rs.filter((r) => s.cells[r.simulation.simulation_id]).map((r) => pairLabel(s, r)));
  const pairSeries = (rs: Comparison["runs"], value: (c: Comparison["strategies"][number]["cells"][string]) => number | null,
    withCi = false): Series[] => rs.map((r) => {
    const i = runs.indexOf(r);
    const rows = strategies.filter((s) => s.cells[r.simulation.simulation_id] && value(s.cells[r.simulation.simulation_id]) !== null);
    const cells = rows.map((s) => s.cells[r.simulation.simulation_id]);
    return {
      name: r.simulation.name, kind: "bar" as const, color: i, x: rows.map((s) => pairLabel(s, r)),
      y: cells.map((c) => value(c)!),
      ...(withCi ? { errorLow: cells.map((c) => c.win_rate_low), errorHigh: cells.map((c) => c.win_rate_high) } : {}),
    };
  });

  const winSeries = useMemo(() => pairSeries(multiRuns, (c) => c.win_rate, true), [data]); // eslint-disable-line react-hooks/exhaustive-deps
  const turnsSeries = useMemo(() => pairSeries(charted, (c) => c.turns_to_target_mean), [data]); // eslint-disable-line react-hooks/exhaustive-deps
  const pptSeries = useMemo(() => pairSeries(charted, (c) => c.points_per_turn), [data]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <Notice>{error}</Notice>;
  if (!data) return <p className="sub">Loading comparison…</p>;
  const h = (rs: Comparison["runs"]) => Math.max(180, 52 * pairs(rs).length + 70);

  return (
    <div className="compare-view">
      <div className="table-wrap">
        <table className="data">
          <caption>Runs</caption>
          <thead><tr><th scope="col">Run</th><th scope="col" className="n">Games</th><th scope="col" className="n">Players</th>
            <th scope="col" className="n">Target</th><th scope="col">Game ends</th><th scope="col" className="n">Mean rounds</th><th scope="col">Seed</th></tr></thead>
          <tbody>{runs.map((r, i) => (
            <tr key={r.simulation.simulation_id}>
              <th scope="row">{i < MAX_CHART_RUNS && <span className="swatch" style={{ background: `var(--series-${i + 1})` }} aria-hidden="true" />}{r.simulation.name}</th>
              <td className="n">{int(r.overview.games)}</td><td className="n">{r.simulation.n_players}</td><td className="n">{int(r.simulation.target)}</td>
              <td>{r.simulation.end_rule === "equal_turns" ? "Equal turns" : "First to the target"}</td>
              <td className="n">{num(r.overview.mean_rounds, 1)}</td><td>{String(r.simulation.master_seed)}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      {runs.length > MAX_CHART_RUNS && <Notice kind="info">The charts show the first {MAX_CHART_RUNS} runs; the tables show all {runs.length}.</Notice>}

      <div className="table-wrap">
        <table className="data matrix">
          <caption>Each strategy in each run: win rate (95% interval), mean turns to reach the target, points per turn. A strategy's results depend on its opponents, so runs are not combined.</caption>
          <thead><tr><th scope="col">Strategy</th>{runs.map((r) => <th key={r.simulation.simulation_id} scope="col" className="n">{r.simulation.name}</th>)}</tr></thead>
          <tbody>{strategies.map((s) => (
            <tr key={s.strategy_version_id ?? s.strategy_name}>
              <th scope="row">{label(s)}</th>
              {runs.map((r) => {
                const c = s.cells[r.simulation.simulation_id];
                return (
                  <td key={r.simulation.simulation_id} className="n">
                    {c ? (
                      <>
                        {r.simulation.n_players > 1 && <span className="cell-main">{pct(c.win_rate)} <span className="sub">({pct(c.win_rate_low, 0)} to {pct(c.win_rate_high, 0)})</span></span>}
                        <span className="cell-line">{num(c.turns_to_target_mean, 1)} turns</span>
                        <span className="cell-line sub">{num(c.points_per_turn)} per turn</span>
                      </>
                    ) : <span className="sub">not in this run</span>}
                  </td>
                );
              })}
            </tr>
          ))}</tbody>
        </table>
      </div>

      <div className="chart-grid">
        {multiRuns.length > 0 && (
          <Chart title="Win rate by strategy" subtitle="With 95% intervals; one bar for each run the strategy played in" series={winSeries}
            horizontal yFormat="pct" height={h(multiRuns)} barmode="stack" categoryOrder={pairs(multiRuns)}
            table={{ columns: ["Strategy", ...multiRuns.map((r) => r.simulation.name)],
              rows: strategies.map((s) => [label(s), ...multiRuns.map((r) => { const c = s.cells[r.simulation.simulation_id]; return c ? pct(c.win_rate) : null; })]) }} />
        )}
        <Chart title="Mean turns to reach the target" subtitle="Fewer is better. Only games that reached the target count; in multiplayer runs that is mostly the games the strategy won." series={turnsSeries}
          horizontal yFormat="num1" height={h(charted)} barmode="stack" categoryOrder={pairs(charted)}
          table={{ columns: ["Strategy", ...charted.map((r) => r.simulation.name)],
            rows: strategies.map((s) => [label(s), ...charted.map((r) => { const c = s.cells[r.simulation.simulation_id]; return c ? num(c.turns_to_target_mean, 1) : null; })]) }} />
        <Chart title="Points per turn by strategy" series={pptSeries} horizontal yFormat="num" height={h(charted)} barmode="stack" categoryOrder={pairs(charted)}
          table={{ columns: ["Strategy", ...charted.map((r) => r.simulation.name)],
            rows: strategies.map((s) => [label(s), ...charted.map((r) => { const c = s.cells[r.simulation.simulation_id]; return c ? num(c.points_per_turn) : null; })]) }} />
      </div>
    </div>
  );
}
