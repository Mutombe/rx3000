import ClaudeIcon from "./ClaudeIcon";

/** What the assistant is doing, while it is doing it.
 *
 *  A spinner says "wait". This says what is being waited for, which is the
 *  difference between a pause that feels broken and one that feels considered.
 *  The shimmer runs along the label rather than around a circle because the
 *  thing being waited for is a sentence, not a page.
 */
export type Phase =
  | { kind: "idle" }
  | { kind: "thinking" }
  | { kind: "reading"; what: string }
  | { kind: "writing" };

export default function AiPhase({ phase }: { phase: Phase }) {
  if (phase.kind === "idle") return null;
  // "Writing" needs no label: the text arriving is the indicator.
  if (phase.kind === "writing") return null;

  const label = phase.kind === "thinking" ? "Thinking…" : `Reading ${phase.what}…`;
  return (
    <div className="ai-phase" role="status" aria-live="polite">
      <ClaudeIcon size={13} className="ai-phase-mark" />
      <span className="ai-shimmer">{label}</span>
    </div>
  );
}
