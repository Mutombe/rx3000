/** A person in a row: a face, then their name.
 *
 *  WHY A FACE, WHEN THE NAME IS RIGHT THERE.
 *
 *  Sixteen enterprise interfaces were studied side by side and every one of
 *  them draws people rather than spelling them. It is not decoration. A
 *  dispenser working a queue scans a column of thirty names for one of them,
 *  and a name is read letter by letter while a face is recognised before it is
 *  read. The face is what makes a list scannable; the name is what makes it
 *  certain.
 *
 *  It matters more here than in the interfaces it was learned from. This
 *  market has a small pool of surnames and a great many shared ones: a repeats
 *  queue can hold four people called Moyo, and four identical strings in a
 *  column is a list nobody can navigate. Four different faces is.
 *
 *  THE FACE IS NOT A CHOICE.
 *
 *  It is drawn from the name, deterministically, by the same component the
 *  signed-in user's own avatar comes from. So one person is one face on every
 *  screen in the product, nobody picks it, and nothing has to be stored.
 *
 *  A PERSON WHO IS NOT THERE GETS NO FACE.
 *
 *  An unnamed prescriber is not a person with a blank face, it is a fact that
 *  is missing, and this product says what is missing in its own words rather
 *  than drawing a placeholder and hoping. `absent` is that sentence.
 */
import { ReactNode } from "react";
import Blobatar from "./Blobatar";

/** How big a face is, by where it is standing.
 *
 *  Three sizes and no more. A table row is 36px, so 22 sits inside it without
 *  driving the row taller — which is the whole reason a dense table can carry
 *  faces at all. */
const SIZE = { row: 22, list: 28, head: 56 } as const;

export type PersonSize = keyof typeof SIZE;

export default function Person({
  name, meta, size = "row", absent = "Not recorded", title, className = "", children,
}: {
  /** Their whole name, as it is held. Blank means nobody is recorded. */
  name?: string | null;
  /** A second line under the name: a telephone number, a role, a scheme. */
  meta?: ReactNode;
  size?: PersonSize;
  /** What to say when there is no name. Said in words, never a dash. */
  absent?: string;
  title?: string;
  className?: string;
  /** Anything that goes after the name on the same line, such as a link or a
   *  state. Keeps the face and the name as one unit and lets the caller add
   *  to the row without rebuilding it. */
  children?: ReactNode;
}) {
  const said = (name ?? "").trim();
  if (!said) return <span className="muted">{absent}</span>;

  return (
    <span className={`person person-${size} ${className}`.trim()}>
      <Blobatar name={said} size={SIZE[size]} title={title ?? said} />
      <span className="person-said">
        <span className="person-name">{said}{children}</span>
        {meta ? <span className="person-meta">{meta}</span> : null}
      </span>
    </span>
  );
}
