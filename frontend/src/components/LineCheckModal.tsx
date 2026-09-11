/** Everything the checks know about one line of a script.
 *
 *  Opened from the shield on the row, once that line has been checked. The row
 *  says whether there is anything to say; this says what it is.
 *
 *  Three deterministic answers and one opinion, kept apart on purpose:
 *
 *    Dose          the directions as written, against the maximum held here
 *    Interactions  this line against the other lines, and against what the
 *                  patient has had in the last six months
 *    Scheme        whether the patient's cover carries it
 *
 *    Second opinion  the AI read of the whole script, which sees allergies and
 *                    chronic conditions and is advisory. It is a press, not a
 *                    gate, and it says so.
 *
 *  A clear answer is worded as what was checked, never as "safe". The pairs
 *  table is finite and a pharmacist who learns that a green shield means safe
 *  has been taught something false by the software.
 */
import { CircleNotch, PencilSimple, ShieldCheck, Warning } from "@phosphor-icons/react";
import type { CoverageLine } from "../types";
import type { DoseFinding, Finding, Screen } from "./InteractionPanel";
import type { useAiStream } from "../hooks/useAiStream";
import AiOutput from "./AiOutput";
import AiPhase from "./AiPhase";
import ClaudeIcon from "./ClaudeIcon";

/** What a screen says about one line, matched on the exact label the server
 *  builds — `"{name} {strength}"` — because two products whose names share a
 *  long prefix must never swap findings. */
export function findingsFor(screen: Screen | null | undefined, name: string) {
  const dose: DoseFinding | null =
    screen?.doses?.found.find((f) => f.product === name) ?? null;
  const interactions: Finding[] =
    (screen?.found ?? []).filter((f) => f.between.includes(name));
  const judged = !!dose && dose.severity !== "unknown";
  const notHeld = !!screen && (
    (screen.doses?.not_covered ?? []).includes(name) || dose?.severity === "unknown");
  const major = (judged && dose!.severity === "major")
    || interactions.some((f) => f.severity === "major");
  return { dose: judged ? dose : null, unjudged: dose && !judged ? dose : null,
           interactions, notHeld, major, any: judged || interactions.length > 0 };
}

const COVER_LABEL: Record<string, string> = {
  covered: "on benefit",
  reference: "reference priced",
  authorisation: "authorisation required",
  excluded: "not on benefit",
};

