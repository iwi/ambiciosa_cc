"""Run simulations: many automated games, in parallel, stored in DuckDB.

Workers play chunks of consecutive game indices and return Arrow batches.
One thread in this process writes every batch to DuckDB (a DuckDB file has a
single writer), commits it together with the completed-game count, and keeps
the progress figures that `progress()` reports.

Because each game's seed comes only from the master seed and its index
(see seeds.py), the stored games are identical for any number of workers or
any chunk size.

Cancelling stops new chunks from starting; chunks already being played are
finished and stored, and the run ends with status 'cancelled'.
"""

from __future__ import annotations

import math
import multiprocessing as mp
import signal
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, replace

import pyarrow as pa

from ..engine import Game
from ..persistence import Database
from ..strategies import play_automated
from .config import SimulationConfig
from .recorder import BatchRecorder, needs_history
from .seeds import game_seed

FINAL_STATUSES = ("completed", "cancelled", "failed")


# ----------------------------------------------------------------- playing


def replay_game(config: SimulationConfig, game_index: int, *, record_history: bool = True) -> Game:
    """Play one game of a run again, exactly as it was played in the run."""
    if not 0 <= game_index < config.n_games:
        raise ValueError(f"game_index must be between 0 and {config.n_games - 1}")
    return play_automated(
        config.game_config(), game_seed(config.master_seed, game_index), record_history=record_history
    )


def play_chunk(
    config: SimulationConfig, simulation_id: uuid.UUID, start: int, stop: int
) -> dict[str, pa.Table]:
    """Play games start..stop-1 of a run and return their rows as Arrow tables."""
    game_config = config.game_config()
    history = needs_history(config.record_level)
    recorder = BatchRecorder(simulation_id, config.record_level)
    clock = time.perf_counter
    for index in range(start, stop):
        t0 = clock()
        game = play_automated(game_config, game_seed(config.master_seed, index), record_history=history)
        recorder.add(game, index, (clock() - t0) * 1000.0)
    return recorder.to_arrow()


# Worker processes receive the config once, at start-up, instead of with every chunk.
_worker_state: tuple[SimulationConfig, uuid.UUID] | None = None


def _init_worker(config: SimulationConfig, simulation_id: uuid.UUID) -> None:
    global _worker_state
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # Ctrl+C is handled by the parent as a cancel
    _worker_state = (config, simulation_id)


def _worker_chunk(start: int, stop: int) -> dict[str, pa.Table]:
    assert _worker_state is not None, "worker not initialised"
    config, simulation_id = _worker_state
    return play_chunk(config, simulation_id, start, stop)


CHUNKS_PER_WORKER = 4  # at least this many chunks per worker: even load and frequent progress


def chunk_bounds(n_games: int, chunk_size: int, workers: int) -> list[tuple[int, int]]:
    """Split 0..n_games-1 into chunks of at most chunk_size games.

    Smaller runs get smaller chunks so that every worker has several, which
    balances the load and keeps progress moving. Chunking never changes results.
    """
    size = max(1, min(chunk_size, math.ceil(n_games / (workers * CHUNKS_PER_WORKER))))
    return [(s, min(s + size, n_games)) for s in range(0, n_games, size)]


# ---------------------------------------------------------------- progress


@dataclass(frozen=True)
class Progress:
    simulation_id: uuid.UUID
    status: str
    games_completed: int
    games_requested: int
    elapsed_s: float
    error: str | None = None

    @property
    def fraction(self) -> float:
        return self.games_completed / self.games_requested if self.games_requested else 1.0

    @property
    def rate(self) -> float:
        """Games stored per second so far."""
        return self.games_completed / self.elapsed_s if self.elapsed_s > 0 else 0.0

    @property
    def eta_s(self) -> float | None:
        if self.status in FINAL_STATUSES:
            return 0.0
        rate = self.rate
        return None if rate == 0 else (self.games_requested - self.games_completed) / rate

    @property
    def done(self) -> bool:
        return self.status in FINAL_STATUSES


class _Run:
    def __init__(self, config: SimulationConfig, simulation_id: uuid.UUID) -> None:
        self.config = config
        self.simulation_id = simulation_id
        self.cancel_event = threading.Event()
        self.finished = threading.Event()
        self.lock = threading.Lock()
        self.started = time.perf_counter()
        self.ended: float | None = None
        self.progress = Progress(simulation_id, "running", 0, config.n_games, 0.0)
        self.thread: threading.Thread | None = None

    def snapshot(self) -> Progress:
        with self.lock:
            end = self.ended if self.ended is not None else time.perf_counter()
            return replace(self.progress, elapsed_s=end - self.started)

    def update(self, **changes) -> None:
        with self.lock:
            if changes.get("status") in FINAL_STATUSES:
                self.ended = time.perf_counter()
            self.progress = replace(self.progress, **changes)


# ------------------------------------------------------------------ runner


