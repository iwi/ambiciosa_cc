-- Ambiciosa Simulator DuckDB schema, version 3 (Phase 1 document, "DuckDB schema").
-- Every statement is idempotent, so applying it to an existing file is safe.

CREATE TYPE IF NOT EXISTS strategy_type AS ENUM ('threshold','max_throws','combined','random','game_state');
CREATE TYPE IF NOT EXISTS run_source    AS ENUM ('simulation','interactive');
CREATE TYPE IF NOT EXISTS run_status    AS ENUM ('pending','running','completed','cancelled','failed');
CREATE TYPE IF NOT EXISTS record_level  AS ENUM ('summary','turns','full');
CREATE TYPE IF NOT EXISTS game_status   AS ENUM ('finished','unfinished','abandoned');
CREATE TYPE IF NOT EXISTS turn_end      AS ENUM ('stop','bust_zero','bust_negative','reached_target','game_over');
CREATE TYPE IF NOT EXISTS decision      AS ENUM ('CONTINUE','STOP');

-- Housekeeping: which schema version this file holds.
CREATE TABLE IF NOT EXISTS schema_version (
  version    INTEGER NOT NULL,
  applied_at TIMESTAMPTZ NOT NULL
);

-- Immutable strategy versions: editing a strategy creates a new version,
-- so past results always point at the exact parameters used.
CREATE TABLE IF NOT EXISTS strategy (
  strategy_version_id UUID PRIMARY KEY,
  strategy_id   UUID NOT NULL,           -- stable across versions
  version       INTEGER NOT NULL,
  name          VARCHAR NOT NULL,
  description   VARCHAR,
  type          strategy_type NOT NULL,
  params        JSON NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL,
  UNIQUE (strategy_id, version)
);

