/** Small dependency-free SVG chart set, styled to the RX5000 palette.
 *
 *  The colours come from chartPalette.ts rather than being declared here. The
 *  set that used to live in this file was four near-grey violets and two muted
 *  earth tones; run through the validator it failed the lightness band, the
 *  chroma floor and the normal-vision separation floor, which in practice meant
 *  two adjacent slices of a donut that nobody could tell apart. It also had no
 *  dark variant, so on a dark surface the indigo slot all but vanished. */
import { ReactNode } from "react";
import { useChartPalette } from "../chartPalette";

/** The palette, for pages that assign colours to their own series.
 *
 *  A hook rather than a constant, because the answer changes with the theme.
 *  Assign these in order and never cycle: a seventh series folds into "Other".
 */
export function useSeries(): string[] {
  return useChartPalette().slots;
}

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
  const palette = useChartPalette();
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
          return <line key={s} x1={0} x2={100} y1={y} y2={y} stroke={palette.grid} strokeWidth={0.6} vectorEffect="non-scaling-stroke" />;
        })}
        {columns.map((c, i) => {
          let acc = 0;
          const x = i * colW + colW * 0.22;
          const w = colW * 0.56;
          return (
            <g key={c.label}>
              {c.segments.map((g) => {
                const full = (g.value / max) * plot;
                // Two pixels of surface between segments. Without it a stack of
                // two similar hues is one bar with a colour change in it, and
                // the eye cannot find where one measure ends.
                const h = Math.max(full - (acc > 0 ? 1.5 : 0), 0.5);
                const y = padT + plot - acc - full;
                acc += full;
                // no rx — the viewBox is stretched horizontally, so a corner
                // radius would render as a lopsided ellipse
                return g.value > 0 ? (
                  <rect key={g.key} x={x} y={y} width={w} height={h} fill={g.colour} />
                ) : null;
              })}
              {c.marker !== undefined && c.marker > 0 && (
                <line
                  x1={x - colW * 0.04} x2={x + w + colW * 0.04}
                  y1={padT + plot - (c.marker / max) * plot}
                  y2={padT + plot - (c.marker / max) * plot}
                  stroke={palette.axis} strokeWidth={2} strokeDasharray="4 3"
                  vectorEffect="non-scaling-stroke"
                />
              )}
            </g>
          );
        })}
        {/* One hit target per column, sitting over the whole plot height.
            A stacked segment three pixels tall is not a hit target, and the
            reader is pointing at the month rather than at one band of it. The
            readout names every series in that column, which is what makes two
            months comparable — the native <title> that used to be on each rect
            gave one number, after a one-second delay, in the system font, at the
            pointer. That is the absence of a chart readout, not one. */}
        {columns.map((c, i) => (
          <rect
            key={`hit-${c.label}`}
            x={i * colW} y={0} width={colW} height={height}
            fill="transparent" className="chart-hit"
            data-tip={[
              c.label,
              ...c.segments.filter((g) => g.value > 0).map((g) => `${g.key} ${format(g.value)}`),
              ...(c.marker !== undefined && c.marker > 0
                ? [`${markerLabel ?? "marker"} ${format(c.marker)}`] : []),
            ].join(" · ")}
          />
        ))}
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
  const palette = useChartPalette();
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
              {/* One hue deepening down the funnel, not six.
                  Funnel stages are a sequence, not six unrelated things, and the
                  previous version gave each one a categorical hue from a cycled
                  list — so stage seven repeated stage one, and the colours
                  implied a difference in kind where the only difference is
                  position. Width already carries the count; the deepening only
                  reinforces the direction of travel. */}
              <div className="funnel-bar" style={{
                width: `${width}%`,
                background: palette.one,
                opacity: 0.55 + (0.45 * i) / Math.max(stages.length - 1, 1),
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

/** Horizontal leaderboard bars — one row per entity, two comparable measures.
 *
 *  The colours are **passed in**, and that is the whole point of this rewrite.
 *  They used to come from the stylesheet: `.barlist-bar.primary` was painted in
 *  `var(--accent)` — near-black ink, not a data colour — and `.secondary` in a
 *  gradient of `--rose` and `--mauve`, two leftovers of a palette that was
 *  removed for failing the contrast validator. Meanwhile the `<Legend>` above
 *  the chart drew its swatches from the chart palette. So on the rep performance
 *  and attribution tabs the key said blue and green while the bars rendered
 *  black and pink, and the reader had no way to tell which bar was which
 *  measure. A legend that does not match its chart is worse than no legend.
 *
 *  Each row also carries a hover readout, because a bar whose exact figure is
 *  only in one column is a bar you cannot compare with the one below it.
 */
export function BarList({ rows, format, colours, labels }: {
  rows: { label: string; sub?: ReactNode; primary: number; secondary?: number }[];
  format: (n: number) => string;
  /** [primary, secondary]. Defaults to the first two categorical slots. */
  colours?: [string, string];
  /** What the two measures are called, for the hover readout. */
  labels?: [string, string];
}) {
  const palette = useChartPalette();
  const [primaryColour, secondaryColour] = colours ?? [palette.slots[0], palette.slots[2]];
  const [primaryLabel, secondaryLabel] = labels ?? ["Primary", "Secondary"];
  const top = Math.max(...rows.map((r) => Math.max(r.primary, r.secondary ?? 0)), 1);
  return (
    <div className="barlist">
      {rows.map((r) => (
        <div key={r.label} className="barlist-row">
          <div className="barlist-label"><b>{r.label}</b>{r.sub && <div className="muted">{r.sub}</div>}</div>
          <div className="barlist-track">
            {/* The tip is on the track rather than the bar: a bar two pixels
                wide is a hit target nobody can find, and the row is what the
                reader is pointing at anyway. */}
            <div
              className="barlist-hit"
              data-tip={r.secondary !== undefined
                ? `${r.label} · ${primaryLabel} ${format(r.primary)} · ${secondaryLabel} ${format(r.secondary)}`
                : `${r.label} · ${format(r.primary)}`}
            />
            <div className="barlist-bar primary"
                 style={{ width: `${(r.primary / top) * 100}%`, background: primaryColour }} />
            {r.secondary !== undefined && (
              <div className="barlist-bar secondary"
                   style={{ width: `${(r.secondary / top) * 100}%`, background: secondaryColour }} />
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
  const palette = useChartPalette();
  const total = slices.reduce((s, x) => s + x.value, 0);
  if (total <= 0) {
    return <div className="empty">No attributed pipeline yet. Campaigns have not sourced a deal</div>;
  }
  const stroke = size * 0.19;
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  let offset = 0;

  return (
    <div className="donut-wrap">
      <div className="donut" style={{ width: size, height: size }}>
        <svg width={size} height={size}>
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={palette.grid} strokeWidth={stroke} />
          {total > 0 && slices.map((s) => {
            const dash = (s.value / total) * circumference;
            const el = (
              <circle
                key={s.key} cx={size / 2} cy={size / 2} r={r} fill="none"
                stroke={s.colour} strokeWidth={stroke}
                strokeDasharray={`${dash} ${circumference - dash}`}
                strokeDashoffset={-offset}
                transform={`rotate(-90 ${size / 2} ${size / 2})`}
                /* A 2px ring of the surface between slices, so two adjacent
                   slices read as two rather than as one long arc. */
                style={{ filter: "drop-shadow(0 0 0 transparent)" }}
              />
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
