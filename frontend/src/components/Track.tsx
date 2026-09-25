/** How far along a row is, drawn on the row.
 *
 *  A waybill is raised, goes out with a driver, and is signed for at a door.
 *  That is a journey, and a journey shown as a word tells you where it is but
 *  not how far that is from the end: "out" and "delivered" are the same size
 *  on the page and look equally final. Somebody scanning forty waybills for
 *  the ones still moving reads forty words.
 *
 *  Drawn, it is one glance. Filled behind you, hollow ahead, on a line. The
 *  Shipment reference does exactly this and it is the clearest thing in the
 *  whole set.
 *
 *  NOT `StepTrail`. That is the dispensary's form navigator: numbered, with a
 *  sentence per step saying what is missing, clickable, scrolling the page to
 *  the card it names. This is four pixels on a table row and is not a control.
 *  One of them would be a bad version of the other.
 *
 *  WHAT AN EXIT LOOKS LIKE.
 *
 *  A delivery that failed did not reach the end and did not stop halfway: it
 *  left the path. So the last node is marked rather than filled, and the line
 *  to it is not drawn as completed. A track that showed a failure as "done"
 *  would be the row lying about the one thing somebody is looking for.
 */
export interface Stage {
  /** What this stage is called, for the title a reader hovers. */
  said: string;
  /** Reached. */
  done: boolean;
  /** Reached, and it went wrong here. Ends the journey. */
  failed?: boolean;
}

export default function Track({ stages, title }: {
  stages: Stage[];
  /** The whole journey in words, for anybody who cannot see the drawing. */
  title?: string;
}) {
  const said = title
    ?? stages.map((s) => `${s.said}: ${s.failed ? "failed" : s.done ? "done" : "not yet"}`)
             .join(" · ");
  return (
    <span className="track" title={said} role="img" aria-label={said}>
      {stages.map((s, i) => (
        <span
          key={i}
          className={["track-step",
                      s.failed ? "is-failed" : s.done ? "is-done" : ""]
                     .filter(Boolean).join(" ")}
          // The line into this node is only drawn as travelled when the step
          // before it was actually reached.
          data-linked={i > 0 && stages[i - 1].done && !stages[i - 1].failed
                       ? "true" : "false"}
        />
      ))}
    </span>
  );
}

/** The three stages a waybill passes through, from its status.
 *
 *  Kept here rather than in the page, because the delivery list, the driver's
 *  own screen and the waybill's page all show the same journey and must not
 *  disagree about where it has got to.
 */
export function waybillStages(status: string): Stage[] {
  const out = status === "out" || status === "delivered" || status === "failed";
  return [
    { said: "Raised", done: true },
    { said: "Out with a driver", done: out },
    { said: "Signed for at the door",
      done: status === "delivered",
      failed: status === "failed" },
  ];
}
