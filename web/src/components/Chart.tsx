import { useEffect, useRef, useState, type ReactNode } from "react";

// One chart component for the whole app. Plotly is loaded only when the
// first chart is shown, so Play, Simulate and Strategies stay light.
//
// Rules applied everywhere (from the data-viz method):
// * players keep one colour per seat, in a fixed order (validated palette, light and dark steps);
// * a legend whenever there are two or more series; text never takes a series colour;
// * thin marks, hairline recessive grid, one y-axis;
// * every chart has a table view with the same numbers.

export type Fmt = "pct" | "pct1" | "num" | "num1" | "int";

export type Series = {
  name: string;
  x: (number | string)[];
  y: number[];
  kind: "bar" | "line" | "marker";
  color?: number | string;            // seat index into the series palette, or a CSS colour token name
  errorLow?: (number | null)[];       // absolute lower ends (for intervals)
  errorHigh?: (number | null)[];
  hover?: string[];                   // extra text per point
};

type Props = {
  title: string;
  subtitle?: ReactNode;
  series: Series[];
  xTitle?: string;
  yTitle?: string;
  yFormat?: Fmt;
  xFormat?: Fmt;
  horizontal?: boolean;               // bars run left to right; categories on the y-axis
  barmode?: "group" | "stack" | "overlay";
  xCategorical?: boolean;
  categoryOrder?: string[];           // explicit order of the category axis
  height?: number;
  table: { columns: string[]; rows: (string | number | null)[][] };
  note?: ReactNode;
};

const TICK: Record<Fmt, string> = { pct: ".0%", pct1: ".1%", num: ",.2f", num1: ",.1f", int: "," };
const HOVER: Record<Fmt, string> = { pct: ".1%", pct1: ".1%", num: ",.2f", num1: ",.1f", int: "," };

function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function seriesColor(c: number | string | undefined, i: number): string {
  if (typeof c === "string") return token(c) || c;
  return token(`--series-${((c ?? i) % 6) + 1}`);
}

function useColorScheme() {
  const [dark, setDark] = useState(() => window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false);
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mq) return;
    const on = () => setDark(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return dark;
}

let plotly: Promise<typeof import("plotly.js-basic-dist-min").default> | null = null;
const loadPlotly = () => (plotly ??= import("plotly.js-basic-dist-min").then((m) => m.default));

