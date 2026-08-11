import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";

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
  const [history, setHistory] = useState<Exchange[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ enabled: boolean; model: string } | null>(null);

  useEffect(() => {
    api.get<{ enabled: boolean; model: string }>("/api/ai/status").then(setStatus);
  }, []);

  async function ask(e?: FormEvent, preset?: string) {
    e?.preventDefault();
    const q = preset ?? question;
    if (!q.trim()) return;
    setBusy(true);
    setQuestion("");
    try {
      const res = await api.post<{ text: string }>("/api/ai/ask", { question: q });
      setHistory((h) => [{ question: q, answer: res.text }, ...h]);
    } catch (err: any) {
      setHistory((h) => [{ question: q, answer: `Error: ${err.message}` }, ...h]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Pulse AI</h1>
          <div className="sub">
            Ask questions about your pharmacy's live data — powered by Claude
            {status && !status.enabled && " (currently disabled: add ANTHROPIC_API_KEY to backend/.env)"}
          </div>
        </div>
      </div>

      <div className="card">
        <form onSubmit={ask} style={{ display: "flex", gap: 10 }}>
          <input
            placeholder="e.g. Which lines are running low that sold well this week?"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
          <button disabled={busy} style={{ whiteSpace: "nowrap" }}>{busy ? "Thinking…" : "Ask ✦"}</button>
        </form>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
          {SUGGESTIONS.map((s) => (
            <button key={s} className="secondary small" onClick={() => ask(undefined, s)} disabled={busy}>{s}</button>
          ))}
        </div>
      </div>

      {history.map((h, i) => (
        <div className="card" key={i}>
          <h3>“{h.question}”</h3>
          <div className="ai-box">{h.answer}</div>
        </div>
      ))}
      {history.length === 0 && (
        <div className="card"><div className="empty">Ask anything about sales, stock, scripts or patients — answers are grounded in your live database.</div></div>
      )}
    </>
  );
}
