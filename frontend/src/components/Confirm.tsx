/** Confirmation and asking for a value, in the application rather than in the
 *  browser.
 *
 *  `window.confirm` was doing this job. Three problems with it, in the order
 *  they matter at a counter:
 *
 *  * It blocks. In a Tauri window the whole application freezes until it is
 *    answered — no toast can appear, no background refresh completes, and a
 *    till that has stopped responding looks broken rather than busy.
 *  * It cannot say what is at stake. A native dialog gets one string and two
 *    buttons labelled OK and Cancel. "Write off 40 units of Amoxicillin" needs
 *    the quantity, the batch and the consequence, and the confirming button
 *    should say *write off*, not *OK*.
 *  * It looks like the operating system, not like this product, which on a
 *    machine a pharmacy bought to run one application is jarring.
 *
 *  Destructive actions get a red confirm button and the focus stays on Cancel,
 *  so a reflexive Enter does not write off stock.
 *
 *  ASKING FOR A VALUE
 *
 *  `window.prompt` was doing that job in four places, with every fault above
 *  and two of its own. It returns a bare string with no validation, so "why was
 *  this lead disqualified" accepted an empty answer and recorded a reason of
 *  nothing; and on the will-call shelf it was collecting **who took a
 *  controlled substance**, a legal record, through an unstyled operating
 *  system box with no label, no hint and no way to require an answer.
 *
 *  `ask()` is the same dialog with a field in it. It can require a value,
 *  which is the whole point on the handover.
 */
import {
  createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState,
} from "react";

interface Ask {
  title: string;
  /** What will actually happen. Written as a sentence, not a label. */
  body?: ReactNode;
  /** The verb, not "OK": "Write off", "Retire", "Void the sale". */
  confirmLabel?: string;
  cancelLabel?: string;
  /** Red button, focus parked on Cancel. */
  destructive?: boolean;
  /** Ask for a value as well as a yes. The label above the field. */
  field?: string;
  placeholder?: string;
  /** An empty answer is refused. Used where the value is the record. */
  required?: boolean;
  maxLength?: number;
}

type Answer = { ok: boolean; value: string };
type Resolver = (answer: Answer) => void;

const Ctx = createContext<(ask: Ask) => Promise<Answer>>(
  async () => ({ ok: false, value: "" }));

/** `const confirm = useConfirm(); if (await confirm({...})) …`
 *
 *  Returns a boolean, so every existing caller is untouched. Where a value is
 *  wanted, `useAsk` returns the whole answer.
 */
export function useConfirm() {
  const request = useContext(Ctx);
  return useCallback(
    async (ask: Ask) => (await request(ask)).ok, [request]);
}

/** `const ask = useAsk(); const { ok, value } = await ask({ field: "Why?" })` */
export function useAsk() {
  return useContext(Ctx);
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [ask, setAsk] = useState<Ask | null>(null);
  const [value, setValue] = useState("");
  const resolver = useRef<Resolver | null>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const fieldRef = useRef<HTMLInputElement>(null);

  const request = useCallback((next: Ask) => {
    setAsk(next);
    setValue("");
    return new Promise<Answer>((resolve) => { resolver.current = resolve; });
  }, []);

  function close(ok: boolean) {
    resolver.current?.({ ok, value: ok ? value.trim() : "" });
    resolver.current = null;
    setAsk(null);
    setValue("");
  }

  useEffect(() => {
    if (!ask) return;
    // The field where there is one — somebody asked a question is expected to
    // start typing, and a dialog that makes them click first is one they fight.
    // Otherwise the safe option: on a destructive prompt that is Cancel, so the
    // dispenser's habitual Enter does not confirm something irreversible.
    if (ask.field) fieldRef.current?.focus();
    else cancelRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") { e.preventDefault(); close(false); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ask]);

  return (
    <Ctx.Provider value={request}>
      {children}
      {ask && (
        <div className="cf-backdrop" role="presentation" onMouseDown={() => close(false)}>
          <div
            className="cf-box"
            role="alertdialog"
            aria-modal="true"
            aria-label={ask.title}
            // The backdrop closes; a click inside must not travel to it.
            onMouseDown={(e) => e.stopPropagation()}
          >
            <h3 className="cf-title">{ask.title}</h3>
            {ask.body && <div className="cf-body">{ask.body}</div>}
            {ask.field && (
              <label className="cf-field">
                <span>
                  {ask.field}
                  {ask.required && <span className="cf-required"> required</span>}
                </span>
                <input
                  ref={fieldRef}
                  value={value}
                  maxLength={ask.maxLength ?? 200}
                  placeholder={ask.placeholder}
                  onChange={(e) => setValue(e.target.value)}
                  // Enter submits, which is what somebody typing an answer
                  // expects. Blocked while a required field is empty, so the
                  // habit cannot produce a blank record.
                  onKeyDown={(e) => {
                    if (e.key !== "Enter") return;
                    e.preventDefault();
                    if (!ask.required || value.trim()) close(true);
                  }}
                />
              </label>
            )}
            <div className="cf-actions">
              <button ref={cancelRef} className="btn" onClick={() => close(false)}>
                {ask.cancelLabel ?? "Cancel"}
              </button>
              <button
                className={`btn ${ask.destructive ? "danger" : "primary"}`}
                // A required answer cannot be skipped by pressing the button
                // either. The value IS the record on a controlled handover.
                disabled={!!ask.field && !!ask.required && !value.trim()}
                onClick={() => close(true)}
              >
                {ask.confirmLabel ?? "Confirm"}
              </button>
            </div>
          </div>
        </div>
      )}
    </Ctx.Provider>
  );
}
