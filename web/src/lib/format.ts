const intFmt = new Intl.NumberFormat("en-GB");

export function int(n: number | null | undefined): string {
  return n === null || n === undefined ? "–" : intFmt.format(Math.round(n));
}

export function num(n: number | null | undefined, digits = 2): string {
  return n === null || n === undefined
    ? "–"
    : n.toLocaleString("en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function pct(n: number | null | undefined, digits = 1): string {
  return n === null || n === undefined ? "–" : `${(n * 100).toFixed(digits)}%`;
}

export function signed(n: number): string {
  return n > 0 ? `+${n}` : n < 0 ? `−${Math.abs(n)}` : "0";
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "–";
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

export function when(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export const FACE_SYMBOLS = ["9", "10", "J", "Q", "K", "A"]; // face codes 0-5 (decision 12)

export const END_REASON: Record<string, string> = {
  stop: "banked",
  bust_zero: "no score",
  bust_negative: "penalty",
  reached_target: "reached the target",
  game_over: "game over",
};
