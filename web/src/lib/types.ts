// Shapes returned by the Python API (see ambiciosa/api).

export type JsonSchema = {
  title?: string;
  description?: string;
  type?: string;
  enum?: string[];
  default?: unknown;
  minimum?: number;
  maximum?: number;
  anyOf?: JsonSchema[];
  properties?: Record<string, JsonSchema>;
};

export type StrategyType = { name: string; title: string; description: string; schema: JsonSchema };

export type Strategy = {
  strategy_version_id: string;
  strategy_id: string;
  version: number;
  name: string;
  label: string;
  description: string;
  type: string;
  params: Record<string, unknown>;
  created_at: string;
  archived?: boolean;
  n_versions?: number;
  has_results?: boolean;
};

export type ThrowView = {
  throw_number: number;
  dice: number[];
  symbols: string;
  score: number;
  turn_points_after: number;
  decision: "CONTINUE" | "STOP" | null;
  reason: string | null;
};

export type TurnView = {
  seat: number;
  turn_number: number;
  round_number: number;
  points: number;
  end_reason: string | null;
  turn_score: number | null;
  banked_after: number | null;
  throws: ThrowView[];
};

export type PlayerView = {
  seat: number;
  name: string;
  player_type: "human" | "automated";
  strategy: { name: string; type: string; strategy_version_id: string } | null;
  score: number;
  turns_taken: number;
  total_throws: number;
  busts: number;
};

export type GameState = {
  game_id: string;
  simulation_id: string;
  status: "in_progress" | "finished" | "unfinished" | "abandoned";
  awaiting: "throw" | "decision" | "finished";
  round_number: number;
  current_seat: number | null;
  current_player_type: "human" | "automated" | null;
  play_order: number[];
  target: number;
  end_rule: string;
  max_turns: number;
  scoring: import("./scoring").Scoring;
  winners: number[];
  players: PlayerView[];
  current_turn: TurnView | null;
  history: TurnView[];
  n_turns: number;
};

export type ThrowEvent = {
  seat: number;
  throw: ThrowView;
  bot_decision: { decision: string; reason: string } | null;
  turn_ended: boolean;
  turn: TurnView | null;
};

export type Progress = {
  simulation_id: string;
  status: "running" | "completed" | "cancelled" | "failed" | "pending";
  games_completed: number;
  games_requested: number;
  fraction: number;
  elapsed_s: number | null;
  rate: number | null;
  eta_s: number | null;
  error: string | null;
};

export type RunRow = {
  simulation_id: string;
  source: "simulation" | "interactive";
  name: string;
  created_at: string;
  finished_at: string | null;
  status: Progress["status"];
  master_seed: number;
  n_games_requested: number;
  n_games_completed: number;
  record_level: "summary" | "turns" | "full";
  software_version: string;
};

export type PlayerSummary = {
  seat: number;
  display_name: string;
  strategy_version_id: string | null;
  strategy_name: string | null;
  strategy_version: number | null;
  strategy_type: string | null;
  games: number;
  games_finished: number;
  wins: number;
  win_rate: number;
  mean_final_score: number;
  mean_turns_to_win: number | null;
  points_per_turn: number | null;
  throws_per_turn: number | null;
  bust_rate: number | null;
};

export type Overview = {
  games: number;
  finished: number;
  unfinished: number;
  mean_rounds: number | null;
  shared_wins: number;
};

export type Stats = { overview: Overview; players: PlayerSummary[] };

export type Rules = {
  target: number;
  end_rule: "first_to_target" | "equal_turns";
  max_turns: number;
  face_weights: number[] | null;
  scoring: import("./scoring").Scoring | null; // null = the standard scores
};

// ------------------------------------------------------------- analysis

export type Histogram = {
  bin_start: number[];
  bin_width: number;
  series: { seat: number | null; counts: number[]; total: number; shares: number[] }[];
};

