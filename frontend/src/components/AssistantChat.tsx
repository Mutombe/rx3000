/** RX-Assistant, as a conversation. One component, three places.
 *
 *  The dock in the corner, the page under Insight and anywhere else that wants
 *  it are the same thing at different widths. Two implementations of a chat
 *  would drift within a fortnight, and the one nobody was looking at would be
 *  the one somebody used.
 *
 *  WHAT IT SHOWS WHILE IT WORKS.
 *
 *  Not a spinner. A spinner says "wait" and nothing else, and this can take a
 *  few seconds because it is looking things up. So every step says what it is:
 *  looking something up, drawing the steps, handing the question to the bigger
 *  model. Somebody who can see it working will wait; somebody watching a
 *  spinner decides it is broken.
 */
import { useEffect, useRef, useState } from "react";
import { ArrowUp, Stop, MagnifyingGlass, Path, TreeStructure, Brain, Globe }
  from "@phosphor-icons/react";

import { getToken } from "../api";
import Markdown from "./Markdown";
import AssistantRoute, { RouteStep } from "./AssistantRoute";
import AssistantDiagram from "./AssistantDiagram";

/** One thing that happened while the answer was being worked out. */
interface Step { name: string; say: string; done?: string }

interface Turn {
  question: string;
  text: string;
  steps: Step[];
  routes: { title: string; steps: RouteStep[] }[];
  diagrams: { title: string; mermaid: string }[];
  model?: string;
  error?: string;
  /** Still being answered. */
  live?: boolean;
}

const MARKS: Record<string, any> = {
  find_in_app: MagnifyingGlass,
  show_route: Path,
  show_diagram: TreeStructure,
  think_harder: Brain,
  web_search: Globe,
};

const OPENERS = [
  "Where do I see what has been dispensed today?",
  "How do I set a price on a script?",
  "What does PP10 mean?",
  "How do I put stock back after a return?",
];

export default function AssistantChat({ compact = false }: { compact?: boolean }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const foot = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    foot.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  useEffect(() => () => abort.current?.abort(), []);

  async function ask(asked: string) {
    const said = asked.trim();
    if (!said || busy) return;
    setQuestion("");
    setBusy(true);

    // The turn goes up before the first byte comes back, so the question is on
    // screen while it is being answered rather than appearing with the answer.
    setTurns((all) => [...all, {
      question: said, text: "", steps: [], routes: [], diagrams: [], live: true,
    }]);
    const patch = (fn: (t: Turn) => Turn) =>
      setTurns((all) => all.map((t, i) => (i === all.length - 1 ? fn(t) : t)));

    const control = new AbortController();
    abort.current = control;
    try {
      const res = await fetch("/api/ai/assistant/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
        },
        // The turns so far, so a second question can build on the first. Sent
        // rather than held on the server: the dock and the page are one
        // conversation only because the client says they are.
        body: JSON.stringify({
          question: said,
          history: turns.flatMap((t) => ([
            { role: "user", content: t.question },
            { role: "assistant", content: t.text || "(no answer)" },
          ])).slice(-8),
        }),
        signal: control.signal,
      });
      if (!res.ok || !res.body) throw new Error(`The assistant did not answer (${res.status}).`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          const line = frame.trim();
          if (!line.startsWith("data:")) continue;
          let event: any;
          try { event = JSON.parse(line.slice(5).trim()); } catch { continue; }

          if (event.type === "delta") {
            patch((t) => ({ ...t, text: t.text + event.text }));
          } else if (event.type === "tool") {
            patch((t) => ({ ...t, steps: [...t.steps, { name: event.name, say: event.say }] }));
          } else if (event.type === "tool_done") {
            patch((t) => ({
              ...t,
              steps: t.steps.map((s, i) =>
                i === t.steps.length - 1 ? { ...s, done: event.say } : s),
            }));
          } else if (event.type === "route") {
            patch((t) => ({ ...t, routes: [...t.routes, { title: event.title, steps: event.steps }] }));
          } else if (event.type === "diagram") {
            patch((t) => ({ ...t, diagrams: [...t.diagrams, { title: event.title, mermaid: event.mermaid }] }));
          } else if (event.type === "model") {
            patch((t) => ({ ...t, model: event.say }));
          } else if (event.type === "error") {
            patch((t) => ({ ...t, error: event.message }));
          }
          // Anything else is a frame this version does not draw yet, and is
          // ignored on purpose so the server can grow without breaking this.
        }
      }
    } catch (err: any) {
      if (err?.name !== "AbortError") {
        patch((t) => ({ ...t, error: err?.message || "The assistant stopped." }));
      }
    } finally {
      patch((t) => ({ ...t, live: false }));
      setBusy(false);
      abort.current = null;
    }
  }

  return (
    <div className={`ax${compact ? " is-compact" : ""}`}>
      <div className="ax-thread">
        {turns.length === 0 && (
          <div className="ax-open">
            <p className="ax-open-say">
              Ask where something is, how it is done, or what a code means.
              I can show you the steps and take you there.
            </p>
            <div className="ax-openers">
              {OPENERS.map((o) => (
                <button key={o} type="button" className="ax-opener" onClick={() => ask(o)}>
                  {o}
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((turn, i) => (
          <article key={i} className="ax-turn">
            <p className="ax-asked">{turn.question}</p>

            {turn.steps.length > 0 && (
              <ol className="ax-steps-live" aria-live="polite">
                {turn.steps.map((step, n) => {
                  const Mark = MARKS[step.name] ?? MagnifyingGlass;
                  const running = turn.live && n === turn.steps.length - 1 && !step.done;
                  return (
                    <li key={n} className={running ? "is-running" : "is-done"}>
                      <Mark size={13} weight={running ? "regular" : "fill"} />
                      <span className={running ? "ai-shimmer" : undefined}>{step.say}</span>
                      {step.done && <span className="ax-step-done">{step.done}</span>}
                    </li>
                  );
                })}
              </ol>
            )}

            {turn.model && <p className="ax-model">{turn.model}</p>}

            {turn.routes.map((r, n) => (
              <AssistantRoute key={n} title={r.title} steps={r.steps} />
            ))}
            {turn.diagrams.map((d, n) => (
              <AssistantDiagram key={n} title={d.title} source={d.mermaid} />
            ))}

            {turn.text && (
              <div className={`ax-said${turn.live ? " ai-caret" : ""}`}>
                <Markdown text={turn.text} />
              </div>
            )}
            {turn.error && <div className="alert error">{turn.error}</div>}
          </article>
        ))}
        <div ref={foot} />
      </div>

      <form
        className="ax-ask"
        onSubmit={(e) => { e.preventDefault(); ask(question); }}
      >
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Where is… ? How do I… ?"
          aria-label="Ask RX-Assistant"
        />
        {busy ? (
          <button type="button" className="btn ghost ax-stop"
                  onClick={() => abort.current?.abort()} aria-label="Stop">
            <Stop size={15} weight="fill" />
          </button>
        ) : (
          <button type="submit" className="btn primary ax-send"
                  disabled={!question.trim()} aria-label="Ask">
            <ArrowUp size={15} weight="bold" />
          </button>
        )}
      </form>
    </div>
  );
}
