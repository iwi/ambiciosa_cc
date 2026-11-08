import { useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";
import { FACE_SYMBOLS, int, num, pct, when } from "../../lib/format";
import { SCORE_FIELDS } from "../../lib/scoring";
import { describeParams, fieldsFromSchema } from "../../lib/schemaForm";
import type { Analysis, Histogram, PlayerMetrics, StrategyType } from "../../lib/types";
import { Chart, type Series } from "../Chart";
import { Notice } from "../Forms";
import { GamesBrowser } from "./GamesBrowser";

type Tab = "summary" | "distributions" | "turns" | "throws" | "games";
const TABS: [Tab, string][] = [
  ["summary", "Summary"],
  ["distributions", "Distributions"],
  ["turns", "Turns"],
  ["throws", "Throws"],
  ["games", "Games"],
];

export function playerLabel(p: { display_name: string; strategy_name: string | null }) {
  return p.display_name;
}

/** A share that never rounds a near-certainty up to 100% (or a rarity down to 0%). */
function share(v: number | null) {
  if (v === null) return "–";
  if (v > 0.999 && v < 1) return ">99.9%";
  if (v > 0 && v < 0.001) return "<0.1%";
  return pct(v);
}

function interval(lo: number | null, hi: number | null) {
  return lo === null || hi === null ? "–" : `${pct(lo)} to ${pct(hi)}`;
}

export function RunDetail({ id, types }: { id: string; types: StrategyType[] }) {
  const [data, setData] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("summary");

  useEffect(() => {
    setData(null);
    api.analysis(id).then(setData).catch((e) => setError(e.message));
  }, [id]);

  if (error) return <Notice>{error}</Notice>;
  if (!data) return <p className="sub">Loading results…</p>;
  if (data.overview.games === 0) return <p className="sub">No games are stored in this run.</p>;

  return (
    <div className="run-detail">
      <div className="tabs" role="tablist" aria-label="Result views">
        {TABS.map(([t, label]) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>{label}</button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === "summary" && <Summary data={data} types={types} />}
        {tab === "distributions" && <Distributions data={data} />}
        {tab === "turns" && (data.turns ? <Turns data={data} /> : <NotRecorded what="Turn details" need="Every turn or Every throw" />)}
        {tab === "throws" && (data.throws ? <Throws data={data} /> : <NotRecorded what="Throw details" need="Every throw" />)}
        {tab === "games" && <GamesBrowser data={data} />}
      </div>
    </div>
  );
}

function NotRecorded({ what, need }: { what: string; need: string }) {
  return (
    <div className="empty">
      <p>{what} were not kept for this run. To see them, run it again with the detail set to {need}; the same seed gives the same games.</p>
    </div>
  );
}

// ------------------------------------------------------------------ summary

function Config({ data, types }: { data: Analysis; types: StrategyType[] }) {
  const s = data.simulation;
  const typeByName = new Map(types.map((t) => [t.name, t]));
  const level = { summary: "Totals only", turns: "Every turn", full: "Every throw" }[s.record_level];
  return (
    <section className="config" aria-label="Configuration">
      <dl className="config-grid">
        <div><dt>Games</dt><dd>{int(s.n_games_completed)}{s.n_games_completed !== s.n_games_requested ? ` of ${int(s.n_games_requested)} requested` : ""}</dd></div>
        <div><dt>Started</dt><dd>{when(s.created_at)}</dd></div>
        <div><dt>Target</dt><dd>{int(s.target)}</dd></div>
        <div><dt>Game ends</dt><dd>{s.end_rule === "equal_turns" ? "Equal turns" : "First to the target"}</dd></div>
        <div><dt>Turn limit</dt><dd>{s.max_turns ? int(s.max_turns) : "–"}</dd></div>
        <div><dt>Dice</dt><dd>{s.face_weights ? `Loaded: ${s.face_weights.map((w, i) => `${FACE_SYMBOLS[i]} ${pct(w, 0)}`).join(", ")}` : "Fair"}</dd></div>
        <div className={s.scoring_is_default ? undefined : "wide"}><dt>Scores</dt><dd>{s.scoring_is_default ? "Standard"
          : SCORE_FIELDS.map((f) => `${f.label} ${s.scoring[f.key] > 0 ? "+" : ""}${s.scoring[f.key]}`).join(", ")}</dd></div>
        <div><dt>Seed</dt><dd>{String(s.master_seed)}</dd></div>
        <div><dt>Detail kept</dt><dd>{level}</dd></div>
        <div><dt>Version</dt><dd>{s.software_version}</dd></div>
      </dl>
      <table className="data seats-table">
        <caption>Players and strategies</caption>
        <thead><tr><th scope="col">Player</th><th scope="col">Strategy</th><th scope="col">Parameters</th></tr></thead>
        <tbody>
          {s.players.map((p) => {
            const t = p.strategy ? typeByName.get(p.strategy.type) : undefined;
            return (
              <tr key={p.seat}>
                <th scope="row"><SeatSwatch seat={p.seat} />{p.name}</th>
                <td>{p.strategy ? `${p.strategy.name}${p.strategy.version > 1 ? ` (v${p.strategy.version})` : ""}` : "Human"}
                  {t && <span className="sub"> ({t.title})</span>}</td>
                <td>{p.strategy ? (t ? describeParams(fieldsFromSchema(t.schema), p.strategy.params) : JSON.stringify(p.strategy.params)) : "–"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

export function SeatSwatch({ seat }: { seat: number }) {
  return <span className="swatch" style={{ background: `var(--series-${(seat % 6) + 1})` }} aria-hidden="true" />;
}

function Summary({ data, types }: { data: Analysis; types: StrategyType[] }) {
  const single = data.simulation.single_player;
  const players = data.players;
  const multi = !single;

  const winSeries: Series[] = useMemo(() => [{
    name: "Win rate", kind: "bar", color: "--series-1",
    x: players.map(playerLabel), y: players.map((p) => p.win_rate),
    errorLow: players.map((p) => p.win_rate_low), errorHigh: players.map((p) => p.win_rate_high),
    hover: players.map((p) => `95% interval ${interval(p.win_rate_low, p.win_rate_high)}`),
  }], [players]);

  const pptSeries: Series[] = useMemo(() => [{
    name: "Points per turn", kind: "bar", color: "--series-1",
    x: players.map(playerLabel), y: players.map((p) => p.points_per_turn ?? 0),
  }], [players]);

  const positions = data.play_position.rows;
  const nPos = Math.max(0, ...positions.map((r) => r.position));
  const posSeries: Series[] = useMemo(() => players.map((p) => {
    const rows = positions.filter((r) => r.seat === p.seat).sort((a, b) => a.position - b.position);
    return { name: playerLabel(p), kind: "bar" as const, color: p.seat, x: rows.map((r) => `${ordinal(r.position)}`), y: rows.map((r) => r.win_rate),
      errorLow: rows.map((r) => r.win_rate_low), errorHigh: rows.map((r) => r.win_rate_high),
      hover: rows.map((r) => `${int(r.games)} games`) };
  }), [players, positions]);

  return (
    <>
      <Config data={data} types={types} />
      <MetricsTable players={players} single={single} target={data.simulation.target} overview={data.overview} />
      <div className="chart-grid">
        {multi && (
          <Chart title="Win rate" subtitle="Share of games won (a shared win counts as a fraction), with 95% intervals"
            series={winSeries} horizontal yFormat="pct" height={Math.max(160, 56 * players.length + 40)}
            table={{ columns: ["Player", "Win rate", "95% interval", "Wins", "Games"],
              rows: players.map((p) => [playerLabel(p), pct(p.win_rate), interval(p.win_rate_low, p.win_rate_high), num(p.wins, Number.isInteger(p.wins) ? 0 : 1), int(p.games)]) }} />
        )}
        {single && <TurnsToTarget data={data} />}
        {multi && (
          <Chart title="Points per turn" subtitle="Total points over total turns, so long games count in proportion"
            series={pptSeries} horizontal yFormat="num" height={Math.max(160, 56 * players.length + 40)}
            table={{ columns: ["Player", "Points per turn", "Throws per turn", "Turns lost"],
              rows: players.map((p) => [playerLabel(p), num(p.points_per_turn), num(p.throws_per_turn), pct(p.bust_rate)]) }} />
        )}
        {multi && nPos > 1 && (
          <Chart title="Win rate by playing position" subtitle="Does moving first help? Each player's win rate by their place in the order"
            series={posSeries} yFormat="pct" xTitle="Position in the playing order" xCategorical
            table={{ columns: ["Position", ...players.map(playerLabel), "Everyone"],
              rows: Array.from({ length: nPos }, (_, i) => {
                const pos = i + 1;
                return [ordinal(pos), ...players.map((p) => {
                  const r = positions.find((x) => x.seat === p.seat && x.position === pos);
                  return r ? pct(r.win_rate) : "–";
                }), pct(positions.find((x) => x.seat === null && x.position === pos)?.win_rate)];
              }) }} />
        )}
      </div>
    </>
  );
}

function ordinal(n: number) {
  return `${n}${n === 1 ? "st" : n === 2 ? "nd" : n === 3 ? "rd" : "th"}`;
}

function MetricsTable({ players, single, target, overview }: { players: PlayerMetrics[]; single: boolean; target: number; overview: Analysis["overview"] }) {
  return (
    <div className="table-wrap metrics">
      <table className="data">
        <caption>
          {int(overview.games)} games, {int(overview.finished)} finished
          {overview.unfinished ? `, ${int(overview.unfinished)} stopped at the turn limit` : ""}
          {overview.shared_wins ? `, ${int(overview.shared_wins)} shared wins` : ""}.
          {" "}Turns to reach {int(target)} count only the games in which the player reached it{single ? "" : ", which in a multiplayer game is usually only the winner"}.
        </caption>
        <thead>
          <tr>
            <th scope="col" rowSpan={2}>Player</th>
            {!single && <th scope="col" rowSpan={2} className="n">Win rate</th>}
            {!single && <th scope="col" rowSpan={2} className="n">95% interval</th>}
            <th scope="col" rowSpan={2} className="n">Reached {int(target)}</th>
            <th scope="colgroup" colSpan={5} className="group">Turns to reach {int(target)}</th>
            <th scope="col" rowSpan={2} className="n">Points per turn</th>
            <th scope="col" rowSpan={2} className="n">Throws per turn</th>
            <th scope="col" rowSpan={2} className="n">Turns lost</th>
          </tr>
          <tr>
            <th scope="col" className="n">Mean</th>
            <th scope="col" className="n">Median</th>
            <th scope="col" className="n">Min</th>
            <th scope="col" className="n">Max</th>
            <th scope="col" className="n">SD</th>
          </tr>
        </thead>
        <tbody>
          {players.map((p) => (
            <tr key={p.seat}>
              <th scope="row"><span className="who"><SeatSwatch seat={p.seat} />{p.display_name}</span>
                {p.strategy_name && p.strategy_name !== p.display_name && <span className="sub">{p.strategy_name}</span>}</th>
              {!single && <td className="n">{pct(p.win_rate)}</td>}
              {!single && <td className="n sub">{interval(p.win_rate_low, p.win_rate_high)}</td>}
              <td className="n">{share(p.reached_target_rate)}</td>
              <td className="n strong">{num(p.turns_to_target_mean, 1)}</td>
              <td className="n">{num(p.turns_to_target_median, 1)}</td>
              <td className="n">{int(p.turns_to_target_min)}</td>
              <td className="n">{int(p.turns_to_target_max)}</td>
              <td className="n">{num(p.turns_to_target_sd, 1)}</td>
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

// ------------------------------------------------------------ distributions

const binLabel = (h: Histogram, i: number) =>
  h.bin_width > 1 ? `${h.bin_start[i]} to ${h.bin_start[i] + h.bin_width - 1}` : String(h.bin_start[i]);

function histSeries(h: Histogram, players: PlayerMetrics[], kind: "line" | "bar" = "line", dropEmpty = false): Series[] {
  const name = (seat: number | null) => (seat === null ? "Games" : playerLabel(players.find((p) => p.seat === seat)!));
  const centre = h.bin_width > 1 ? h.bin_width / 2 - 0.5 : 0;
  // With dropEmpty, only bins that some series uses are kept, as categories (for spiky, gappy distributions).
  const keep = h.bin_start.map((_, i) => !dropEmpty || h.series.some((s) => s.counts[i] > 0));
  const pick = <T,>(xs: T[]) => xs.filter((_, i) => keep[i]);
  return h.series.map((s) => ({
    name: name(s.seat), kind, color: s.seat ?? 0,
    x: dropEmpty ? pick(h.bin_start.map((b) => String(b))) : h.bin_start.map((b) => b + centre),
    y: pick(s.shares),
    hover: pick(s.counts.map((c, i) => `${binLabel(h, i)}: ${int(c)} of ${int(s.total)}`)),
  }));
}

function histTable(h: Histogram, players: PlayerMetrics[], first: string) {
  const name = (seat: number | null) => (seat === null ? "Games" : playerLabel(players.find((p) => p.seat === seat)!));
  return {
    columns: [first, ...h.series.map((s) => name(s.seat))],
    rows: h.bin_start.map((b, i) => [h.bin_width > 1 ? `${b} to ${b + h.bin_width - 1}` : String(b), ...h.series.map((s) => `${int(s.counts[i])} (${pct(s.shares[i])})`)]),
  };
}

function TurnsToTarget({ data }: { data: Analysis }) {
  const h = data.distributions.turns_to_target;
  const series = useMemo(() => histSeries(h, data.players), [h, data.players]);
  if (!h.series.length) return <p className="sub">Nobody reached the target in this run.</p>;
  return (
    <Chart title={`Turns to reach ${int(data.simulation.target)}`}
      subtitle={`Share of each player's games that reached the target in that many turns${h.bin_width > 1 ? `, in groups of ${h.bin_width}` : ""}`}
      series={series} xTitle="Turns" yFormat="pct" table={histTable(h, data.players, "Turns")} />
  );
}

function Distributions({ data }: { data: Analysis }) {
  const { final_score, game_length } = data.distributions;
  const fs = useMemo(() => histSeries(final_score, data.players), [final_score, data.players]);
  const gl = useMemo(() => histSeries(game_length, data.players, "bar"), [game_length, data.players]);
  return (
    <div className="chart-grid">
      <TurnsToTarget data={data} />
      <Chart title="Final scores" subtitle={`Share of games ending on each score, in groups of ${final_score.bin_width}. The peak just above ${int(data.simulation.target)} is the winners.`}
        series={fs} xTitle="Final score" yFormat="pct" table={histTable(final_score, data.players, "Final score")} />
      <Chart title="Game length" subtitle={`Rounds played${game_length.bin_width > 1 ? `, in groups of ${game_length.bin_width}` : ""}`}
        series={gl} xTitle="Rounds" yFormat="pct" table={histTable(game_length, data.players, "Rounds")} />
    </div>
  );
}

// -------------------------------------------------------------------- turns

const ENDS: { key: "stop" | "reached_target" | "bust_zero" | "bust_negative"; label: string; color: string }[] = [
  { key: "stop", label: "Banked", color: "--end-banked" },
  { key: "reached_target", label: "Reached the target", color: "--end-target" },
  { key: "bust_zero", label: "Scored nothing", color: "--end-zero" },
  { key: "bust_negative", label: "Penalty", color: "--end-penalty" },
];

function Turns({ data }: { data: Analysis }) {
  const t = data.turns!;
  const names = t.end_reasons.map((r) => playerLabel(data.players.find((p) => p.seat === r.seat)!));
  const ends: Series[] = useMemo(() => ENDS.map((e) => ({
    name: e.label, kind: "bar" as const, color: e.color, x: names, y: t.end_reasons.map((r) => r[e.key]),
  })), [t, names.join("|")]); // eslint-disable-line react-hooks/exhaustive-deps
  const scores = useMemo(() => histSeries(t.turn_score, data.players, "bar", true), [t, data.players]);
  const throws = useMemo(() => histSeries(t.throws_per_turn, data.players, "bar"), [t, data.players]);
  return (
    <>
      <div className="table-wrap metrics">
        <table className="data">
          <thead><tr><th scope="col">Player</th><th scope="col" className="n">Turns</th><th scope="col" className="n">Mean turn score</th>
            <th scope="col" className="n">Mean when banked</th><th scope="col" className="n">Throws per turn</th></tr></thead>
          <tbody>{t.end_reasons.map((r, i) => (
            <tr key={r.seat}><th scope="row"><SeatSwatch seat={r.seat} />{names[i]}</th><td className="n">{int(r.turns)}</td>
              <td className="n">{num(r.mean_turn_score)}</td><td className="n">{num(r.mean_banked_score, 1)}</td><td className="n">{num(r.mean_throws)}</td></tr>
          ))}</tbody>
        </table>
      </div>
      <div className="chart-grid">
        <Chart title="How turns end" subtitle="Share of each player's turns" series={ends} horizontal barmode="stack" yFormat="pct"
          height={Math.max(170, 52 * names.length + 70)}
          table={{ columns: ["Player", ...ENDS.map((e) => e.label)], rows: t.end_reasons.map((r, i) => [names[i], ...ENDS.map((e) => pct(r[e.key]))]) }} />
        <Chart title="Turn scores" subtitle={`Share of turns ending on each score, in groups of ${t.turn_score.bin_width}; scores that never occur are left out. Lost turns score 0 or below.`}
          series={scores} xTitle={`Turn score (each bar from the score shown to ${t.turn_score.bin_width - 1} above it)`} yFormat="pct" xCategorical table={histTable(t.turn_score, data.players, "Turn score")} />
        <Chart title="Throws per turn" subtitle="Share of turns with that many throws, the last one included" series={throws}
          xTitle="Throws" yFormat="pct" xCategorical table={histTable(t.throws_per_turn, data.players, "Throws")} />
      </div>
    </>
  );
}

// ------------------------------------------------------------------- throws

function Throws({ data }: { data: Analysis }) {
  const th = data.throws!;
  const faces: Series[] = useMemo(() => [
    { name: "Observed", kind: "bar", color: "--series-1", x: th.faces.map((f) => f.face), y: th.faces.map((f) => f.share),
      hover: th.faces.map((f) => `${int(f.count)} dice`) },
    { name: "Expected", kind: "marker", color: "--ink", x: th.faces.map((f) => f.face), y: th.faces.map((f) => f.expected_share) },
  ], [th]);
  const scores: Series[] = useMemo(() => [
    { name: "Observed", kind: "bar", color: "--series-1", x: th.scores.map((s) => String(s.score)), y: th.scores.map((s) => s.share),
      hover: th.scores.map((s) => `${int(s.count)} throws`) },
    { name: "Exact", kind: "marker", color: "--ink", x: th.scores.map((s) => String(s.score)), y: th.scores.map((s) => s.expected_share) },
  ], [th]);
  const ms = th.mean_score;
  const z = ms.standard_error ? (ms.observed - ms.expected) / ms.standard_error : 0;
  const p = th.face_test.p_value;
  return (
    <>
      <dl className="checks">
        <div><dt>Throws recorded</dt><dd>{int(th.n_throws)}</dd></div>
        <div><dt>Mean throw score</dt><dd>{num(ms.observed, 3)} <span className="sub">exact {num(ms.expected, 3)}, {Math.abs(z) < 3 ? "within" : "outside"} 3 standard errors ({num(z, 1)})</span></dd></div>
        <div><dt>Throws ending a turn</dt><dd>{pct(th.turn_ending_rate.observed, 2)} <span className="sub">exact {pct(th.turn_ending_rate.expected, 2)}</span></dd></div>
        <div><dt>Faces, chi-squared test</dt><dd>{p === null ? "not applicable (some faces have weight 0)" : <>p = {num(p, 3)} <span className="sub">{p < 0.01 ? "the faces differ from their weights more than chance explains" : "consistent with the face weights"}</span></>}</dd></div>
      </dl>
      <div className="chart-grid">
        <Chart title="Faces" subtitle="Share of all dice showing each face, against the face weights" series={faces} yFormat="pct1" xCategorical
          table={{ columns: ["Face", "Dice", "Observed", "Expected"], rows: th.faces.map((f) => [f.face, int(f.count), pct(f.share, 2), pct(f.expected_share, 2)]) }} />
        <Chart title="Throw scores" subtitle="Share of throws with each score, against the exact probabilities" series={scores} yFormat="pct1"
          xTitle="Throw score" xCategorical
          table={{ columns: ["Score", "Throws", "Observed", "Exact"], rows: th.scores.map((s) => [String(s.score), int(s.count), pct(s.share, 2), pct(s.expected_share, 2)]) }} />
      </div>
    </>
  );
}