export function Chart(props: Props) {
  const { title, subtitle, series, table, note } = props;
  const [view, setView] = useState<"chart" | "table">("chart");
  const [failed, setFailed] = useState<string | null>(null);
  const el = useRef<HTMLDivElement>(null);
  const dark = useColorScheme();

  useEffect(() => {
    if (view !== "chart" || !el.current) return;
    let cancelled = false;
    const node = el.current;
    loadPlotly().then((Plotly) => {
      if (cancelled) return;
      const ink = token("--ink"), soft = token("--ink-soft"), rule = token("--rule"), surface = token("--surface");
      const yF = props.yFormat ?? "num", xF = props.xFormat;
      const valueAxis = props.horizontal ? "x" : "y";
      const data = series.map((s, i) => {
        const color = seriesColor(s.color, i);
        const values = s.y;
        const err = s.errorLow && s.errorHigh ? {
          type: "data", symmetric: false, visible: true, thickness: 1.5, width: 5, color: soft,
          array: values.map((v, k) => (s.errorHigh![k] ?? v) - v),
          arrayminus: values.map((v, k) => v - (s.errorLow![k] ?? v)),
        } : undefined;
        const fmtV = `%{${valueAxis}:${HOVER[yF]}}`;
        const fmtC = props.horizontal ? "%{y}" : xF ? `%{x:${HOVER[xF]}}` : "%{x}";
        const base = {
          name: s.name,
          x: props.horizontal ? values : s.x,
          y: props.horizontal ? s.x : values,
          text: s.hover,
          hovertemplate: `<b>${s.name.replace(/</g, "&lt;")}</b><br>${fmtC}: ${fmtV}${s.hover ? "<br>%{text}" : ""}<extra></extra>`,
          showlegend: series.length > 1,
        };
        if (s.kind === "bar") {
          return { ...base, type: "bar", orientation: props.horizontal ? "h" : "v", marker: { color, line: { width: 0 } },
            [props.horizontal ? "error_x" : "error_y"]: err, textposition: "none" };
        }
        if (s.kind === "marker") {
          return { ...base, type: "scatter", mode: "markers",
            marker: { color, size: 26, symbol: "line-ew", line: { color, width: 3 } } };
        }
        return { ...base, type: "scatter", mode: "lines", line: { color, width: 2, shape: "linear" },
          error_y: err, hoveron: "points" };
      });
      const axis = (t: string | undefined, fmt: Fmt | undefined, categorical = false) => ({
        title: t ? { text: t, font: { size: 12, color: soft }, standoff: 8 } : undefined,
        tickformat: fmt ? TICK[fmt] : undefined,
        type: categorical ? "category" : undefined,
        gridcolor: rule, linecolor: rule, zerolinecolor: rule, zerolinewidth: 1,
        tickfont: { size: 12, color: soft }, automargin: true, fixedrange: true,
      });
      const layout = {
        height: props.height ?? 300,
        margin: { l: 8, r: 16, t: series.length > 1 ? 36 : 12, b: 8 },
        paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
        font: { family: getComputedStyle(document.body).fontFamily, color: ink, size: 13 },
        barmode: props.barmode ?? "group", bargap: props.horizontal ? 0.45 : 0.35, bargroupgap: 0.08,
        hovermode: "closest",
        hoverlabel: { bgcolor: surface, bordercolor: rule, font: { color: ink, size: 13 } },
        legend: { orientation: "h", x: 0, y: 1.02, yanchor: "bottom", traceorder: "normal", font: { size: 12, color: ink }, itemclick: false, itemdoubleclick: false },
        xaxis: props.horizontal ? axis(props.yTitle, yF) : axis(props.xTitle, xF, props.xCategorical),
        yaxis: props.horizontal ? { ...axis(props.xTitle, undefined, true), autorange: "reversed" } : axis(props.yTitle, yF),
      };
      if (props.categoryOrder) {
        const cat = props.horizontal ? layout.yaxis : layout.xaxis;
        Object.assign(cat, { type: "category", categoryorder: "array", categoryarray: props.categoryOrder });
      }
      return Plotly.react(node, data, layout, { displayModeBar: false, responsive: true });
    }).catch((e) => setFailed(String(e)));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, series, dark, props.yFormat, props.horizontal, props.height]);

  useEffect(() => () => {
    if (el.current) loadPlotly().then((P) => el.current && P.purge(el.current)).catch(() => undefined);
  }, []);

  return (
    <figure className="chart">
      <figcaption className="chart-head">
        <div>
          <h4>{title}</h4>
          {subtitle && <p className="sub">{subtitle}</p>}
        </div>
        <div className="segmented small" role="group" aria-label={`${title}: view`}>
          <button aria-pressed={view === "chart"} onClick={() => setView("chart")}>Chart</button>
          <button aria-pressed={view === "table"} onClick={() => setView("table")}>Table</button>
        </div>
      </figcaption>
      {view === "chart" ? (
        failed ? <p className="notice notice-error">The chart could not be drawn ({failed}). The table view has the same numbers.</p>
          : <div ref={el} className="chart-plot" role="img" aria-label={`${title}. Switch to the table view for the numbers.`} />
      ) : (
        <div className="table-wrap chart-table">
          <table className="data">
            <thead><tr>{table.columns.map((c, i) => <th key={c} scope="col" className={i ? "n" : undefined}>{c}</th>)}</tr></thead>
            <tbody>
              {table.rows.map((r, i) => (
                <tr key={i}>{r.map((v, j) => j === 0 ? <th key={j} scope="row">{v}</th> : <td key={j} className="n">{v ?? "–"}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {note && <p className="chart-note sub">{note}</p>}
    </figure>
  );
}
