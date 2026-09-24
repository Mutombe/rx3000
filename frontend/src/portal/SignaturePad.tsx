/** Somewhere for a patient to sign, on a phone held out on a doorstep.
 *
 *  WHY A SIGNATURE AND NOT A TYPED NAME
 *
 *  A typed name is the driver's claim about who took the parcel. A signature
 *  is the recipient's own mark, and it is what a disputed delivery is actually
 *  argued from when a funder or a patient says the parcel never arrived. The
 *  product had no signature capture anywhere before this.
 *
 *  SIZED FOR A THUMB, NOT A MOUSE
 *
 *  Drawn with pointer events, which covers finger, stylus and the mouse a
 *  tester will use, in one set of handlers. The canvas is backed at the
 *  device's own pixel ratio, because a signature drawn at CSS resolution and
 *  scaled up is a blurry mark on a claim form.
 *
 *  IT REFUSES AN EMPTY STROKE
 *
 *  A pad somebody tapped once is not a signature, and a delivery with a dot
 *  against it is worse than one with nothing, because it looks answered.
 */
import { useEffect, useRef, useState } from "react";

export default function SignaturePad({ onChange, label }: {
  /** The mark as a PNG data URI, or "" while there is nothing worth keeping. */
  onChange: (dataUri: string) => void;
  label?: string;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  // Counted rather than flagged: one tap puts a single point on the canvas and
  // that is not a signature. A real one is dozens of segments.
  const marks = useRef(0);
  const [drawn, setDrawn] = useState(false);

  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    // Backed at the device's own resolution, then scaled once, so the stroke
    // is as sharp as the screen allows and the coordinates stay in CSS pixels.
    const ratio = window.devicePixelRatio || 1;
    const box = el.getBoundingClientRect();
    el.width = Math.round(box.width * ratio);
    el.height = Math.round(box.height * ratio);
    const ink = el.getContext("2d");
    if (!ink) return;
    ink.scale(ratio, ratio);
    ink.lineWidth = 2.4;
    ink.lineCap = "round";
    ink.lineJoin = "round";
    // FIXED DARK INK, NOT THE THEME'S.
    //
    // This looks like the place to read the theme's ink off the element, and
    // that is wrong: the PNG has a transparent background and is shown later
    // on a white panel and printed on white paper. A signature drawn in the
    // dark theme's near-white ink is an invisible mark on a claim form, and
    // nobody finds that out until a funder asks for it. The pad is painted
    // light in both themes to match, in portal.css.
    ink.strokeStyle = "#16161d";
  }, []);

  function at(e: React.PointerEvent<HTMLCanvasElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    return { x: e.clientX - box.left, y: e.clientY - box.top };
  }

  function start(e: React.PointerEvent<HTMLCanvasElement>) {
    e.preventDefault();
    const ink = canvas.current?.getContext("2d");
    if (!ink) return;
    // Captured, so a stroke that leaves the canvas mid-signature still ends
    // where the finger lifted rather than trailing off the edge.
    e.currentTarget.setPointerCapture(e.pointerId);
    drawing.current = true;
    const p = at(e);
    ink.beginPath();
    ink.moveTo(p.x, p.y);
  }

  function move(e: React.PointerEvent<HTMLCanvasElement>) {
    if (!drawing.current) return;
    e.preventDefault();
    const ink = canvas.current?.getContext("2d");
    if (!ink) return;
    const p = at(e);
    ink.lineTo(p.x, p.y);
    ink.stroke();
    marks.current += 1;
    if (marks.current > 6 && !drawn) setDrawn(true);
  }

  function end() {
    if (!drawing.current) return;
    drawing.current = false;
    if (marks.current > 6) {
      onChange(canvas.current?.toDataURL("image/png") ?? "");
      setDrawn(true);
    }
  }

  function clear() {
    const el = canvas.current;
    const ink = el?.getContext("2d");
    if (!el || !ink) return;
    ink.clearRect(0, 0, el.width, el.height);
    marks.current = 0;
    setDrawn(false);
    onChange("");
  }

  return (
    <div className="dp-sign">
      {/* The label keeps the full width and the way out sits under the pad.
          Side by side, "Start again" squeezed "Ask them to sign here" onto
          two lines the moment it appeared. */}
      <span className="pp-label">{label ?? "Ask them to sign here"}</span>
      <canvas
        ref={canvas}
        className="dp-sign-pad"
        // `touch-action: none` in the stylesheet, so dragging a finger across
        // the pad draws instead of scrolling the page out from under it.
        onPointerDown={start}
        onPointerMove={move}
        onPointerUp={end}
        onPointerCancel={end}
        aria-label="Signature"
      />
      <div className="dp-sign-under">
        <span className="pp-fine">
          {drawn ? "That is enough." : "With a finger is fine."}
        </span>
        {drawn && (
          <button type="button" className="pp-ghost dp-sign-clear"
                  onClick={clear}>
            Start again
          </button>
        )}
      </div>
    </div>
  );
}
