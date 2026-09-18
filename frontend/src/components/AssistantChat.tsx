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
 *  few seconds because it is looking things up. So every step says what it is
 *  and how long it took: looking something up, drawing the steps, handing the
 *  question to the bigger model. Somebody who can see it working will wait;
 *  somebody watching a spinner decides it is broken.
 *
 *  WHAT MAKES IT A TOOL RATHER THAN A TOY.
 *
 *  A single line input is a search box. This is a composer: it grows as you
 *  type, Enter sends and Shift with Enter starts a new line, the last thing you
 *  asked comes back with the up arrow, and every answer can be copied or asked
 *  again. A question at a counter is often two sentences, and a chat that
 *  cannot hold two sentences gets one.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  ArrowUp, Stop, MagnifyingGlass, Path, TreeStructure, Brain, Globe,
  Copy, Check, ArrowsClockwise, CaretDown, Package, ChartLineUp, TrendUp,
  Paperclip, X, FilePdf,
} from "@phosphor-icons/react";

import { getToken } from "../api";
import Markdown from "./Markdown";
import AssistantRoute, { RouteStep } from "./AssistantRoute";
import AssistantDiagram from "./AssistantDiagram";
import { Attachment, MAX_FILES, TAKES, filesFrom, readForAssistant }
  from "../assistantFiles";
import { useToast } from "./Toast";

/** One thing that happened while the answer was being worked out. */
interface Step { name: string; say: string; done?: string; ms?: number }

interface Turn {
  question: string;
  /** Thumbnails of what was sent with it, so the thread shows the screenshot
   *  the question was about rather than just the words. */
  shown?: { preview: string; name: string; media_type: string }[];
  text: string;
  steps: Step[];
  routes: { title: string; steps: RouteStep[] }[];
  diagrams: { title: string; mermaid: string }[];
  model?: string;
  error?: string;
  /** Still being answered. */
  live?: boolean;
  /** How long the whole turn took, once it is finished. */
  ms?: number;
}

const MARKS: Record<string, any> = {
  find_in_app: MagnifyingGlass,
  show_route: Path,
  show_diagram: TreeStructure,
  think_harder: Brain,
  web_search: Globe,
  look_up_medicine: Package,
  usage_history: TrendUp,
  how_is_trade: ChartLineUp,
  what_is_low: Package,
};

const OPENERS = [
  "Where do I see what has been dispensed today?",
  "How do I set a price on a script?",
  "What does PP10 mean?",
  "What is running low?",
];

/** What to offer next, from what the answer turned out to be about.
 *
 *  Derived here rather than asked of the model: another round trip to guess at
 *  three follow-ups costs more than it is worth, and the useful ones are
 *  obvious from what was just drawn. */
function followUps(turn: Turn): string[] {
  const out: string[] = [];
  if (turn.routes.length) out.push("What permission does that need?");
  if (turn.steps.some((s) => s.name === "look_up_medicine")) {
    out.push("How fast does it move?");
    out.push("Which branch has the most?");
  }
  if (turn.steps.some((s) => s.name === "what_is_low")) {
    out.push("What should I order first?");
  }
  if (turn.steps.some((s) => s.name === "how_is_trade")) {
    out.push("How does that compare with last month?");
  }
  if (!out.length) out.push("Show me where that is");
  return out.slice(0, 3);
}

