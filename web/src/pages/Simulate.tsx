import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { DEFAULT_RULES, FieldRow, Notice, RulesFields, rulesBody, SeatsEditor, type SeatDraft } from "../components/Forms";
import { SummaryTable } from "../components/Results";
import { api, watchProgress } from "../lib/api";
import { duration, int } from "../lib/format";
import type { Progress, Rules, RunRow, Stats } from "../lib/types";
import { useStrategies } from "../lib/useStrategies";

type Level = "auto" | "summary" | "turns" | "full";

export default function Simulate() {
  const { strategies, error: loadError } = useStrategies();
  const [seats, setSeats] = useState<SeatDraft[] | null>(null);
  const [rules, setRules] = useState<Rules>(DEFAULT_RULES);
  const [name, setName] = useState("");
  const [games, setGames] = useState("10000");
  const [seed, setSeed] = useState("");
  const [level, setLevel] = useState<Level>("auto");
  const [cpus, setCpus] = useState(1);
  const [workers, setWorkers] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [running, setRunning] = useState<RunRow[]>([]);

  useEffect(() => {
    api.info().then((i) => setCpus(i.cpu_count)).catch(() => undefined);
    api.simulations("simulation").then((rows) => setRunning(rows.filter((r) => r.status === "running"))).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (strategies && strategies.length && seats === null) {
      const pick = (n: string, i: number) => strategies.find((s) => s.name === n) ?? strategies[i % strategies.length];
      setSeats([pick("Stop at 30", 0), pick("Stop at 50", 1)].map((s) => ({
        name: s.name, player_type: "automated" as const, strategy_version_id: s.strategy_version_id,
      })));
    }
  }, [strategies, seats]);

  const n = Number(games);
  const autoLevel = n > 10_000 ? "summary" : "full";

  const start = async () => {
    if (!seats) return;
    setError(null);
    if (!Number.isInteger(n) || n < 1) {
      setError("Enter how many games to play, as a whole number of at least 1.");
      return;
    }
    try {
      const r = await api.startSimulation({
        ...rulesBody(rules),
        name: name.trim(),
        n_games: n,
        ...(seed.trim() ? { master_seed: Number(seed) } : {}),
        ...(level !== "auto" ? { record_level: level } : {}),
        ...(workers.trim() ? { workers: Number(workers) } : {}),
        players: seats.map((s) => ({ name: s.name.trim() || "Player", strategy_version_id: s.strategy_version_id })),
      });
      setActive(r.simulation_id);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="page">
      <header className="page-head">
        <h1>Simulate</h1>
        <p className="lede">Play many games between bots and see which strategy wins most often. Every game is stored for Analyse.</p>
      </header>
      {loadError && <Notice>{loadError}</Notice>}
      {running.length > 0 && !active && (
        <Notice kind="info">
          {running.length === 1 ? "A run is in progress: " : `${running.length} runs are in progress: `}
          {running.map((r, i) => (
            <span key={r.simulation_id}>
              {i > 0 && ", "}
              <button className="link" onClick={() => setActive(r.simulation_id)}>{r.name}</button>
            </span>
          ))}
        </Notice>
      )}
      <div className="two-col">
        {strategies && seats && (
          <form className="setup" onSubmit={(e) => { e.preventDefault(); start(); }}>
            <SeatsEditor seats={seats} strategies={strategies} onChange={setSeats} allowHumans={false} />
            <fieldset>
              <legend>Run</legend>
              <div className="field-grid">
                <FieldRow label="Games" htmlFor="sim-games" help="How many games to play">
                  <input id="sim-games" type="number" min={1} step={1} value={games} onChange={(e) => setGames(e.target.value)} />
                </FieldRow>
                <FieldRow label="Name" htmlFor="sim-name" help="Optional; the strategies are used if empty">
                  <input id="sim-name" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
                </FieldRow>
                <FieldRow label="Detail kept" htmlFor="sim-level"
                  help={level === "auto" ? `Every throw up to 10,000 games, totals above (now: ${autoLevel === "full" ? "every throw" : "totals"})`
                    : level === "summary" ? "Final totals per player; smallest and fastest"
                    : level === "turns" ? "Totals and every turn" : "Totals, every turn and every throw"}>
                  <select id="sim-level" value={level} onChange={(e) => setLevel(e.target.value as Level)}>
                    <option value="auto">Automatic</option>
                    <option value="summary">Totals only</option>
                    <option value="turns">Every turn</option>
                    <option value="full">Every throw</option>
                  </select>
                </FieldRow>
                <FieldRow label="Seed" htmlFor="sim-seed" help="Optional; the same seed repeats the same games">
                  <input id="sim-seed" type="number" min={0} value={seed} placeholder="random" onChange={(e) => setSeed(e.target.value)} />
                </FieldRow>
                <FieldRow label="Processes" htmlFor="sim-workers" help={`Games run in parallel; this computer has ${cpus}`}>
                  <input id="sim-workers" type="number" min={1} max={cpus} value={workers} placeholder={String(cpus)}
                    onChange={(e) => setWorkers(e.target.value)} />
                </FieldRow>
              </div>
            </fieldset>
            <RulesFields rules={rules} onChange={setRules} />
            {error && <Notice>{error}</Notice>}
            <div className="actions">
              <button type="submit" className="primary">Start simulation</button>
            </div>
          </form>
        )}
        <div className="run-pane">
          {active ? <RunPanel key={active} id={active} /> : <EmptyRun />}
        </div>
      </div>
    </div>
  );
}

function EmptyRun() {
  return (
    <div className="empty">
      <p>Choose the bots and how many games to play, then start the simulation. Progress and results appear here.</p>
    </div>
  );
}

function RunPanel({ id }: { id: string }) {
  const [progress, setProgress] = useState<Progress | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const loadedStats = useRef(false);

  useEffect(() => {
    api.simulation(id).then((s) => { setName(s.name); setProgress(s.progress); }).catch((e) => setError(e.message));
    return watchProgress(id, setProgress, () => undefined);
  }, [id]);

  const done = progress && ["completed", "cancelled", "failed"].includes(progress.status);
  useEffect(() => {
    if (done && !loadedStats.current) {
      loadedStats.current = true;
      api.stats(id).then(setStats).catch((e) => setError(e.message));
    }
  }, [done, id]);

  const cancel = async () => {
    try {
      setProgress(await api.cancelSimulation(id));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (!progress) return <p className="sub">Starting…</p>;
  const label = { running: "Running", pending: "Starting", completed: "Finished", cancelled: "Cancelled", failed: "Failed" }[progress.status];

  return (
    <section className="run" aria-label="Simulation progress">
      <h2>{name}</h2>
      <div className={`progress ${progress.status}`}>
        <div className="progress-bar" role="progressbar" aria-valuemin={0} aria-valuemax={progress.games_requested}
          aria-valuenow={progress.games_completed} aria-label="Games played">
          <span style={{ width: `${progress.fraction * 100}%` }} />
        </div>
        <dl className="progress-figures">
          <div><dt>{label}</dt><dd>{int(progress.games_completed)} of {int(progress.games_requested)} games</dd></div>
          <div><dt>Speed</dt><dd>{progress.rate ? `${int(progress.rate)} games a second` : "–"}</dd></div>
          <div><dt>{done ? "Took" : "Time left"}</dt><dd>{done ? duration(progress.elapsed_s) : duration(progress.eta_s)}</dd></div>
        </dl>
      </div>
      {progress.status === "running" && <button onClick={cancel}>Cancel run</button>}
      {progress.status === "cancelled" && <Notice kind="info">Cancelled. The {int(progress.games_completed)} games already played are kept.</Notice>}
      {progress.status === "failed" && <Notice>The run failed: {progress.error ?? "see the server log"}. Games already played are kept.</Notice>}
      {error && <Notice>{error}</Notice>}
      {stats && stats.overview.games > 0 && (
        <>
          <SummaryTable stats={stats} />
          <p className="actions">
            <Link to={`/analyse?run=${id}`}>Open in Analyse</Link>
            <a href={api.exportUrl(id, "parquet")} download>Download Parquet</a>
            <a href={api.exportUrl(id, "csv")} download>Download CSV</a>
          </p>
        </>
      )}
    </section>
  );
}
