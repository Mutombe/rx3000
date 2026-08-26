import { useCallback, useRef, useState } from "react";
import { apiBase, getToken } from "../api";
import type { Phase } from "../components/AiPhase";

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

  const ask = useCallback(async (question: string) => {
    stop();
    const controller = new AbortController();
    abort.current = controller;
    setText("");
    setError("");
    setPhase({ kind: "thinking" });

    try {
      const token = getToken();
      const res = await fetch(`${apiBase}/api/ai/ask/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ question }),
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

  return { ask, stop, text, phase, error, streaming: phase.kind !== "idle" };
}