export default function AssistantChat({ compact = false }: { compact?: boolean }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState<number | null>(null);
  const [atBottom, setAtBottom] = useState(true);
  const [files, setFiles] = useState<Attachment[]>([]);
  const [dragging, setDragging] = useState(false);
  const picker = useRef<HTMLInputElement | null>(null);
  const toast = useToast();
  const abort = useRef<AbortController | null>(null);
  const thread = useRef<HTMLDivElement | null>(null);
  const box = useRef<HTMLTextAreaElement | null>(null);
  const lastAsked = useRef("");

  // Grows with what is typed, up to a point, then scrolls. A composer that
  // stays one line tall makes people write one line.
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, compact ? 110 : 160)}px`;
  }, [question, compact]);

  // Follow the answer as it arrives, but only while the reader is already at
  // the bottom: yanking the view back while somebody is reading the middle of
  // a long answer is the rudest thing a chat can do.
  useEffect(() => {
    if (!atBottom) return;
    const el = thread.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns, atBottom]);

  const onScroll = useCallback(() => {
    const el = thread.current;
    if (!el) return;
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 48);
  }, []);

  useEffect(() => () => abort.current?.abort(), []);

  async function take(picked: File[]) {
    const room = MAX_FILES - files.length;
    if (room <= 0) {
      toast.warn(`${MAX_FILES} attachments is the most I can read at once.`);
      return;
    }
    for (const file of picked.slice(0, room)) {
      try {
        const ready = await readForAssistant(file);
        setFiles((all) => [...all, ready]);
      } catch (e: any) {
        toast.error(e?.message || "That file could not be read.");
      }
    }
    box.current?.focus();
  }

  async function ask(asked: string) {
    const said = asked.trim();
    const sending = files;
    // A screenshot on its own is a question: "what is this". Only an empty
    // composer with nothing attached is nothing to send.
    if ((!said && !sending.length) || busy) return;
    lastAsked.current = said;
    setQuestion("");
    setBusy(true);
    setAtBottom(true);
    const began = Date.now();

    // The turn goes up before the first byte comes back, so the question is on
    // screen while it is being answered rather than appearing with the answer.
    setFiles([]);
    setTurns((all) => [...all, {
      question: said || "What is this?", text: "", steps: [], routes: [],
      diagrams: [], live: true,
      shown: sending.map((f) => ({ preview: f.preview, name: f.name,
                                   media_type: f.media_type })),
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
          question: said || "What is this, and what should I do about it?",
          files: sending.map((f) => ({ media_type: f.media_type, data: f.data })),
          history: turns.flatMap((t) => ([
            { role: "user", content: t.question },
            { role: "assistant", content: t.text || "(no answer)" },
          ])).slice(-8),
        }),
        signal: control.signal,
      });
      if (res.status === 404) {
        throw new Error("This copy of the server does not have RX-Assistant yet. "
                      + "It arrives with the next deployment.");
      }
      if (!res.ok || !res.body) throw new Error(`The assistant did not answer (${res.status}).`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let stepAt = Date.now();
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
            stepAt = Date.now();
            patch((t) => ({ ...t, steps: [...t.steps, { name: event.name, say: event.say }] }));
          } else if (event.type === "tool_done") {
            const took = Date.now() - stepAt;
            patch((t) => ({
              ...t,
              steps: t.steps.map((s, i) =>
                i === t.steps.length - 1 ? { ...s, done: event.say, ms: took } : s),
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
      patch((t) => ({ ...t, live: false, ms: Date.now() - began }));
      setBusy(false);
      abort.current = null;
      box.current?.focus();
    }
  }

  async function copy(turn: Turn, i: number) {
    try {
      await navigator.clipboard.writeText(turn.text);
      setCopied(i);
      window.setTimeout(() => setCopied((n) => (n === i ? null : n)), 1600);
    } catch { /* a browser that refuses the clipboard is not worth a message */ }
  }

  const said = (ms?: number) =>
    ms === undefined ? "" : ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;

  return (
    <div
      className={`ax${compact ? " is-compact" : ""}${dragging ? " is-dropping" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={(e) => {
        if (e.currentTarget.contains(e.relatedTarget as Node)) return;
        setDragging(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        const dropped = filesFrom(e.dataTransfer);
        if (dropped.length) take(dropped);
      }}
    >
      <div className="ax-thread" ref={thread} onScroll={onScroll}>
        {turns.length === 0 && (
          <div className="ax-open">
            <p className="ax-open-say">
              Ask where something is, how it is done, what a code means, or what
              your own figures say. I can show you the steps and take you there.
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
            {turn.shown && turn.shown.length > 0 && (
              <div className="ax-sent">
                {turn.shown.map((f, n) => (
                  f.media_type === "application/pdf"
                    ? <span key={n} className="ax-file"><FilePdf size={15} /> {f.name}</span>
                    : <img key={n} src={f.preview} alt={f.name} className="ax-shot" />
                ))}
              </div>
            )}
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
                      {step.ms !== undefined && (
                        <span className="ax-step-ms">{said(step.ms)}</span>
                      )}
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

            {/* What can be done with an answer, once there is one. */}
            {!turn.live && (turn.text || turn.error) && (
              <div className="ax-acts">
                {turn.text && (
                  <button type="button" className="ax-act" onClick={() => copy(turn, i)}>
                    {copied === i ? <Check size={12} weight="bold" /> : <Copy size={12} />}
                    {copied === i ? "Copied" : "Copy"}
                  </button>
                )}
                <button type="button" className="ax-act" onClick={() => ask(turn.question)}
                        disabled={busy}>
                  <ArrowsClockwise size={12} /> Ask again
                </button>
                {turn.ms !== undefined && (
                  <span className="ax-took">{said(turn.ms)}</span>
                )}
              </div>
            )}

            {/* Where to go next, offered only on the newest answer so the
                thread does not fill with stale suggestions. */}
            {!turn.live && turn.text && !turn.error && i === turns.length - 1 && (
              <div className="ax-next">
                {followUps(turn).map((f) => (
                  <button key={f} type="button" className="ax-opener" onClick={() => ask(f)}>
                    {f}
                  </button>
                ))}
              </div>
            )}
          </article>
        ))}
      </div>

      {/* Only while there is something below to go back to. */}
      {!atBottom && (
        <button type="button" className="ax-jump"
                onClick={() => { setAtBottom(true); const el = thread.current;
                                 if (el) el.scrollTop = el.scrollHeight; }}>
          <CaretDown size={13} weight="bold" /> Latest
        </button>
      )}

      <form
        className="ax-ask"
        onSubmit={(e) => { e.preventDefault(); ask(question); }}
      >
        {files.length > 0 && (
          <div className="ax-tray">
            {files.map((f, n) => (
              <span key={n} className="ax-chip-file">
                {f.media_type === "application/pdf"
                  ? <FilePdf size={15} />
                  : <img src={f.preview} alt="" />}
                <span className="ax-chip-name">{f.name}</span>
                <button type="button" aria-label={`Remove ${f.name}`}
                        onClick={() => setFiles((all) => all.filter((_, i) => i !== n))}>
                  <X size={11} weight="bold" />
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="ax-ask-row">
        <input
          ref={picker} type="file" multiple hidden accept={TAKES.join(",")}
          onChange={(e) => {
            take(Array.from(e.target.files ?? []));
            e.currentTarget.value = "";
          }}
        />
        <button type="button" className="ax-clip" onClick={() => picker.current?.click()}
                title="Attach a screenshot or a PDF" aria-label="Attach a file">
          <Paperclip size={15} />
        </button>
        <textarea
          ref={box}
          rows={1}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Where is… ? How do I… ?   Paste a screenshot."
          aria-label="Ask RX-Assistant"
          onPaste={(e) => {
            // The whole reason this works the way it does: print-screen, then
            // Ctrl with V, and the picture of the problem is in the question.
            const pasted = filesFrom(e.clipboardData);
            if (pasted.length) { e.preventDefault(); take(pasted); }
          }}
          onKeyDown={(e) => {
            // Enter sends, because that is what a chat does. Shift with Enter
            // is a new line, because a question at a counter is sometimes two
            // sentences and the first one alone reads as a different question.
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              ask(question);
              return;
            }
            // The last thing asked, back again, for a small correction rather
            // than retyping it.
            if (e.key === "ArrowUp" && !question && lastAsked.current) {
              e.preventDefault();
              setQuestion(lastAsked.current);
            }
          }}
        />
        {busy ? (
          <button type="button" className="btn ghost ax-stop"
                  onClick={() => abort.current?.abort()} aria-label="Stop">
            <Stop size={15} weight="fill" />
          </button>
        ) : (
          <button type="submit" className="btn primary ax-send"
                  disabled={!question.trim() && !files.length} aria-label="Ask">
            <ArrowUp size={15} weight="bold" />
          </button>
        )}
        </div>
      </form>
    </div>
  );
}