class SimulationRunner:
    """Starts simulations in the background and reports their progress.

    One runner per database. Several runs may be started; their batches are
    written one at a time through each run's own connection.
    """

    def __init__(self, db: Database, *, mp_context: str = "spawn") -> None:
        self.db = db
        self.mp_context = mp_context
        self._runs: dict[uuid.UUID, _Run] = {}
        self._write_lock = threading.Lock()

    # public API ------------------------------------------------------------

    def start(self, config: SimulationConfig) -> uuid.UUID:
        """Store the run and its strategies, start playing, and return the simulation id."""
        if config.has_humans:
            raise ValueError("simulations need automated players only; play games with humans interactively")
        specs = [self.db.resolve_strategy(seat.strategy) for seat in config.players]
        config = config.with_strategies(specs)
        simulation_id = uuid.uuid4()
        self.db.create_simulation(
            simulation_id,
            name=config.name,
            master_seed=config.master_seed,
            n_games_requested=config.n_games,
            record_level=config.record_level,
            config=config.stored_dict(),
        )
        run = _Run(config, simulation_id)
        self._runs[simulation_id] = run
        run.thread = threading.Thread(
            target=self._execute, args=(run,), name=f"simulation-{simulation_id}", daemon=True
        )
        run.thread.start()
        return simulation_id

    def progress(self, simulation_id: uuid.UUID) -> Progress:
        return self._run(simulation_id).snapshot()

    def cancel(self, simulation_id: uuid.UUID) -> None:
        self._run(simulation_id).cancel_event.set()

    def wait(self, simulation_id: uuid.UUID, timeout: float | None = None) -> Progress:
        run = self._run(simulation_id)
        run.finished.wait(timeout)
        return run.snapshot()

    def run(
        self,
        config: SimulationConfig,
        on_progress: Callable[[Progress], None] | None = None,
        interval: float = 0.5,
    ) -> Progress:
        """Run a simulation to the end (Ctrl+C cancels it) and return the final progress."""
        sim_id = self.start(config)
        run = self._runs[sim_id]
        try:
            while not run.finished.wait(interval):
                if on_progress:
                    on_progress(run.snapshot())
        except KeyboardInterrupt:
            self.cancel(sim_id)
            run.finished.wait()
        final = run.snapshot()
        if on_progress:
            on_progress(final)
        return final

    # internals -------------------------------------------------------------

    def _run(self, simulation_id: uuid.UUID) -> _Run:
        try:
            return self._runs[simulation_id]
        except KeyError:
            raise KeyError(f"no simulation {simulation_id} started by this runner") from None

    def _store(self, run: _Run, conn, tables: dict[str, pa.Table]) -> None:
        with self._write_lock:
            n = self.db.insert_batch(run.simulation_id, tables, conn)
        run.update(games_completed=run.progress.games_completed + n)

    def _execute(self, run: _Run) -> None:
        conn = self.db.cursor()
        status, error = "completed", None
        try:
            cfg = run.config
            chunks = chunk_bounds(cfg.n_games, cfg.chunk_size, cfg.workers)
            if cfg.workers == 1 or len(chunks) == 1:
                self._execute_inline(run, conn, chunks)
            else:
                self._execute_pool(run, conn, chunks)
            if run.cancel_event.is_set() and run.progress.games_completed < cfg.n_games:
                status = "cancelled"
        except BaseException as exc:  # noqa: BLE001 - every failure must be recorded
            status = "failed"
            error = "".join(traceback.format_exception_only(exc)).strip()
            if isinstance(exc, BrokenProcessPool):
                error += (
                    " Worker processes could not start. A script that runs simulations with several "
                    "workers must start them under `if __name__ == \"__main__\":`, and must be run from a "
                    "file, not from standard input; or use workers=1."
                )
        finally:
            try:
                with self._write_lock:
                    self.db.set_status(run.simulation_id, status, conn)
            finally:
                conn.close()
                run.update(status=status, error=error)
                run.finished.set()

    def _execute_inline(self, run: _Run, conn, chunks: list[tuple[int, int]]) -> None:
        for start, stop in chunks:
            if run.cancel_event.is_set():
                return
            self._store(run, conn, play_chunk(run.config, run.simulation_id, start, stop))

    def _execute_pool(self, run: _Run, conn, chunks: list[tuple[int, int]]) -> None:
        cfg = run.config
        workers = min(cfg.workers, len(chunks))
        todo = iter(chunks)
        pending: set[Future] = set()
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=mp.get_context(self.mp_context),
            initializer=_init_worker,
            initargs=(cfg, run.simulation_id),
        ) as pool:

            def submit_next() -> None:
                nxt = next(todo, None)
                if nxt is not None:
                    pending.add(pool.submit(_worker_chunk, *nxt))

            try:
                for _ in range(2 * workers):  # keep every worker busy, but no more queued than that
                    submit_next()
                while pending:
                    done, _ = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
                    for fut in done:
                        pending.discard(fut)
                        if fut.cancelled():
                            continue
                        self._store(run, conn, fut.result())
                        if not run.cancel_event.is_set():
                            submit_next()
                    if run.cancel_event.is_set():
                        for fut in list(pending):
                            if fut.cancel():
                                pending.discard(fut)
            except BaseException:
                pool.shutdown(wait=True, cancel_futures=True)
                raise
