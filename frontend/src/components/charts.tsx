/** Small dependency-free SVG chart set, styled to the RX3000 palette. */
import { ReactNode } from "react";

const ROSE = "#f0b4b6";
const MAUVE = "#97829c";
const ACCENT = "#6a6485";
const INDIGO = "#3b3e56";
export const SERIES = [INDIGO, MAUVE, ROSE, ACCENT, "#c98a3e", "#7fa9a0"];

/** Round an axis maximum up to a readable tick interval. */
function niceScale(max: number, ticks = 4) {
  if (max <= 0) return { max: 1, steps: [0, 1] };
  const rough = max / ticks;
  const mag = Math.pow(10, Math.floor(Math.log10(rough)));
  const norm = rough / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
  const top = Math.ceil(max / step) * step;
  const steps: number[] = [];
  for (let v = 0; v <= top + 1e-9; v += step) steps.push(v);
  return { max: top, steps };
}

export type Column = {
  label: string;
  /** Stacked from the baseline upward. */
  segments: { key: string; value: number; colour: string }[];
  /** Optional horizontal marker drawn across the column (e.g. weighted forecast). */
  marker?: number;
};

/** Stacked column chart with a value axis, gridlines and an optional marker. */
export function ColumnChart({ columns, format, height = 230, markerLabel }: {
  columns: Column[];
  format: (n: number) => string;
  height?: number;
  markerLabel?: string;
}) {
  const totals = columns.map((c) => c.segments.reduce((s, g) => s + g.value, 0));
  const peak = Math.max(...totals, ...columns.map((c) => c.marker ?? 0), 0);
  const { max, steps } = niceScale(peak);
  // padB stays small: the x labels are rendered as real DOM below the SVG, so
  // the plot should run almost to the bottom edge or a gap opens up under it.
  const padL = 68, padB = 6, padT = 10;
  const plot = height - padB - padT;
  const colW = 100 / Math.max(columns.length, 1);

  return (
    <div className="chart">
      <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" style={{ height, width: "100%" }}>
        {steps.map((s) => {
          const y = padT + plot - (s / max) * plot;
          return <line key={s} x1={0} x2={100} y1={y} y2={y} stroke="rgba(31,30,38,0.09)" strokeWidth={0.6} vectorEffect="non-scaling-stroke" />;
        })}
        {columns.map((c, i) => {
          let acc = 0;
          const x = i * colW + colW * 0.22;
          const w = colW * 0.56;
          return (
            <g key={c.label}>
              {c.segments.map((g) => {
                const h = (g.value / max) * plot;
                const y = padT + plot - acc - h;
                acc += h;
                // no rx — the viewBox is stretched horizontally, so a corner
                // radius would render as a lopsided ellipse
                return g.value > 0 ? (
                  <rect key={g.key} x={x} y={y} width={w} height={h} fill={g.colour}>
                    <title>{`${c.label} · ${g.key}: ${format(g.value)}`}</title>
                  </rect>
                ) : null;
              })}
              {c.marker !== undefined && c.marker > 0 && (
                <line
                  x1={x - colW * 0.04} x2={x + w + colW * 0.04}
                  y1={padT + plot - (c.marker / max) * plot}
                  y2={padT + plot - (c.marker / max) * plot}
                  stroke={INDIGO} strokeWidth={2} strokeDasharray="4 3"
                  vectorEffect="non-scaling-stroke"
                >
                  <title>{`${c.label} · ${markerLabel ?? "marker"}: ${format(c.marker)}`}</title>
                </line>
              )}
            </g>
          );
        })}
      </svg>
      {/* axis labels sit outside the stretched SVG so text never distorts */}
      <div className="chart-yaxis" style={{ height, paddingTop: padT, paddingBottom: padB, width: padL }}>
        {[...steps].reverse().map((s) => <span key={s}>{format(s)}</span>)}
      </div>
      <div className="chart-xaxis">
        {columns.map((c) => <span key={c.label} style={{ width: `${colW}%` }}>{c.label}</span>)}
      </div>
    </div>
  );
}

