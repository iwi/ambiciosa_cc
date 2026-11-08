import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Compare } from "../components/analysis/Compare";
import { RunDetail } from "../components/analysis/RunDetail";
import { Notice } from "../components/Forms";
import { api } from "../lib/api";
import { int, when } from "../lib/format";
import type { RunRow, StrategyType } from "../lib/types";

type Source = "" | "simulation" | "interactive";
const STATUS = { running: "Running", pending: "Starting", completed: "Finished", cancelled: "Cancelled", failed: "Failed" };
const LEVEL = { summary: "Totals", turns: "Turns", full: "Throws" };

export default function Analyse() {
  const [params, setParams] = useSearchParams();
  const [source, setSource] = useState<Source>("");
  const [runs, setRuns] = useState<RunRow[] | null>(null);
  const [types, setTypes] = useState<StrategyType[]>([]);
  const [error, setError] = useState<string | null>(null);
  const selected = params.getAll("run");

  const load = useCallback(() => {
    api.simulations(source || undefined).then(setRuns).catch((e) => setError(e.message));
  }, [source]);
  useEffect(load, [load]);
  useEffect(() => {
    api.strategyTypes().then(setTypes).catch(() => undefined);
  }, []);

  const select = (ids: string[]) => setParams(ids.map((r): [string, string] => ["run", r]));
  const toggle = (id: string) => select(selected.includes(id) ? selected.filter((s) => s !== id) : [...selected, id]);

  const ordered = [...(runs ?? [])].reverse();
  const known = new Set((runs ?? []).map((r) => r.simulation_id));
  const shown = selected.filter((id) => known.has(id));

  return (
    <div className="page">
      <header className="page-head">
        <h1>Analyse</h1>
        <p className="lede">Your simulations and played games. Choose one to see its results in detail, or several to compare them.</p>
      </header>
      {error && <Notice>{error}</Notice>}
      <div className="list-head">
        <div className="segmented" role="group" aria-label="Show">
          {([["", "All"], ["simulation", "Simulations"], ["interactive", "Played games"]] as const).map(([v, label]) => (
            <button key={v} aria-pressed={source === v} onClick={() => setSource(v)}>{label}</button>
          ))}
        </div>
        {selected.length > 0 && <button className="quiet" onClick={() => select([])}>Clear selection</button>}
      </div>
      {runs && runs.length === 0 && (
        <div className="empty"><p>No runs yet. Start one in Simulate, or play a game.</p></div>
      )}
      {runs && runs.length > 0 && (
        <div className="table-wrap runs-wrap">
          <table className="data runs">
            <thead>
              <tr>
                <th scope="col"><span className="visually-hidden">Selected</span></th>
                <th scope="col">Run</th>
                <th scope="col">Started</th>
                <th scope="col">Status</th>
                <th scope="col" className="n">Games</th>
                <th scope="col">Detail</th>
              </tr>
            </thead>
            <tbody>
              {ordered.map((r) => (
                <tr key={r.simulation_id} className={selected.includes(r.simulation_id) ? "selected" : undefined}>
                  <td>
                    <input type="checkbox" aria-label={`Select ${r.name}`} checked={selected.includes(r.simulation_id)}
                      onChange={() => toggle(r.simulation_id)} />
                  </td>
                  <th scope="row">
                    <button className="link" onClick={() => select([r.simulation_id])}>{r.name}</button>
                    {r.source === "interactive" && <span className="tag">played</span>}
                  </th>
                  <td>{when(r.created_at)}</td>
                  <td className={`status-${r.status}`}>
                    {r.source === "interactive" && r.status === "running" ? "In progress" : STATUS[r.status]}
                  </td>
                  <td className="n">{int(r.n_games_completed)}{r.n_games_completed !== r.n_games_requested ? ` of ${int(r.n_games_requested)}` : ""}</td>
                  <td>{LEVEL[r.record_level]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {runs && shown.length === 1 && (
        <RunSection run={runs.find((r) => r.simulation_id === shown[0])!} types={types}
          onDeleted={() => { select([]); load(); }} />
      )}
      {runs && shown.length > 1 && (
        <section className="results" aria-label="Comparison">
          <header className="results-head"><h2>Comparing {shown.length} runs</h2></header>
          <Compare ids={shown} />
        </section>
      )}
      {runs && shown.length === 0 && runs.length > 0 && (
        <p className="sub hint">Choose a run by its name to see its results; tick several to compare them.</p>
      )}
    </div>
  );
}

function RunSection({ run, types, onDeleted }: { run: RunRow; types: StrategyType[]; onDeleted: () => void }) {
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const remove = async () => {
    try {
      await api.deleteSimulation(run.simulation_id);
      onDeleted();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <section className="results" aria-label="Results">
      <header className="results-head">
        <h2>{run.name}</h2>
        <p className="actions">
          <a href={api.exportUrl(run.simulation_id, "parquet")} download>Download Parquet</a>
          <a href={api.exportUrl(run.simulation_id, "csv")} download>Download CSV</a>
          {run.status !== "running" && (confirm ? (
            <>
              <span>Delete this run and its games?</span>
              <button className="quiet danger" onClick={remove}>Delete</button>
              <button className="quiet" onClick={() => setConfirm(false)}>Keep</button>
            </>
          ) : (
            <button className="quiet danger" onClick={() => setConfirm(true)}>Delete run</button>
          ))}
        </p>
      </header>
      {error && <Notice>{error}</Notice>}
      {run.status === "running" && <Notice kind="info">This run is still in progress; the results cover the games finished so far.</Notice>}
      <RunDetail key={`${run.simulation_id}-${run.n_games_completed}`} id={run.simulation_id} types={types} />
    </section>
  );
}
