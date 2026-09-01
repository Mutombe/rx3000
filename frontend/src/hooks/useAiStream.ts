import { useCallback, useEffect, useRef, useState } from "react";
import { apiBase, getToken } from "../api";
import type { Phase } from "../components/AiPhase";
import { useTypewriter } from "./useTypewriter";

/** Consume the assistant's answer as it is written.
 *
 *  Raw `fetch` with a ReadableStream rather than the shared `api` helper: that
 *  one parses a whole JSON body, which means waiting for the last byte, which is
 *  exactly what streaming exists to avoid.
 *
 *  Frames are JSON objects rather than bare text. A delta that happens to
 *  contain a blank line would otherwise look like the end of an event, and the
 *  answer would silently truncate at the first paragraph break.
 */
export function useAiStream() {
  const [text, setText] = useState("");
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [error, setError] = useState("");
  const abort = useRef<AbortController | null>(null);

  const stop = useCallback(() => {
    abort.current?.abort();
    abort.current = null;
    setPhase({ kind: "idle" });
  }, []);

  /** Stream any AI endpoint.
   *
   *  Was hardcoded to the assistant's path and a `{question}` body, which is why
   *  it could only ever serve one screen. Every AI surface now takes the same
   *  path: same frames, same phases, same abort. */
  const run = useCallback(async (path: string, body: unknown) => {
    stop();
    const controller = new AbortController();
    abort.current = controller;
    setText("");
    setError("");
    setPhase({ kind: "thinking" });

    try {
      const token = getToken();
      const res = await fetch(`${apiBase}${path}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) throw new Error(`The assistant is not reachable (${res.status}).`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Frames are separated by a blank line. Anything after the last one is
        // an incomplete frame and stays in the buffer for the next chunk.
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";

        for (const frame of frames) {
          const line = frame.split("\n").find((l) => l.startsWith("data:"));
          if (!line) continue;
          let event: any;
          try { event = JSON.parse(line.slice(5).trim()); } catch { continue; }

          if (event.type === "delta") {
            setPhase({ kind: "writing" });
            setText((t) => t + event.text);
          } else if (event.type === "phase") {
            setPhase(event.phase === "reading"
              ? { kind: "reading", what: "your live data" }
              : { kind: "thinking" });
          } else if (event.type === "error") {
            setError(event.message || "The assistant could not answer that.");
          }
        }
      }
    } catch (e: any) {
      // An abort is somebody pressing stop, not a failure to report.
      if (e?.name !== "AbortError") {
        setError(e?.message || "The assistant could not be reached.");
      }
    } finally {
      abort.current = null;
      setPhase({ kind: "idle" });
    }
  }, [stop]);

  /** Forget the last answer as well as stopping.
   *  `stop` ends the stream and leaves what was written on screen, which is what
   *  a Stop button should do. Clearing the basket is a different thing: an
   *  interaction read for a script that is no longer on screen is worse than
   *  none, because it looks current. */
  const reset = useCallback(() => {
    stop();
    setText("");
    setError("");
  }, [stop]);

  /** The assistant's own call, kept so that page reads as it did. */
  const ask = useCallback(
    (question: string) => run("/api/ai/ask/stream", { question }),
    [run]);

  return { ask, run, stop, reset, text, phase, error, streaming: phase.kind !== "idle" };
}

/** Stream a draft straight into a form field.
 *
 *  For the three screens where the answer is not something to read but something
 *  to edit and send: a ticket reply, campaign copy. The words land in the
 *  textarea as they arrive, so the staff member can start reading, and start
 *  disagreeing — before it has finished, which is most of the value of streaming
 *  a draft rather than presenting one.
 *
 *  The field is the single source of truth once the stream ends: whatever they
 *  typed over the top is what gets sent, and nothing writes to it afterwards.
 */
export function useAiDraft(setField: (value: string) => void) {
  const { run, stop, text, phase, error, streaming } = useAiStream();
  const shown = useTypewriter(text, streaming);

  useEffect(() => {
    // Only while it is streaming. Mirroring after the end would overwrite an
    // edit the moment the component re-rendered for any other reason.
    if (streaming) setField(shown);
  }, [shown, streaming]);

  return { draft: run, stop, phase, error, streaming };
}