-- Version 2: strategies removed from the library but kept because results use
-- them. (A separate table, because DuckDB cannot add columns to a table that
-- other tables reference.)
CREATE TABLE IF NOT EXISTS strategy_archive (
  strategy_id UUID PRIMARY KEY,
  archived_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS simulation (
  simulation_id     UUID PRIMARY KEY,
  source            run_source NOT NULL,
  name              VARCHAR,
  created_at        TIMESTAMPTZ NOT NULL,
  finished_at       TIMESTAMPTZ,
  status            run_status NOT NULL,
  master_seed       UBIGINT NOT NULL,
  n_games_requested INTEGER NOT NULL,
  n_games_completed INTEGER NOT NULL DEFAULT 0,
  record_level      record_level NOT NULL,
  software_version  VARCHAR NOT NULL,
  config            JSON NOT NULL         -- SimulationConfig: target, end_rule, max_turns,
                                          -- face_weights, player seats (strategy version ids)
);

CREATE TABLE IF NOT EXISTS game (
  game_id       UUID PRIMARY KEY,
  simulation_id UUID NOT NULL REFERENCES simulation,
  game_index    INTEGER NOT NULL,        -- with master_seed, reproduces the game
  status        game_status NOT NULL,
  n_players     UTINYINT NOT NULL,
  n_rounds      INTEGER NOT NULL,        -- turns taken by the first player
  duration_ms   DOUBLE,
  UNIQUE (simulation_id, game_index)
);

CREATE TABLE IF NOT EXISTS game_player (
  game_id        UUID NOT NULL REFERENCES game,
  seat           UTINYINT NOT NULL,      -- position in the configuration
  play_order     UTINYINT NOT NULL,      -- position after randomisation
  player_type    VARCHAR NOT NULL CHECK (player_type IN ('human','automated')),
  display_name   VARCHAR NOT NULL,
  strategy_version_id UUID REFERENCES strategy,  -- NULL for humans
  final_score    INTEGER NOT NULL,
  is_winner      BOOLEAN NOT NULL,
  turns_taken    INTEGER NOT NULL,
  total_throws   INTEGER NOT NULL,
  busts          INTEGER NOT NULL,
  PRIMARY KEY (game_id, seat)
);

-- turn and throw have no primary key (version 3): measured in Phase 7, the index made
-- inserts five times slower and files five times larger without speeding up any query.
-- Each row is still unique: a batch writes its game rows first, in the same transaction,
-- and the game table's key rejects a game stored twice.
-- Natural key of turn: (game_id, seat, turn_number); of throw: + throw_number.
CREATE TABLE IF NOT EXISTS turn (        -- record_level 'turns' or 'full'
  game_id      UUID NOT NULL,
  seat         UTINYINT NOT NULL,
  turn_number  INTEGER NOT NULL,
  n_throws     UTINYINT NOT NULL,
  end_reason   turn_end NOT NULL,
  turn_score   INTEGER NOT NULL,
  banked_after INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS throw (       -- record_level 'full' only
  game_id      UUID NOT NULL,
  seat         UTINYINT NOT NULL,
  turn_number  INTEGER NOT NULL,
  throw_number UTINYINT NOT NULL,
  die1 UTINYINT NOT NULL, die2 UTINYINT NOT NULL, die3 UTINYINT NOT NULL,  -- Face codes 0-5
  throw_score  SMALLINT NOT NULL,
  turn_points_after INTEGER NOT NULL,    -- accumulated (or bust value)
  decision     decision,                 -- NULL when the throw ended the turn
  reason       VARCHAR                   -- strategy explanation, interactive games only
);

-- One row per player per game, with everything Analysis and R usually need.
-- A shared win counts as 1/n of a win (equal-turns details).
CREATE OR REPLACE VIEW v_player_results AS
SELECT
  s.simulation_id,
  s.source,
  s.name                  AS simulation_name,
  g.game_id,
  g.game_index,
  g.status                AS game_status,
  g.n_players,
  g.n_rounds,
  gp.seat,
  gp.play_order,
  gp.player_type,
  gp.display_name,
  gp.strategy_version_id,
  st.strategy_id,
  st.name                 AS strategy_name,
  st.version              AS strategy_version,
  st.type                 AS strategy_type,
  gp.final_score,
  gp.is_winner,
  CASE WHEN gp.is_winner
       THEN 1.0 / count(*) FILTER (WHERE gp.is_winner) OVER (PARTITION BY g.game_id)
       ELSE 0.0 END       AS win_share,
  gp.turns_taken,
  gp.total_throws,
  gp.busts,
  gp.final_score  / nullif(gp.turns_taken, 0) AS points_per_turn,
  gp.total_throws / nullif(gp.turns_taken, 0) AS throws_per_turn,
  gp.busts        / nullif(gp.turns_taken, 0) AS bust_rate
FROM game_player gp
JOIN game g        USING (game_id)
JOIN simulation s  USING (simulation_id)
LEFT JOIN strategy st USING (strategy_version_id);

-- One row per simulation, seat and strategy: the headline numbers of a run.
CREATE OR REPLACE VIEW v_strategy_summary AS
SELECT
  simulation_id,
  any_value(source)          AS source,
  any_value(simulation_name) AS simulation_name,
  seat,
  any_value(display_name)    AS display_name,
  strategy_version_id,
  any_value(strategy_name)   AS strategy_name,
  any_value(strategy_version) AS strategy_version,
  any_value(strategy_type)   AS strategy_type,
  count(*)                   AS games,
  count(*) FILTER (WHERE game_status = 'finished') AS games_finished,
  sum(win_share)             AS wins,
  avg(win_share)             AS win_rate,
  avg(final_score)           AS mean_final_score,
  avg(turns_taken) FILTER (WHERE is_winner) AS mean_turns_to_win,
  sum(final_score)  / nullif(sum(turns_taken), 0) AS points_per_turn,
  sum(total_throws) / nullif(sum(turns_taken), 0) AS throws_per_turn,
  sum(busts)        / nullif(sum(turns_taken), 0) AS bust_rate
FROM v_player_results
GROUP BY simulation_id, seat, strategy_version_id;
