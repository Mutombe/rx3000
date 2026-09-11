/** Whether this member has cover, and whether their scheme is paying us.
 *
 *  Shown at the two moments it can change a decision: dispensing, and taking
 *  the money. Both, because they are often different people — the pharmacist
 *  hands the medicine over and the cashier finds out later what it was worth.
 *
 *  Two facts, kept apart on purpose:
 *
 *    **Benefit left** is the member's business and only the funder knows it.
 *    Until the switch is connected this says so rather than showing nothing,
 *    because a blank space where a balance would be reads as "covered" and an
 *    exhausted member turned into a surprise cash sale at the till is the exact
 *    failure this exists to prevent.
 *
 *    **Whether the scheme pays** is our business and we can answer it out of
 *    our own claims. A funder holding eleven thousand dollars of medicine it
 *    has not settled is not a discovery for the year end; it is a decision to
 *    make at the counter, one script at a time.
 *
 *  Advisory, never blocking. A slow funder is a commercial dispute and the
 *  person at the counter cannot resolve it, so this makes sure they know what
 *  they are handing over, and leaves the choice with them.
 */
import { useEffect, useState } from "react";
import { Info, ShieldCheck, ShieldWarning, Warning } from "@phosphor-icons/react";
import { api, money } from "../api";

export interface Standing {
  patient_id: number;
  has_cover: boolean;
  member_number?: string;
  claims?: number;
  claimed?: number;
  settled?: number;
  outstanding?: number;
  rejected?: number;
  verdict: "paying" | "lagging" | "watch" | "cash" | "unknown";
  why: string;
  scheme: null | {
    scheme: string; scheme_code: string; settles_in: string;
    claimed: number; settled: number; outstanding: number;
    recovery: number | null; overdue_claims: number; overdue_value: number;
    oldest_overdue_days: number; late_after_days: number;
    verdict: string; why: string;
  };
  benefit: { known: boolean; available: number | null; note?: string };
}

const TONE: Record<string, { cls: string; label: string }> = {
  paying: { cls: "ok", label: "Settling normally" },
  lagging: { cls: "warn", label: "Behind on payment" },
  watch: { cls: "warn", label: "Worth checking" },
  cash: { cls: "muted", label: "Cash patient" },
  unknown: { cls: "muted", label: "Nothing claimed yet" },
};

export default function InsuranceStanding({ patientId, compact = false, variant = "block", onOpen, skeleton = false }: {
  /** "chip": the scheme and its standing on one line, for a lane. */
  variant?: "block" | "chip" | "icon";
  onOpen?: () => void;
  /** Show the card's shape while it loads. */
  skeleton?: boolean;
  patientId: number | null;
  /** The till has less room than the dispensary, and needs the verdict more
   *  than the workings. */
  compact?: boolean;
}) {
  const [data, setData] = useState<Standing | null>(null);

  useEffect(() => {
    if (!patientId) { setData(null); return; }
    let live = true;
    api.get<Standing>(`/api/patients/${patientId}/insurance`)
      .then((d) => { if (live) setData(d); })
      // A standing that cannot be read must not stop anybody dispensing. The
      // panel simply does not appear.
      .catch(() => { if (live) setData(null); });
    return () => { live = false; };
  }, [patientId]);

  // An icon for a toolbar, in the same place whether or not there is cover.
  if (variant === "icon") {
    const covered = !!data?.has_cover;
    const tone = covered ? (TONE[data!.verdict] ?? TONE.unknown) : null;
    const Icon = covered && data!.verdict !== "paying" && data!.verdict !== "unknown"
      ? ShieldWarning : ShieldCheck;
    const label = !data ? "Checking the medical aid\u2026"
      : covered
        ? `${data.scheme?.scheme ?? "Medical aid"} \u00b7 ${tone!.label}`
          + (data.benefit.known ? "" : " \u00b7 balance unknown")
        : "Private patient: no medical aid on file";
    return (
      <button type="button"
              className={`lane-tool is-aid${tone ? ` is-${tone.cls}` : ""}`}
              disabled={!covered} onClick={onOpen} title={label} aria-label={label}>
        <Icon size={15} weight={covered ? "fill" : "regular"} />
      </button>
    );
  }

  if (!data) {
    return skeleton ? (
      <div className="ins" aria-busy="true" aria-label="Loading the medical aid">
        <div className="ins-head">
          <span className="skel skel-icon" />
          <span className="skel" style={{ width: 150 }} />
          <span className="skel" style={{ width: 90 }} />
        </div>
        <span className="skel skel-line" style={{ width: "85%" }} />
        <div className="ins-figures">
          {[0, 1, 2, 3].map((i) => (
            <div key={i}>
              <span className="skel skel-line" style={{ width: "75%" }} />
              <b><span className="skel" style={{ width: "45%" }} /></b>
            </div>
          ))}
        </div>
      </div>
    ) : null;
  }

  // A cash patient has no insurance to reconcile, and saying so in a panel
  // would be noise on the majority of sales.
  if (!data.has_cover) return null;

  const tone = TONE[data.verdict] ?? TONE.unknown;
  const Glyph = data.verdict === "paying" ? ShieldCheck
    : data.verdict === "cash" || data.verdict === "unknown" ? Info : ShieldWarning;

  if (variant === "chip") {
    return (
      <button type="button" className={`ctx-chip ins-chip ins-${tone.cls}`}
              onClick={onOpen} title={data.why}>
        <Glyph size={13} weight="fill" />
        {data.scheme?.scheme ?? "Medical aid"} · {tone.label}
        {!data.benefit.known && <span className="ctx-chip-sub">&nbsp;· balance unknown</span>}
      </button>
    );
  }

  return (
    <div className={`ins ins-${tone.cls}`}>
      <div className="ins-head">
        <Glyph size={16} weight="fill" />
        <b>{data.scheme?.scheme ?? "Medical aid"}</b>
        {data.member_number && (
          <span className="mono muted small">{data.member_number}</span>
        )}
        <span className={`badge ${tone.cls}`}>{tone.label}</span>
      </div>

      <p className="ins-why">{data.why}</p>

      {!compact && data.scheme && (
        <div className="ins-figures">
          <div>
            <span>This member owes the scheme</span>
            <b>{money(data.outstanding ?? 0)}</b>
          </div>
          <div>
            <span>Scheme owes the pharmacy</span>
            <b>{money(data.scheme.outstanding)}</b>
          </div>
          <div>
            <span>Settled</span>
            <b>
              {data.scheme.recovery === null
                ? "—"
                : `${Math.round(data.scheme.recovery * 100)}%`}
            </b>
          </div>
          {data.scheme.settles_in && (
            <div>
              <span>Settles in</span>
              <b>{data.scheme.settles_in}</b>
            </div>
          )}
        </div>
      )}

      {/* Said out loud rather than left as an empty space. */}
      {!data.benefit.known && (
        <p className="ins-benefit">
          <Warning size={13} weight="fill" />
          <span>
            {compact
              ? "Benefit balance not known — the scheme is not connected."
              : data.benefit.note}
          </span>
        </p>
      )}
    </div>
  );
}
