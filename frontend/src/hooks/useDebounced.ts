/** A value that settles before anything acts on it.
 *
 *  Search boxes here fired a request per keystroke: typing "paracetamol" sent
 *  twelve requests, of which eleven were already stale when they left. On a
 *  pharmacy's connection the answers can also arrive out of order, so the list
 *  briefly shows the results for "parac" after the results for "paracetamol" —
 *  which reads as the search being broken rather than slow.
 *
 *  250ms is about the gap between keystrokes for someone typing normally, so a
 *  request goes when they pause rather than while they are still thinking.
 */
import { useEffect, useState } from "react";

export function useDebounced<T>(value: T, delay = 250): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setSettled(value), delay);
    return () => window.clearTimeout(t);
  }, [value, delay]);
  return settled;
}