export function Legend({ items }: { items: { key: string; colour: string; dashed?: boolean }[] }) {
  return (
    <div className="legend">
      {items.map((i) => (
        <span key={i.key}>
          <i style={i.dashed
            ? { background: "none", borderTop: `2px dashed ${i.colour}`, height: 0 }
            : { background: i.colour }} />
          {i.key}
        </span>
      ))}
    </div>
  );
}

/** Tapered funnel with stage-to-stage drop-off. */
export function FunnelChart({ stages }: { stages: { stage: string; count: number; conversion: number }[] }) {
  const top = Math.max(...stages.map((s) => s.count), 1);
  return (
    <div className="funnel">
      {stages.map((s, i) => {
        const width = Math.max((s.count / top) * 100, 4);
        const prev = i > 0 ? stages[i - 1] : null;
        const dropped = prev ? prev.count - s.count : 0;
        return (
          <div key={s.stage} className="funnel-row">
            <div className="funnel-label">
              <b>{s.stage}</b>
              <span className="muted">{s.count}</span>
            </div>
            <div className="funnel-track">
              <div className="funnel-bar" style={{
                width: `${width}%`,
                background: `linear-gradient(90deg, ${SERIES[i % SERIES.length]}, ${ACCENT})`,
              }} />
            </div>
            <div className="funnel-side">
              <b>{s.conversion}%</b>
              {/* a stage can exceed the one before it — opportunities may be raised
                  directly rather than via a converted lead — so don't call that "no drop-off" */}
              {prev && (
                <span className="muted">
                  {dropped > 0 ? `−${dropped} dropped`
                    : dropped < 0 ? `+${-dropped} added directly`
                    : "no change"}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Horizontal leaderboard bars — one row per entity, two comparable measures. */
export function BarList({ rows, format }: {
  rows: { label: string; sub?: ReactNode; primary: number; secondary?: number }[];
  format: (n: number) => string;
}) {
  const top = Math.max(...rows.map((r) => Math.max(r.primary, r.secondary ?? 0)), 1);
  return (
    <div className="barlist">
      {rows.map((r) => (
        <div key={r.label} className="barlist-row">
          <div className="barlist-label"><b>{r.label}</b>{r.sub && <div className="muted">{r.sub}</div>}</div>
          <div className="barlist-track">
            <div className="barlist-bar primary" style={{ width: `${(r.primary / top) * 100}%` }} />
            {r.secondary !== undefined && (
              <div className="barlist-bar secondary" style={{ width: `${(r.secondary / top) * 100}%` }} />
            )}
          </div>
          <div className="barlist-value">{format(r.primary)}</div>
        </div>
      ))}
    </div>
  );
}

/** Donut for share-of-total breakdowns. */
export function Donut({ slices, size = 168, format }: {
  slices: { key: string; value: number; colour: string }[];
  size?: number;
  format: (n: number) => string;
}) {
  const total = slices.reduce((s, x) => s + x.value, 0);
  if (total <= 0) {
    return <div className="empty">No attributed pipeline yet — campaigns have not sourced a deal</div>;
  }
  const stroke = size * 0.19;
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  let offset = 0;

  return (
    <div className="donut-wrap">
      <div className="donut" style={{ width: size, height: size }}>
        <svg width={size} height={size}>
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(31,30,38,0.07)" strokeWidth={stroke} />
          {total > 0 && slices.map((s) => {
            const dash = (s.value / total) * circumference;
            const el = (
              <circle
                key={s.key} cx={size / 2} cy={size / 2} r={r} fill="none"
                stroke={s.colour} strokeWidth={stroke}
                strokeDasharray={`${dash} ${circumference - dash}`}
                strokeDashoffset={-offset}
                transform={`rotate(-90 ${size / 2} ${size / 2})`}
              >
                <title>{`${s.key}: ${format(s.value)}`}</title>
              </circle>
            );
            offset += dash;
            return el;
          })}
        </svg>
        <div className="donut-centre">
          <b>{format(total)}</b>
          <span>total</span>
        </div>
      </div>
      <div className="donut-key">
        {slices.filter((s) => s.value > 0).map((s) => (
          <div key={s.key}>
            <i style={{ background: s.colour }} />
            <span>{s.key}</span>
            <b>{format(s.value)}</b>
            <span className="muted">{total ? Math.round((s.value / total) * 100) : 0}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}
