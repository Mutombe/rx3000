/** A chart for a report this component has never seen before.
 *
 *  Reports here are *described* — every column carries a `kind`, an `align` and
 *  whether it totals, so one chart can be derived from any of the eighty-eight
 *  report definitions. A bespoke chart per report is a promise nobody keeps past
 *  the first dozen.
 *
 *  What it works out for itself, and why:
 *
 *    - **the measures** — money and number columns, and anything the report
 *      totals, because a column worth summing is a column worth drawing;
 *    - **the label** — the first date column if there is one, so a time series
 *      stays in time order instead of being sorted by size, otherwise the first
 *      text column;
 *    - **the form** — a line for time (trend), columns for categories
 *      (magnitude). Not a preference: those are the jobs those forms do;
 *    - **the colour** — ONE hue for one series. Colouring each bar differently
 *      double-encodes length as hue and spends the only free channel on
 *      information the bar length already carries. Distinct hues appear only
 *      where the series genuinely differ in identity, in a fixed order, never
 *      cycled — past the last slot the tail folds into "Other", because a
 *      generated ninth hue is indistinguishable from an existing one to a
 *      colour-blind reader.
 *
 *  Everything a reader might want to slice by is a control rather than a guess:
 *  which measure, how to aggregate, what to break down by, how many to show. The
 *  table beside it is the exhaustive view, so the chart never has to be complete
 *  — only honest about what it is showing.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import Select from "./Select";
import { useChartPalette } from "../chartPalette";

export interface ChartCol {
  key: string; header: string; kind: string; align: string; total?: boolean;
}

/* The palette moved to chartPalette.ts so this chart and the deal charts cannot
   drift apart, and so both follow the theme. Only the slot *count* is a constant
   here — it decides when a seventh series folds into "Other", which is the same
   number in either theme. */
const MAX_SERIES = 6;

type Agg = "sum" | "avg" | "count" | "max";
const AGGS: { value: Agg; label: string }[] = [
  { value: "sum", label: "Total" },
  { value: "avg", label: "Average" },
  { value: "max", label: "Highest" },
  { value: "count", label: "Count of rows" },
];

const NUMERIC = ["money", "number", "int", "float", "quantity", "currency", "percent"];
const isMeasure = (c: ChartCol) =>
  NUMERIC.includes(c.kind) || c.total === true || (c.align === "right" && c.kind !== "date");
const isDate = (c: ChartCol) => c.kind === "date" || /date|day|month|period|when/i.test(c.key);

function aggregate(values: number[], how: Agg): number {
  if (!values.length) return 0;
  if (how === "count") return values.length;
  if (how === "avg") return values.reduce((s, v) => s + v, 0) / values.length;
  if (how === "max") return Math.max(...values);
  return values.reduce((s, v) => s + v, 0);
}

/** Axis ticks are abbreviated; the tooltip and the summary keep full precision.
 *  An axis labelled "4,000,000.00" spends seventy pixels of plot on six zeros
 *  and two decimals nobody reads at that scale — the reader wants the order of
 *  magnitude there and the exact figure on hover. */
function tickLabel(n: number, money: boolean): string {
  const sign = n < 0 ? "-" : "";
  const v = Math.abs(n);
  const unit = money ? "$" : "";
  if (v >= 1_000_000) return `${sign}${unit}${+(v / 1_000_000).toFixed(v >= 10_000_000 ? 0 : 1)}M`;
  if (v >= 1_000) return `${sign}${unit}${+(v / 1_000).toFixed(v >= 10_000 ? 0 : 1)}k`;
  return `${sign}${unit}${Number.isInteger(v) ? v : v.toFixed(2)}`;
}

/** Ticks on round numbers, so nobody is asked to interpolate 3.7k. */
function niceTicks(max: number): number[] {
  if (max <= 0) return [0];
  const raw = max / 4;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? mag * 10;
  const out: number[] = [];
  /* Runs PAST the peak, not up to it.
     The loop used to stop at the last tick at or below `max`, so a peak of
     119,167 against a 50,000 step gave a top gridline of 100,000, and the line
     drew above the plot and was clipped by the top of the chart. The tallest
     value has to fit inside the scale or the scale is lying about it. */
  for (let v = 0; v < max; v += step) out.push(v);
  out.push(out.length ? out[out.length - 1] + step : step);
  return out;
}

