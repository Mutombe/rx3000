import { useEffect, useRef, useState } from "react";

/** A smooth reveal, decoupled from however the text actually arrives.
 *
 *  Answers land in bursts: a whole paragraph appears, then nothing, then
 *  another. Rendering that directly makes the text jump, which reads as the
 *  machine stuttering rather than thinking. This accumulates the full target and
 *  drains it on an animation frame, at a speed that scales with how far behind
 *  it is: instant catch-up when a large burst lands, an even flow at the tail.
 *
 *  When `active` goes false the answer is finished, so it snaps to the whole
 *  text rather than politely typing out the last hundred characters while
 *  somebody waits to read them.
 */
export function useTypewriter(target: string, active: boolean): string {
  const [shown, setShown] = useState(active ? "" : target);
  const shownLen = useRef(active ? 0 : target.length);
  const raf = useRef(0);

  useEffect(() => {
    if (!active) {
      shownLen.current = target.length;
      setShown(target);
      return;
    }
    // The target got shorter, so a new answer is reusing this hook.
    if (shownLen.current > target.length) shownLen.current = 0;

    const tick = () => {
      const backlog = target.length - shownLen.current;
      if (backlog > 0) {
        // Two characters a frame at the tail (~120 a second), and big strides
        // when a burst has left it far behind.
        const step = Math.max(2, Math.ceil(backlog / 24));
        shownLen.current = Math.min(target.length, shownLen.current + step);
        setShown(target.slice(0, shownLen.current));
      }
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [target, active]);

  return shown;
}
