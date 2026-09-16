/** Work the software is doing, while the counter gets on with the next patient.
 *
 *  A dialog that sits on "Cancelling…" is the software making a pharmacist wait
 *  for its own bookkeeping, with a queue behind them. `useOptimisticList`
 *  already argues this for rows in a table; this is the same argument for the
 *  one-off actions that live in a modal — cancel a script, dispense one, put one
 *  on hold. The modal closes on the keystroke. The work carries on here.
 *
 *  WHAT IT GUARANTEES, BECAUSE OPTIMISM WITHOUT THESE IS JUST LYING
 *
 *  It is always visible. Every piece of work in flight is a chip on screen with
 *  a name a person recognises — "Cancelling RX38468" — so nothing is happening
 *  invisibly on somebody's behalf.
 *
 *  It always says what happened. Success and failure both end in a word: the
 *  chip turns and a toast is raised. Silence is never the answer, because the
 *  whole bargain of closing the dialog early is that the answer will find you.
 *
 *  A failure hands the work back. The chip stays, in red, with Try again on it,
 *  and the screen that started the work is told so it can put the script back
 *  where it was. Nothing is retried automatically: a dispensary that quietly
 *  re-sends a dispensing is worse than one that says it did not work.
 *
 *  It does not pretend to be finished. The chip shows real progress — started,
 *  working, done — and the done state lingers for a moment so the eye catches
 *  it, which is the whole of the gamified feel: press, watch it land, carry on.
 */
import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import { ArrowClockwise, Check, Warning, X } from "@phosphor-icons/react";
import { errorText } from "../api";
import { useToast } from "./Toast";

type State = "working" | "done" | "failed";

interface Job {
  id: number;
  /** What a person would call it: "Cancelling RX38468". */
  label: string;
  /** What to say when it lands. Defaults to the label in the past tense. */
  said?: string;
  state: State;
  detail: string;
  run: () => Promise<unknown>;
  /** Put the screen back the way it was, because the work did not happen. */
  undo?: (why: string) => void;
  /** Where this leads, offered rather than taken: a dispensing sent to the till
   *  used to navigate there by itself, which was fine while somebody stood
   *  waiting for it and is theft of the screen once they have moved on. */
  next?: { label: string; go: () => void };
  nextOf?: (result: any) => { label: string; go: () => void } | null;
}

export interface DoingApi {
  /** Start a piece of work, and get on with the next thing. */
  run: (job: {
    label: string;
    said?: string;
    run: () => Promise<unknown>;
    done?: (result: any) => void;
    undo?: (why: string) => void;
    next?: (result: any) => { label: string; go: () => void } | null;
  }) => void;
  /** Whether anything is in flight, for a screen that wants to wait for quiet. */
  busy: boolean;
}

const DoingContext = createContext<DoingApi | null>(null);

let seq = 0;

export function DoingProvider({ children }: { children: React.ReactNode }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const toast = useToast();
  const timers = useRef<number[]>([]);

  const forget = useCallback((id: number, linger = 2600) => {
    const t = window.setTimeout(
      () => setJobs((all) => all.filter((j) => j.id !== id)), linger);
    timers.current.push(t);
  }, []);

  const start = useCallback((job: Job) => {
    setJobs((all) => [...all, job]);
    job.run()
      .then((result: any) => {
        const next = job.nextOf?.(result) ?? null;
        setJobs((all) => all.map((j) => (
          j.id === job.id ? { ...j, state: "done" as const, next: next ?? undefined } : j)));
        toast.ok(job.said ?? `${job.label}. Done.`);
        // Somewhere to go stays long enough to be gone to.
        forget(job.id, next ? 9000 : 2600);
        return result;
      })
      .catch((e) => {
        const why = errorText(e);
        setJobs((all) => all.map((j) => (
          j.id === job.id ? { ...j, state: "failed" as const, detail: why } : j)));
        toast.error(why);
        job.undo?.(why);
      });
  }, [forget, toast]);

  const api = useMemo<DoingApi>(() => ({
    busy: jobs.some((j) => j.state === "working"),
    run: ({ label, said, run, done, undo, next }) => {
      seq += 1;
      start({
        id: seq, label, said, state: "working", detail: "",
        run: () => run().then((r) => { done?.(r); return r; }),
        undo, nextOf: next,
      });
    },
  }), [jobs, start]);

  return (
    <DoingContext.Provider value={api}>
      {children}
      {jobs.length > 0 && (
        <div className="doing" role="status" aria-live="polite">
          {jobs.map((job) => (
            <div key={job.id} className={`doing-chip is-${job.state}`}>
              <span className="doing-icon">
                {job.state === "working" && <span className="doing-spin" aria-hidden="true" />}
                {job.state === "done" && <Check size={13} weight="bold" />}
                {job.state === "failed" && <Warning size={13} weight="fill" />}
              </span>
              <span className="doing-what">
                {/* Past tense once it has landed: a tick beside "Dispensing…"
                    reads as though it were still going. */}
                {job.state === "done" ? (job.said ?? job.label) : job.label}
                {job.state === "failed" && job.detail && (
                  <span className="doing-why">{job.detail}</span>
                )}
              </span>
              {job.state === "failed" && (
                <>
                  <button type="button" className="doing-act"
                          onClick={() => {
                            setJobs((all) => all.filter((j) => j.id !== job.id));
                            seq += 1;
                            start({ ...job, id: seq, state: "working", detail: "" });
                          }}>
                    <ArrowClockwise size={12} weight="bold" /> Try again
                  </button>
                  <button type="button" className="doing-act is-quiet"
                          aria-label="Dismiss"
                          onClick={() => setJobs((all) => all.filter((j) => j.id !== job.id))}>
                    <X size={12} weight="bold" />
                  </button>
                </>
              )}
              {job.state === "done" && job.next && (
                <button type="button" className="doing-act"
                        onClick={() => {
                          setJobs((all) => all.filter((j) => j.id !== job.id));
                          job.next!.go();
                        }}>
                  {job.next.label}
                </button>
              )}
              {job.state === "working" && <span className="doing-bar" aria-hidden="true" />}
            </div>
          ))}
        </div>
      )}
    </DoingContext.Provider>
  );
}

/** The work tray. Outside a provider it runs the work plainly, so a screen
 *  rendered on its own in a test still behaves. */
export function useDoing(): DoingApi {
  const api = useContext(DoingContext);
  const toast = useToast();
  return api ?? {
    busy: false,
    run: ({ label, said, run, done, undo }) => {
      run()
        .then((r) => { done?.(r); toast.ok(said ?? `${label}. Done.`); })
        .catch((e) => { const why = errorText(e); toast.error(why); undo?.(why); });
    },
  };
}
