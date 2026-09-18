/** The steps to get somewhere, drawn as chips that take you there.
 *
 *  The whole point of RX-Assistant over a help page. "Dispensary, then
 *  double-click the Amount column" written as a sentence leaves somebody to go
 *  and find both; the same thing drawn here navigates to the screen and lights
 *  up the control.
 *
 *  The steps are composed by the model and drawn here, never parsed out of
 *  prose: the server sends them as a frame with a schema the model is held to,
 *  so a step either has a route it can go to or it does not, and there is no
 *  sentence to misread.
 *
 *  A step that changes something is marked. "Go to the Dispensary" and "Finish
 *  the script" are not the same kind of instruction, and on a system where
 *  finishing fiscalises a receipt the difference is worth a stripe.
 */
import { useNavigate } from "react-router-dom";
import { ArrowRight, CursorClick } from "@phosphor-icons/react";

export interface RouteStep {
  label: string;
  /** A route to open, from the atlas. */
  go?: string;
  /** A CSS selector for the control on that screen. */
  click?: string;
  key?: string;
  /** True where the step changes something rather than navigating. */
  does?: boolean;
}

/** Take somebody to a step, and show them the control when they arrive.
 *
 *  The highlight is done here rather than by the page: a page that had to know
 *  how to be pointed at would need changing once per thing worth pointing at,
 *  and this needs to work on screens nobody has thought about yet.
 */
export function goToStep(step: RouteStep, navigate: (to: string) => void) {
  if (step.go) navigate(step.go);
  if (!step.click) return;
  // Looked for until it appears, rather than once after a guess at how long
  // the screen takes. The dispensary is a heavy page behind a lazy chunk and a
  // single timeout found nothing on it, which reads as a chip that does not
  // work: the one thing this feature cannot afford to look like.
  const deadline = Date.now() + 4000;
  const look = () => {
    const target = document.querySelector<HTMLElement>(step.click!);
    if (!target) {
      if (Date.now() < deadline) window.setTimeout(look, 120);
      return;
    }
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.classList.add("is-pointed-at");
    if (typeof target.focus === "function") target.focus({ preventScroll: true });
    window.setTimeout(() => target.classList.remove("is-pointed-at"), 2600);
  };
  window.setTimeout(look, step.go ? 260 : 30);
}

export default function AssistantRoute({ title, steps }: {
  title: string;
  steps: RouteStep[];
}) {
  const navigate = useNavigate();
  if (!steps?.length) return null;

  return (
    <figure className="ax-route">
      {title && <figcaption className="ax-route-title">{title}</figcaption>}
      <ol className="ax-steps">
        {steps.map((step, i) => (
          <li key={i}>
            {i > 0 && <ArrowRight size={13} className="ax-arrow" aria-hidden="true" />}
            <button
              type="button"
              className={`ax-step${step.does ? " does" : ""}`}
              // Only clickable where there is somewhere to go. A chip that
              // looks like a button and does nothing teaches people to stop
              // trying the ones that do.
              disabled={!step.go && !step.click}
              onClick={() => goToStep(step, navigate)}
              title={step.go ? `Go to ${step.go}` : step.click ? "Show me" : undefined}
            >
              <span className="ax-step-n">{i + 1}</span>
              <span className="ax-step-label">{step.label}</span>
              {step.key && <kbd className="ax-key">{step.key}</kbd>}
              {step.click && <CursorClick size={12} className="ax-step-mark" aria-hidden="true" />}
            </button>
          </li>
        ))}
      </ol>
    </figure>
  );
}
