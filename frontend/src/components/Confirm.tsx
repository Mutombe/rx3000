/** Confirmation, in the application rather than in the browser.
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
}

type Resolver = (ok: boolean) => void;

const Ctx = createContext<(ask: Ask) => Promise<boolean>>(async () => false);

/** `const confirm = useConfirm(); if (await confirm({...})) …` */
export function useConfirm() {
  return useContext(Ctx);
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [ask, setAsk] = useState<Ask | null>(null);
  const resolver = useRef<Resolver | null>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  const request = useCallback((next: Ask) => {
    setAsk(next);
    return new Promise<boolean>((resolve) => { resolver.current = resolve; });
  }, []);

  function close(ok: boolean) {
    resolver.current?.(ok);
    resolver.current = null;
    setAsk(null);
  }

  useEffect(() => {
    if (!ask) return;
    // Focus the safe option. On a destructive prompt that is Cancel, so the
    // dispenser's habitual Enter does not confirm something irreversible.
    cancelRef.current?.focus();
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
            <div className="cf-actions">
              <button ref={cancelRef} className="btn" onClick={() => close(false)}>
                {ask.cancelLabel ?? "Cancel"}
              </button>
              <button
                className={`btn ${ask.destructive ? "danger" : "primary"}`}
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