export type PlayerMetrics = {
  seat: number;
  display_name: string;
  player_type: string;
  strategy_version_id: string | null;
  strategy_name: string | null;
  strategy_version: number | null;
  strategy_type: string | null;
  games: number;
  wins: number;
  win_rate: number;
  win_rate_low: number | null;
  win_rate_high: number | null;
  reached_target: number;
  reached_target_rate: number | null;
  turns_to_target_mean: number | null;
  turns_to_target_median: number | null;
  turns_to_target_min: number | null;
  turns_to_target_max: number | null;
  turns_to_target_sd: number | null;
  turns_to_target_p10: number | null;
  turns_to_target_p90: number | null;
  mean_final_score: number;
  sd_final_score: number | null;
  turns: number;
  throws: number;
  busts: number;
  points_per_turn: number | null;
  throws_per_turn: number | null;
  bust_rate: number | null;
};

export type SeatConfig = {
  seat: number;
  name: string;
  player_type: string;
  strategy: { name: string; version: number; type: string; params: Record<string, unknown>; description: string } | null;
};

export type Analysis = {
  simulation: {
    simulation_id: string;
    name: string;
    source: string;
    status: string;
    record_level: "summary" | "turns" | "full";
    master_seed: number;
    n_games_completed: number;
    n_games_requested: number;
    target: number;
    end_rule: string;
    max_turns: number | null;
    face_weights: number[] | null;
    scoring: import("./scoring").Scoring;
    scoring_is_default: boolean;
    created_at: string;
    finished_at: string | null;
    software_version: string;
    single_player: boolean;
    players: SeatConfig[];
  };
  available: { turns: boolean; throws: boolean };
  overview: Overview;
  players: PlayerMetrics[];
  play_position: { rows: { seat: number | null; position: number; games: number; wins: number; win_rate: number; win_rate_low: number; win_rate_high: number }[] };
  distributions: { turns_to_target: Histogram; final_score: Histogram; game_length: Histogram };
  turns: null | {
    end_reasons: { seat: number; turns: number; stop: number; reached_target: number; bust_zero: number; bust_negative: number; mean_turn_score: number; mean_banked_score: number | null; mean_throws: number }[];
    turn_score: Histogram;
    throws_per_turn: Histogram;
  };
  throws: null | {
    n_throws: number;
    faces: { face: string; code: number; count: number; share: number; expected_share: number }[];
    face_test: { chi2: number; df: number; p_value: number | null; impossible_faces: number };
    scores: { score: number; count: number; share: number; expected_share: number }[];
    mean_score: { observed: number; expected: number; standard_error: number };
    turn_ending_rate: { observed: number; expected: number };
  };
};

export type GameRow = {
  game_id: string;
  game_index: number;
  status: string;
  n_rounds: number;
  winner_seats: number[] | null;
  winners: string[] | null;
  scores: number[];
  play_order: number[];
  margin: number;
};

export type GameHistory = {
  game: { game_id: string; game_index: number; status: string; n_rounds: number; n_players: number };
  players: { seat: number; play_order: number; display_name: string; player_type: string; final_score: number; is_winner: boolean; turns_taken: number; total_throws: number; busts: number }[];
  turns: { seat: number; turn_number: number; n_throws: number; end_reason: string; turn_score: number; banked_after: number;
    throws: { throw_number: number; die1: number; die2: number; die3: number; throw_score: number; turn_points_after: number; decision: string | null; reason: string | null }[] }[];
};

export type Comparison = {
  runs: { simulation: { simulation_id: string; name: string; source: string; n_games_completed: number; record_level: string; master_seed: number; target: number; end_rule: string; n_players: number }; overview: Overview; players: PlayerMetrics[] }[];
  strategies: { strategy_version_id: string | null; strategy_name: string; strategy_version: number | null; strategy_type: string | null;
    cells: Record<string, { games: number; wins: number; win_rate: number | null; win_rate_low: number | null; win_rate_high: number | null; points_per_turn: number | null; turns_to_target_mean: number | null; reached_target: number; seats: number[] }> }[];
};
