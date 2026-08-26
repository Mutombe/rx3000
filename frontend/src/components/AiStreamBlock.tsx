/** An AI answer that appears as it is written, wherever one is asked for.
 *
 *  Six screens each held their own `aiBusy` flag, their own try/catch, and their
 *  own "Thinking…" label, and every one of them blocked until the whole answer
 *  arrived. Twelve seconds of an unchanged screen reads as a system that has
 *  hung; the pharmacist reaches for the back button at about second five. The
 *  same twelve seconds spent watching a sentence form reads as thinking.
 *
 *  What this holds is the shape all six shared: a button that starts it, a phase
 *  line saying what is happening before there is anything to show, the text as it
 *  streams, and the finished answer handed to `AiOutput` so it can be copied,
 *  printed or exported like any other. The finished text goes to `onDone` for the
 *  screens that keep it.
 */
import { useEffect, useRef } from "react";
import AiOutput from "./AiOutput";
import AiPhase from "./AiPhase";
import ClaudeIcon from "./ClaudeIcon";
import { useAiStream } from "../hooks/useAiStream";
import { useTypewriter } from "../hooks/useTypewriter";

export default function AiStreamBlock({
  path, body, label, title, context, empty, onDone, onText,
}: {
  /** The streaming endpoint. */
  path: string;
  /** Its POST body, or undefined for a path-parameter endpoint. */
  body?: unknown;
  /** The verb on the button: "Draft reply", "Generate summary". */
  label: string;
  /** What the finished answer is called, for the export header. */
  title: string;
  context?: string;
  /** Shown before anything has been asked for. */
  empty?: string;
  /** The finished text, once. */
  onDone?: (text: string) => void;
  /** Every update, for a screen that mirrors it into a field as it arrives. */
  onText?: (text: string) => void;
}) {
  const { run, stop, text, phase, error, streaming } = useAiStream();
  const shown = useTypewriter(text, streaming);
  const delivered = useRef(false);

  useEffect(() => { onText?.(shown); }, [shown]);

  useEffect(() => {
    // Once, when the stream ends with something in it. Without the guard a
    // re-render after completion hands the same answer over again, and a screen
    // that appends drafts would collect three copies of one reply.
    if (streaming) { delivered.current = false; return; }
    if (!delivered.current && text.trim()) {
      delivered.current = true;
      onDone?.(text);
    }
  }, [streaming, text]);

  return (
    <div className="ai-block">
      {error && <div className="alert error">{error}</div>}

      {!text && !streaming && empty && <p className="muted">{empty}</p>}

      {(streaming || text) && (
        <>
          <AiPhase phase={phase} />
          {/* While it is being written it is plain text with a caret: running
              Markdown over a half-finished document makes headings and lists
              flicker in and out as the syntax completes. The finished answer
              goes to AiOutput, which renders it properly. */}
          {streaming
            ? shown && <p className={`ai-live${streaming ? " ai-caret" : ""}`}>{shown}</p>
            : text && <AiOutput text={text} title={title} context={context} />}
        </>
      )}

      <div className="ai-block-actions">
        {streaming ? (
          <button type="button" className="secondary" onClick={stop}>Stop</button>
        ) : (
          <button type="button" className="secondary" onClick={() => run(path, body)}>
            <ClaudeIcon size={14} /> {text ? "Again" : label}
          </button>
        )}
      </div>
    </div>
  );
}
