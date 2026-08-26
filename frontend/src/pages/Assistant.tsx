import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import AiOutput from "../components/AiOutput";
import { ClockCounterClockwise } from "@phosphor-icons/react";
import AiHistory from "../components/AiHistory";
import ClaudeIcon from "../components/ClaudeIcon";
import AiPhase from "../components/AiPhase";
import { useAiStream } from "../hooks/useAiStream";
import { useTypewriter } from "../hooks/useTypewriter";

interface Exchange {
  question: string;
  answer: string;
}

const SUGGESTIONS = [
  "How are sales this month compared to what you can see?",
  "What are our top sellers this week?",
  "Which products should we reorder urgently?",
  "How many scripts did we dispense in the last 7 days?",
];

export default function Assistant() {
  const [question, setQuestion] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  /* Bumped when an answer has been saved, so the drawer refetches rather than
     showing a list that is one question out of date the moment you open it. */
  const [logVersion, setLogVersion] = useState(0);
  const [history, setHistory] = useState<Exchange[]>([]);
  /* The answer arrives as it is written rather than all at once.
     Twelve seconds of blank screen reads as a system that has hung, and the
     pharmacist reaches for the back button at about second five. The same
     twelve seconds spent watching a sentence form reads as thinking. */
  const { ask: stream, stop, text: live, phase, error: streamError, streaming } = useAiStream();
  const shown = useTypewriter(live, streaming);
  const busy = streaming;
  const [status, setStatus] = useState<{ enabled: boolean; model: string } | null>(null);

  useEffect(() => {
    api.get<{ enabled: boolean; model: string }>("/api/ai/status").then(setStatus);
  }, []);

  const [asking, setAsking] = useState("");

  async function ask(e?: FormEvent, preset?: string) {
    e?.preventDefault();
    const q = preset ?? question;
    if (!q.trim()) return;
    setQuestion("");
    setAsking(q);
    await stream(q);
  }

  // The finished answer moves into the history, so the live pane only ever
  // holds the one being written.
  useEffect(() => {
    if (!streaming && asking && live) {
      setHistory((h) => [{ question: asking, answer: live }, ...h]);
      setAsking("");
      // The server has just written this one to the log.
      setLogVersion((n) => n + 1);
    }
  }, [streaming, asking, live]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Pulse AI</h1>
          <div className="sub">
            Ask questions about your pharmacy's live data, powered by Claude
            {status && !status.enabled && " (currently disabled: add ANTHROPIC_API_KEY to backend/.env)"}
          </div>
        </div>
        {/* Top right, where a history control is looked for. Every answer is
            kept, so a question worth twelve seconds of a model's time is not
            thrown away by a page refresh. */}
        <button className="btn secondary small" onClick={() => setHistoryOpen(true)}>
          <ClockCounterClockwise size={14} weight="bold" /> History
        </button>
      </div>

      <AiHistory
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        reloadKey={logVersion}
        onOpenEntry={(e) => setHistory((h) => (
          // Shown at the top, and never twice: reopening the same entry moves it
          // up rather than stacking a second copy of the same answer.
          [{ question: e.question, answer: e.answer },
           ...h.filter((x) => !(x.question === e.question && x.answer === e.answer))]
        ))}
      />

      <div className="card">
        <form onSubmit={ask} style={{ display: "flex", gap: 10 }}>
          <input
            placeholder="e.g. Which lines are running low that sold well this week?"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
          {busy ? (
            <button type="button" className="secondary" onClick={stop} style={{ whiteSpace: "nowrap" }}>
              Stop
            </button>
          ) : (
            <button style={{ whiteSpace: "nowrap" }}>
              <ClaudeIcon size={14} /> Ask
            </button>
          )}
        </form>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
          {SUGGESTIONS.map((s) => (
            <button key={s} className="secondary small" onClick={() => ask(undefined, s)} disabled={busy}>{s}</button>
          ))}
        </div>
      </div>

      {/* The answer being written, with what is happening above it. */}
      {(asking || busy) && (
        <div className="card">
          <h3>“{asking}”</h3>
          <AiPhase phase={phase} />
          {streamError && <div className="alert error">{streamError}</div>}
          {shown && (
            <p className={`ai-live${streaming ? " ai-caret" : ""}`}>{shown}</p>
          )}
        </div>
      )}

      {history.map((h, i) => (
        <div className="card" key={i}>
          <h3>“{h.question}”</h3>
          <AiOutput text={h.answer} title="Assistant answer" context={h.question} />
        </div>
      ))}
      {history.length === 0 && (
        <div className="card"><div className="empty">Ask anything about sales, stock, scripts or patients. Answers are grounded in your live database.</div></div>
      )}
    </>
  );
}
