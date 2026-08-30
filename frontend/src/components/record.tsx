/** Shared record-workspace primitives — the visual vocabulary the CRM screens
 *  are built from: avatars, score rings, stage paths and highlight strips. */
import { ReactNode } from "react";

export function initials(first?: string, last?: string, fallback = "?") {
  const a = (first ?? "").trim()[0] ?? "";
  const b = (last ?? "").trim()[0] ?? "";
  return ((a + b) || fallback).toUpperCase();
}

/** Deterministic tint per person so the same name always gets the same chip. */
export function Avatar({ first, last, size = 34, label }: {
  first?: string; last?: string; size?: number; label?: string;
}) {
  const seed = `${first ?? ""}${last ?? ""}`;
  let hash = 0;
  for (let i = 0; i < seed.length; i++) hash = (hash * 31 + seed.charCodeAt(i)) % 360;
  return (
    <span
      className="avatar"
      title={label}
      style={{
        width: size, height: size, fontSize: size * 0.36,
        // Lightness 34%/28%, not 78%/58%. The label is white, and white on
        // hsl(h 42% 78%) is about 1.7:1 — the initials were a pale suggestion on
        // a pale disc. 34% clears 4.5:1 for every hue including yellow, which is
        // the brightest at any given lightness and therefore the one to size
        // against; picking a value that worked for blue would have failed
        // silently for a third of the alphabet.
        background: `linear-gradient(140deg, hsl(${hash} 45% 34%), hsl(${(hash + 40) % 360} 42% 28%))`,
      }}
    >
      {initials(first, last)}
    </span>
  );
}

/** Circular score gauge — the arc length is the score, the colour is the band. */
export function ScoreRing({ score, rating, size = 54 }: { score: number; rating: string; size?: number }) {
  const stroke = size < 50 ? 4 : 5;
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  const dash = (Math.max(0, Math.min(100, score)) / 100) * circumference;
  const colour = rating === "hot" ? "#c2536b" : rating === "warm" ? "#c98a3e" : "#8a86a3";
  return (
    <span className="score-ring" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(31,30,38,0.10)" strokeWidth={stroke} />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none" stroke={colour} strokeWidth={stroke}
          strokeLinecap="round" strokeDasharray={`${dash} ${circumference}`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      <b style={{ fontSize: size * 0.3 }}>{score}</b>
    </span>
  );
}

/** Chevron path showing progression through a set of stages. */
export function Path({ stages, current, onPick, lostKey }: {
  stages: { key: string; label: string }[];
  current: string;
  onPick?: (key: string) => void;
  lostKey?: string;
}) {
  const index = stages.findIndex((s) => s.key === current);
  const isLost = lostKey !== undefined && current === lostKey;
  return (
    <div className="path" role="tablist">
      {stages.map((s, i) => {
        const done = !isLost && i < index;
        const active = s.key === current;
        return (
          <button
            key={s.key}
            role="tab"
            aria-selected={active}
            className={`path-step${done ? " done" : ""}${active ? " active" : ""}${active && isLost ? " lost" : ""}`}
            onClick={onPick ? () => onPick(s.key) : undefined}
            disabled={!onPick}
          >
            <span>{s.label}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Key-field strip that sits directly under a record title. */
export function Highlights({ items }: {
  items: { label: string; value: ReactNode; hint?: ReactNode; tone?: string }[];
}) {
  return (
    <div className="highlights">
      {items.map((h) => (
        <div key={h.label} className={`highlight${h.tone ? ` is-${h.tone}` : ""}`}>
          <div className="label">{h.label}</div>
          <div className="value">{h.value}</div>
          {h.hint && <div className="hint">{h.hint}</div>}
        </div>
      ))}
    </div>
  );
}