export default function LineCheckModal({
  name, schedule, loading, screen, error, coverage, otherLines, hasPatient,
  ai, aiShown, onAskAi, onRecheck, onEdit, onClose,
}: {
  name: string;
  schedule: number;
  loading: boolean;
  screen: Screen | null;
  error?: string;
  coverage: CoverageLine | null;
  otherLines: number;
  hasPatient: boolean;
  ai: ReturnType<typeof useAiStream>;
  aiShown: string;
  onAskAi: () => void;
  onRecheck: () => void;
  onEdit: () => void;
  onClose: () => void;
}) {
  const f = findingsFor(screen, name);
  // Three answers at a glance, on an even grid; the detail follows below.
  const doseCard = f.dose
    ? (f.dose.severity === "major"
      ? { tone: "major", text: "Over the maximum" }
      : { tone: "minor", text: "Directions unreadable" })
    : f.notHeld ? { tone: "none", text: "Not judged" } : { tone: "ok", text: "Within the maximum" };
  const ixCard = f.interactions.length === 0
    ? { tone: "ok", text: "None found" }
    : { tone: f.interactions.some((x) => x.severity === "major") ? "major" : "minor",
        text: `${f.interactions.length} found` };
  const coverCard = !coverage || coverage.status === "unknown"
    ? { tone: "none", text: "Not checked" }
    : coverage.status === "covered" ? { tone: "ok", text: "On benefit" }
    : coverage.status === "excluded" ? { tone: "major", text: "Not on benefit" }
    : { tone: "minor", text: COVER_LABEL[coverage.status] ?? coverage.status };

  const summary = loading ? "checking…"
    : error ? "the check could not run"
    : f.major ? "a major finding"
    : f.any ? "something to look at"
    : "nothing found";

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true"
         aria-label={`Check: ${name}`}
         onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal disp-check">
        <h2>
          {name}
          <span className={`badge ${schedule >= 5 ? "danger" : "muted"}`}>S{schedule}</span>
          <span className="disp-entry-of">{summary}</span>
        </h2>

        {loading ? (
          <p className="chk-none"><CircleNotch size={16} className="spin" /> Checking this line…</p>
        ) : error ? (
          <div className="alert error">{error}</div>
        ) : (
          <>
            <div className="chk-summary">
              <div className={`chk-card is-${doseCard.tone}`}><span>Dose</span><b>{doseCard.text}</b></div>
              <div className={`chk-card is-${ixCard.tone}`}><span>Interactions</span><b>{ixCard.text}</b></div>
              <div className={`chk-card is-${coverCard.tone}`}><span>Scheme</span><b>{coverCard.text}</b></div>
            </div>
            <section className="chk-sec">
              <h4>Dose</h4>
              {f.dose ? (
                <div className={`chk-row is-${f.dose.severity === "major" ? "major" : "minor"}`}>
                  <Warning size={16} weight="fill" />
                  <div>
                    <b>{f.dose.severity === "major"
                      ? "Over the maximum held here"
                      : "The directions could not be read"}</b>
                    <p>{f.dose.detail}</p>
                    <p className="chk-action">{f.dose.action}</p>
                  </div>
                </div>
              ) : f.notHeld ? (
                <p className="chk-none">
                  {f.unjudged?.detail
                    ?? "No maximum is held here for this medicine, so the dose was not judged."}
                </p>
              ) : (
                <p className="chk-ok">
                  <ShieldCheck size={16} weight="fill" />
                  Within the maximum held here, for the directions as written.
                </p>
              )}
            </section>

            <section className="chk-sec">
              <h4>
                Interactions
                <span className="chk-scope">
                  {" "}with {otherLines === 0 ? "no other line"
                    : `the other ${otherLines} line${otherLines === 1 ? "" : "s"}`}
                  {hasPatient ? " and the last six months of this patient" : ""}
                </span>
              </h4>
              {f.interactions.length > 0 ? f.interactions.map((x, i) => {
                const other = x.between.find((b) => b !== name) ?? x.between[1];
                const tone = x.severity === "major" ? "major"
                  : x.severity === "moderate" ? "minor" : "info";
                return (
                  <div key={i} className={`chk-row is-${tone}`}>
                    <Warning size={16} weight="fill" />
                    <div>
                      <b>{other}</b>
                      <span className={`badge ${tone === "major" ? "danger" : "muted"}`}>
                        {x.severity}
                      </span>
                      {x.with_history && <span className="badge muted">already taking</span>}
                      <p>{x.effect}</p>
                      <p className="chk-action">{x.action}</p>
                      {x.context && <p className="chk-coverage">{x.context}</p>}
                    </div>
                  </div>
                );
              }) : (
                <p className="chk-ok">
                  <ShieldCheck size={16} weight="fill" />
                  None found among the pairs held here.
                </p>
              )}
              {screen?.coverage && <p className="chk-coverage">{screen.coverage}</p>}
            </section>

            {coverage && coverage.status !== "unknown" && (
              <section className="chk-sec">
                <h4>Scheme</h4>
                <p className="chk-none">
                  <span className={`badge ${coverage.status === "covered" ? "ok"
                    : coverage.status === "excluded" ? "danger" : "warn"}`}>
                    {COVER_LABEL[coverage.status] ?? coverage.status}
                  </span>{" "}
                  {coverage.reason}
                </p>
              </section>
            )}

            <section className="chk-sec">
              <h4>Second opinion</h4>
              <p className="chk-coverage">
                Reads the whole script against this patient's history, allergies and
                chronic conditions. Advisory — it does not hold the dispense.
              </p>
              {(ai.streaming || ai.text) && (
                <div className="ai-block">
                  <AiPhase phase={ai.phase} />
                  {ai.error && <div className="alert error">{ai.error}</div>}
                  {ai.streaming
                    ? aiShown && <p className="ai-live ai-caret">{aiShown}</p>
                    : <AiOutput text={ai.text} title="Interaction check" />}
                </div>
              )}
              <button type="button" className="btn secondary small"
                      disabled={!ai.streaming && !hasPatient}
                      title={hasPatient ? undefined : "Find the patient first"}
                      onClick={onAskAi}>
                {ai.streaming ? "Stop" : <><ClaudeIcon size={14} /> Ask for a second opinion</>}
              </button>
            </section>
          </>
        )}

        <div className="disp-edit-actions">
          <button type="button" className="btn secondary" onClick={onRecheck}
                  disabled={loading}>
            Check again
          </button>
          <button type="button" className="btn secondary" onClick={onEdit}>
            <PencilSimple size={14} /> Edit this line
          </button>
          <span className="finish-spacer" />
          <button type="button" className="btn primary" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  );
}
