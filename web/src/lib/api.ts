import type { Analysis, Comparison, GameHistory, GameRow, GameState, Progress, RunRow, Stats, Strategy, StrategyType, ThrowEvent } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") message = data.detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

export type Seat = { name: string; player_type: "human" | "automated"; strategy_version_id?: string | null };

export const api = {
  info: () => call<{ version: string; database: string; cpu_count: number }>("GET", "/info"),

  strategyTypes: () => call<StrategyType[]>("GET", "/strategy-types"),
  strategies: (includeArchived = false) =>
    call<Strategy[]>("GET", `/strategies${includeArchived ? "?include_archived=true" : ""}`),
  strategyVersions: (id: string) =>
    call<{ strategy_id: string; archived: boolean; versions: Strategy[] }>("GET", `/strategies/${id}`),
  createStrategy: (body: { name: string; description: string; type: string; params: Record<string, unknown> }) =>
    call<Strategy>("POST", "/strategies", body),
  updateStrategy: (id: string, body: { name?: string; description?: string; params?: Record<string, unknown> }) =>
    call<Strategy>("PUT", `/strategies/${id}`, body),
  deleteStrategy: (id: string) => call<{ result: "deleted" | "archived" }>("DELETE", `/strategies/${id}`),
  restoreStrategy: (id: string) => call<{ result: string }>("POST", `/strategies/${id}/restore`),

  liveGames: () => call<{ game_id: string; simulation_id: string; status: string; round_number: number;
    players: { name: string; score: number }[] }[]>("GET", "/games"),
  createGame: (body: Record<string, unknown>) => call<GameState>("POST", "/games", body),
  game: (id: string) => call<GameState>("GET", `/games/${id}?history_turns=20`),
  throwDice: (id: string) => call<{ event: ThrowEvent; state: GameState }>("POST", `/games/${id}/throw`),
  decide: (id: string, decision: "CONTINUE" | "STOP") =>
    call<{ state: GameState }>("POST", `/games/${id}/decision`, { decision }),
  abandon: (id: string) => call<{ state: GameState }>("POST", `/games/${id}/abandon`),

  startSimulation: (body: Record<string, unknown>) =>
    call<{ simulation_id: string; progress: Progress }>("POST", "/simulations", body),
  simulations: (source?: string) => call<RunRow[]>("GET", `/simulations${source ? `?source=${source}` : ""}`),
  simulation: (id: string) => call<RunRow & { config: Record<string, unknown>; progress: Progress }>("GET", `/simulations/${id}`),
  cancelSimulation: (id: string) => call<Progress>("POST", `/simulations/${id}/cancel`),
  deleteSimulation: (id: string) => call<{ result: string }>("DELETE", `/simulations/${id}`),
  stats: (id: string) => call<Stats>("GET", `/simulations/${id}/stats`),
  analysis: (id: string) => call<Analysis>("GET", `/simulations/${id}/analysis`),
  compare: (ids: string[]) => call<Comparison>("GET", `/compare?ids=${ids.join(",")}`),
  games: (id: string, q: { limit: number; offset: number; winner?: number | null; sort?: string }) => {
    const p = new URLSearchParams({ limit: String(q.limit), offset: String(q.offset), sort: q.sort ?? "index" });
    if (q.winner !== undefined && q.winner !== null) p.set("winner", String(q.winner));
    return call<{ total: number; games: GameRow[] }>("GET", `/simulations/${id}/games?${p}`);
  },
  gameHistory: (gameId: string) => call<GameHistory>("GET", `/games/${gameId}/history`),
  exportUrl: (id: string, format: "parquet" | "csv") => `/api/simulations/${id}/export?format=${format}`,
};

/** Follow a run's progress over server-sent events; returns a function that stops listening. */
export function watchProgress(id: string, onProgress: (p: Progress) => void, onEnd: () => void): () => void {
  const source = new EventSource(`/api/simulations/${id}/progress`);
  source.addEventListener("progress", (e) => onProgress(JSON.parse((e as MessageEvent).data)));
  source.addEventListener("end", () => {
    source.close();
    onEnd();
  });
  source.onerror = () => {
    source.close();
    onEnd();
  };
  return () => source.close();
}