export default function ReportChart({
  columns, rows, format, title,
}: {
  columns: ChartCol[];
  rows: Record<string, any>[];
  format: (n: number) => string;
  title?: string;
}) {
  const measures = useMemo(() => columns.filter(isMeasure), [columns]);
  const labels = useMemo(() => columns.filter((c) => !isMeasure(c)), [columns]);
  const labelCol = useMemo(
    () => columns.find(isDate) ?? labels[0] ?? columns[0],
    [columns, labels],
  );

  const [measureKeys, setMeasureKeys] = useState<string[]>(
    () => measures.slice(0, 1).map((m) => m.key));
  const [agg, setAgg] = useState<Agg>("sum");
  // Read here rather than at module scope so the chart repaints when the theme
  // moves. A palette captured once would leave dark-mode charts wearing the
  // light hues until the page was reloaded.
  const palette = useChartPalette();
  const [breakdownKey, setBreakdownKey] = useState("");
  /* The zoom window: how many categories are on screen, and where it starts.
     Expressed over the category list rather than over pixels, because these are
     bands, not a continuous axis — zooming out has to mean "more of them", not
     "the same bars, smaller". */
  const [size, setSize] = useState(12);
  const [start, setStart] = useState(0);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [hover, setHover] = useState<{ i: number; x: number; y: number } | null>(null);
  const zoomRef = useRef<(factor: number, fraction: number) => void>(() => {});

  const box = useRef<HTMLDivElement>(null);
  const plot = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(760);
  useEffect(() => {
    if (!box.current) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(320, e.contentRect.width)));
    ro.observe(box.current);
    return () => ro.disconnect();
  }, []);

  /* Ctrl/⌘ + wheel zooms; a plain wheel is left alone deliberately.
     Swallowing the plain wheel over a chart is how a page stops scrolling for
     anyone whose pointer happens to be over it — the same fault that made these
     tables unscrollable, so the modifier is the price of not breaking the page.
     Registered non-passively because it calls preventDefault, which React's own
     onWheel cannot do reliably. */
  useEffect(() => {
    const el = plot.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const at = ((e.clientX - r.left) / Math.max(1, r.width));
      zoomRef.current(e.deltaY > 0 ? 1.25 : 0.8, at);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const chosen = measures.filter((m) => measureKeys.includes(m.key));
  const breakdown = labels.find((c) => c.key === breakdownKey && c.key !== labelCol?.key);
  const timeline = !!labelCol && isDate(labelCol);

  /* Rows to categories to series. A breakdown makes each distinct value its own
     series; otherwise each chosen measure is one. Deliberately exclusive: a
     grouped-and-broken-down chart is a table pretending to be a picture. */
  const model = useMemo(() => {
    if (!labelCol) return null;

    const order: string[] = [];
    const buckets = new Map<string, Record<string, number[]>>();
    for (const r of rows) {
      const cat = String(r[labelCol.key] ?? "—");
      if (!buckets.has(cat)) { buckets.set(cat, {}); order.push(cat); }
      const into = buckets.get(cat)!;
      if (breakdown) {
        const key = String(r[breakdown.key] ?? "—");
        (into[key] ??= []).push(chosen[0] ? Number(r[chosen[0].key]) || 0 : 1);
      } else if (chosen.length) {
        for (const m of chosen) (into[m.key] ??= []).push(Number(r[m.key]) || 0);
      } else {
        (into.count ??= []).push(1);
      }
    }

    let keys = breakdown
      ? [...new Set(rows.map((r) => String(r[breakdown.key] ?? "—")))]
      : chosen.length ? chosen.map((m) => m.key) : ["count"];

    let folded: string[] = [];
    if (keys.length > MAX_SERIES) {
      const weight = (k: string) =>
        [...buckets.values()].reduce((s, b) => s + aggregate(b[k] ?? [], agg), 0);
      const ranked = [...keys].sort((a, b) => weight(b) - weight(a));
      folded = ranked.slice(MAX_SERIES - 1);
      keys = [...ranked.slice(0, MAX_SERIES - 1), "Other"];
    }

    const labelFor = (k: string) =>
      k === "Other" ? "Other"
        : k === "count" ? "Rows"
        : breakdown ? k
        : measures.find((m) => m.key === k)?.header ?? k;

    let cats = order.map((cat) => {
      const b = buckets.get(cat)!;
      const values: Record<string, number> = {};
      for (const k of keys) {
        values[k] = k === "Other"
          ? aggregate(folded.flatMap((f) => b[f] ?? []), agg)
          : aggregate(b[k] ?? [], agg);
      }
      return { cat, values, weight: Object.values(values).reduce((s, v) => s + v, 0) };
    });

    /* A timeline reads oldest to newest, whatever order the rows arrived in.
       Daily totals come back newest-first because that is the useful order for a
       table, and drawing them in that order put last Monday to the right of this
       Monday: a line that slopes down while takings go up. */
    cats = timeline
      ? cats.sort((a, b) => String(a.cat).localeCompare(String(b.cat)))
      : cats.sort((a, b) => b.weight - a.weight);

    return {
      // Every category, in the order it should be read. The window below decides
      // which are drawn, so zooming never re-sorts the data under the reader —
      // the same bar stays in the same place.
      cats,
      series: keys.map((k, i) => ({ key: k, label: labelFor(k), colour: palette.slots[i] })),
    };
  }, [rows, labelCol, chosen, breakdown, agg, timeline, measures, palette]);

  if (!labelCol || (!measures.length && agg !== "count")) {
    return (
      <p className="muted rc-none">
        This report has no numeric column, so there is nothing to plot. The table
        is the whole of it.
      </p>
    );
  }
  if (!model || !model.cats.length) {
    return <p className="muted rc-none">No rows matched, so there is nothing to plot.</p>;
  }

  /* Clamped on every render rather than at each interaction: a breakdown change
     or a new filter can shrink the list under a window that was valid a moment
     ago, and a window past the end draws an empty plot with no way back. */
  const totalCats = model.cats.length;
  const winSize = Math.max(2, Math.min(size, totalCats));
  const winStart = Math.max(0, Math.min(start, totalCats - winSize));
  const view = model.cats.slice(winStart, winStart + winSize);
  const zoomed = winSize < totalCats;

  /** Zoom around a category, so whatever the pointer is on stays under it. */
  const zoomTo = (nextSize: number, anchor = winStart + winSize / 2) => {
    const clamped = Math.max(2, Math.min(Math.round(nextSize), totalCats));
    const ratio = winSize ? (anchor - winStart) / winSize : 0.5;
    setSize(clamped);
    setStart(Math.max(0, Math.min(Math.round(anchor - ratio * clamped), totalCats - clamped)));
  };

  // The wheel listener is bound once; this keeps it pointed at the current
  // window without rebinding on every render.
  zoomRef.current = (factor: number, fraction: number) =>
    zoomTo(winSize * factor, winStart + fraction * winSize);

  const live = model.series.filter((s) => !hidden.has(s.key));
  const peak = Math.max(...view.flatMap((c) => live.map((s) => c.values[s.key] ?? 0)), 0);
  const ticks = niceTicks(peak);
  const top = ticks[ticks.length - 1] || 1;

  // padL shrinks with the label: abbreviated ticks no longer need 78px.
  const H = 300, padL = 56, padR = 16, padT = 14, padB = 8;
  const plotW = Math.max(80, width - padL - padR);
  const plotH = H - padT - padB;
  const band = plotW / view.length;
  const y = (v: number) => padT + plotH - (v / top) * plotH;

  const single = live.length === 1;
  // Whether the axis wears a currency mark, taken from the columns being drawn.
  const moneyish = (chosen.length ? chosen : measures).some((m) => m.kind === "money");
  /* Over every category, not over the window.
     Zoom changes what is drawn; it must not change what the report is worth. A
     headline that moves when somebody scrolls the plot is a headline that will
     eventually disagree with the table beside it, and the table is right. */
  const allValues = model.cats.flatMap((c) => live.map((s) => c.values[s.key] ?? 0));
  const total = allValues.reduce((s, v) => s + v, 0);

  return (
    <div className="rc" ref={box}>
      <div className="rc-controls">
        {measures.length > 0 && !breakdown && (
          <label className="rc-ctl">
            <span>Measure</span>
            <Select
              value={measureKeys[0] ?? ""}
              onChange={(v) => setMeasureKeys([v])}
              options={measures.map((m) => ({ value: m.key, label: m.header }))}
            />
          </label>
        )}
        {measures.length > 1 && !breakdown && (
          <button
            type="button" className="ghost small"
            disabled={measureKeys.length >= Math.min(measures.length, MAX_SERIES)}
            onClick={() => {
              const next = measures.find((m) => !measureKeys.includes(m.key));
              if (next) setMeasureKeys([...measureKeys, next.key]);
            }}
          >
            + Compare another
          </button>
        )}
        <label className="rc-ctl">
          <span>Aggregate</span>
          <Select value={agg} onChange={(v) => setAgg(v as Agg)} options={AGGS} />
        </label>
        {labels.length > 1 && (
          <label className="rc-ctl">
            <span>Break down by</span>
            <Select
              value={breakdownKey}
              onChange={(v) => { setBreakdownKey(v); if (v) setMeasureKeys(measureKeys.slice(0, 1)); }}
              placeholder="Nothing" clearable
              options={labels.filter((c) => c.key !== labelCol.key)
                .map((c) => ({ value: c.key, label: c.header }))}
            />
          </label>
        )}
        {/* Zoom as buttons as well as a gesture. Ctrl-wheel is the gesture
            people expect, but a chart whose only zoom is a modifier-wheel is a
            chart most people never discover is zoomable. */}
        <div className="rc-ctl rc-zoom">
          <span>Zoom</span>
          <div className="rc-zoom-row">
            <button type="button" className="ghost small" aria-label="Show fewer, larger"
                    disabled={winSize <= 2} onClick={() => zoomTo(winSize / 1.6)}>+</button>
            <button type="button" className="ghost small" aria-label="Show more, smaller"
                    disabled={!zoomed} onClick={() => zoomTo(winSize * 1.6)}>−</button>
            <button type="button" className="ghost small" disabled={!zoomed}
                    onClick={() => { setSize(totalCats); setStart(0); }}>Fit all</button>
            <span className="rc-zoom-state muted">
              {winStart + 1}–{winStart + view.length} of {totalCats.toLocaleString()}
            </span>
          </div>
        </div>
      </div>

      <div className="rc-summary">
        <span><b>{format(total)}</b> total</span>
        <span><b>{format(allValues.length ? total / allValues.length : 0)}</b> average</span>
        <span><b>{format(allValues.length ? Math.max(...allValues) : 0)}</b> highest</span>
        <span className="muted">
          over all {totalCats.toLocaleString()} {timeline ? "periods" : "groups"}
          {zoomed && <> · showing {view.length}</>}
        </span>
      </div>

      <div
        className={`rc-plot${zoomed ? " is-zoomed" : ""}`}
        ref={plot}
        onPointerLeave={() => setHover(null)}
        onPointerDown={(e) => {
          // Drag to pan, but only when there is something off-screen to pan to.
          if (!zoomed || e.button !== 0) return;
          const from = e.clientX, at = winStart;
          const el = e.currentTarget;
          el.setPointerCapture(e.pointerId);
          const move = (ev: PointerEvent) => {
            const perBand = Math.max(1, plotW / view.length);
            setStart(at - Math.round((ev.clientX - from) / perBand));
          };
          const up = () => {
            el.removeEventListener("pointermove", move);
            el.removeEventListener("pointerup", up);
          };
          el.addEventListener("pointermove", move);
          el.addEventListener("pointerup", up);
        }}
      >
        <svg width="100%" height={H} role="img"
             aria-label={title ? `${title}, charted` : "Report chart"}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={padL} x2={padL + plotW} y1={y(t)} y2={y(t)} stroke={palette.grid} strokeWidth="1" />
              <text x={padL - 10} y={y(t) + 4} className="rc-axis" textAnchor="end">
                {tickLabel(t, moneyish)}
              </text>
            </g>
          ))}

          {timeline
            ? live.map((s) => {
                const pts = view.map((c, i) =>
                  [padL + band * i + band / 2, y(c.values[s.key] ?? 0)] as const);
                const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0]},${p[1]}`).join(" ");
                const end = pts[pts.length - 1];
                return (
                  <g key={s.key}>
                    <path d={d} fill="none" stroke={single ? palette.one : s.colour}
                          strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
                    {/* End marker only: a dot on every point is noise. */}
                    <circle cx={end[0]} cy={end[1]} r="4.5"
                            fill={single ? palette.one : s.colour}
                            stroke="var(--surface)" strokeWidth="2" />
                  </g>
                );
              })
            : view.map((c, i) => {
                // Capped at 24px, 2px gap between neighbours, rounded data-end.
                const groupW = Math.min(band - 8, 24 * live.length + 2 * (live.length - 1));
                const barW = Math.max(3, (groupW - 2 * (live.length - 1)) / live.length);
                const x0 = padL + band * i + (band - groupW) / 2;
                return live.map((s, j) => {
                  const v = c.values[s.key] ?? 0;
                  return (
                    <rect
                      key={s.key} x={x0 + j * (barW + 2)} y={y(v)}
                      width={barW} height={Math.max(0, y(0) - y(v))}
                      rx={Math.min(4, barW / 2)}
                      fill={single ? palette.one : s.colour}
                      opacity={hover && hover.i !== i ? 0.5 : 1}
                    />
                  );
                });
              })}

          {/* Hit target is the whole band. Nobody aims at a 2px line. */}
          {view.map((c, i) => (
            <rect
              key={`hit-${c.cat}-${i}`} x={padL + band * i} y={padT}
              width={band} height={plotH} fill="transparent"
              onPointerMove={(e) => {
                const svg = e.currentTarget.ownerSVGElement as SVGSVGElement;
                const r = svg.getBoundingClientRect();
                setHover({ i, x: e.clientX - r.left, y: e.clientY - r.top });
              }}
            />
          ))}

          {hover && (
            <line
              x1={padL + band * hover.i + band / 2} x2={padL + band * hover.i + band / 2}
              y1={padT} y2={padT + plotH} stroke={palette.grid} strokeWidth="1"
            />
          )}
        </svg>

        {/* X labels as real text, so they can be clipped and hovered like any
            other truncated value, but only while there is room for them.
            Zoomed out to 325 groups every label was rendered at three pixels
            wide, which is not a small label: it is a grey smear that overflowed
            the card and told the reader nothing. Below the legible width the
            axis stands down and the hover carries the name instead, which is
            what the hover is for. */}
        {band >= 34 ? (
          <div className="rc-xaxis" style={{ paddingLeft: padL, paddingRight: padR }}>
            {view.map((c, i) => (
              <span key={`${c.cat}-${i}`} style={{ width: band }}>{c.cat}</span>
            ))}
          </div>
        ) : (
          <div className="rc-xaxis is-dense" style={{ paddingLeft: padL, paddingRight: padR }}>
            <span>{view[0]?.cat}</span>
            <span className="muted">
              {view.length.toLocaleString()} {timeline ? "periods" : "groups"}, hover for names
            </span>
            <span>{view[view.length - 1]?.cat}</span>
          </div>
        )}

        {hover && (
          <div className="rc-tip"
               style={{ left: Math.min(Math.max(hover.x, 96), width - 96), top: Math.max(6, hover.y - 14) }}>
            <div className="rc-tip-cat">{view[hover.i].cat}</div>
            {live.map((s) => (
              <div key={s.key} className="rc-tip-row">
                <i style={{ background: single ? palette.one : s.colour }} />
                <b>{format(view[hover.i].values[s.key] ?? 0)}</b>
                <span>{s.label}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* A legend wherever identity is carried by colour, and it toggles — the
          quickest way to answer "what is that one doing". */}
      {model.series.length >= 2 && (
        <div className="rc-legend">
          {model.series.map((s) => (
            <button
              key={s.key} type="button"
              className={`rc-key${hidden.has(s.key) ? " is-off" : ""}`}
              onClick={() => setHidden((h) => {
                const next = new Set(h);
                if (next.has(s.key)) next.delete(s.key); else next.add(s.key);
                // Never hide the last one: an empty plot is not a filter.
                return next.size >= model.series.length ? h : next;
              })}
            >
              <i style={{ background: s.colour }} />
              {s.label}
            </button>
          ))}
        </div>
      )}

      {zoomed && (
        <>
          {/* An overview strip, so the window is legible rather than implied.
              Zoomed into 12 of 433 rows, "where am I" is a fair question and the
              plot alone cannot answer it. Dragging it pans. */}
          <div
            className="rc-overview"
            role="slider"
            aria-label="Visible range"
            aria-valuemin={1}
            aria-valuemax={totalCats}
            aria-valuenow={winStart + 1}
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "ArrowLeft") { e.preventDefault(); setStart(winStart - 1); }
              if (e.key === "ArrowRight") { e.preventDefault(); setStart(winStart + 1); }
            }}
            onPointerDown={(e) => {
              const strip = e.currentTarget;
              strip.setPointerCapture(e.pointerId);
              const move = (ev: React.PointerEvent | PointerEvent) => {
                const r = strip.getBoundingClientRect();
                const at = ((ev as PointerEvent).clientX - r.left) / r.width;
                setStart(Math.round(at * totalCats - winSize / 2));
              };
              move(e);
              const up = () => {
                strip.removeEventListener("pointermove", move as any);
                strip.removeEventListener("pointerup", up);
              };
              strip.addEventListener("pointermove", move as any);
              strip.addEventListener("pointerup", up);
            }}
          >
            <div
              className="rc-overview-window"
              style={{
                left: `${(winStart / totalCats) * 100}%`,
                width: `${(view.length / totalCats) * 100}%`,
              }}
            />
          </div>
          <p className="muted rc-note">
            Showing {view.length} of {totalCats.toLocaleString()}{" "}
            {timeline ? "periods" : "groups"}. Drag the strip to move, or hold Ctrl
            and scroll on the chart. The table has every one.
          </p>
        </>
      )}
    </div>
  );
}
