/** The drawn face everybody in this product has.
 *
 *  A pharmacy is not a social network. Nobody is uploading a photograph of
 *  themselves to a till, and asking them to would mean a file store, an upload
 *  control, a crop, a size limit and somebody deciding what is allowed in one.
 *  But a staff list of identical grey discs is unreadable, and a dispensing
 *  history where every row wears the same initial is anonymous in the one place
 *  that has to name who did what.
 *
 *  So every person is drawn from a string. `blobatar` turns a seed into the
 *  same face for ever: nothing to store but the seed, nothing to upload,
 *  nothing to moderate, and two people with the same initials look nothing
 *  alike.
 *
 *  ONE COMPONENT, DELIBERATELY. There were two avatars before this, and they
 *  disagreed: the corner of the screen drew the signed-in user's initials on a
 *  flat disc, the CRM screens drew a different set of initials on a gradient,
 *  and neither knew about the other. An avatar that is one thing in the header
 *  and another in the staff list is worse than no avatar, because it reads as
 *  two different people. Everything goes through here.
 */
import { useMemo } from "react";
import { blobatar } from "blobatar";

/** How many faces the picker offers. Enough to feel like a choice, few enough
 *  to see at once without scrolling on a laptop. */
export const CHOICES = 24;

/** The seed a person is drawn from when they have not picked one.
 *
 *  Their name, so somebody who has never opened the profile page still has a
 *  face of their own the first time they sign in, and the same one on every
 *  screen and every device. Falling back to a blank would have made "has not
 *  chosen yet" look like "no such person".
 */
export function defaultSeed(name?: string | null, id?: number | string): string {
  const said = (name ?? "").trim();
  if (said) return said;
  // Somebody with no name on record still gets a face rather than a hole.
  return id != null ? `user-${id}` : "somebody";
}

/** The seeds offered in the picker, for one person.
 *
 *  Derived from their own default seed rather than random, so the grid is the
 *  same every time they open it: a choice that reshuffles under you is not a
 *  choice, and somebody who liked the third one and closed the page should
 *  find it in the same place.
 */
export function choicesFor(name?: string | null, id?: number | string): string[] {
  const base = defaultSeed(name, id);
  return [base, ...Array.from({ length: CHOICES - 1 },
                              (_, i) => `${base}#${i + 1}`)];
}

export default function Blobatar({
  seed, name, id, size = 34, title, className = "",
}: {
  /** The chosen seed. Empty or missing falls back to the name. */
  seed?: string | null;
  name?: string | null;
  id?: number | string;
  size?: number;
  title?: string;
  className?: string;
}) {
  const use = (seed ?? "").trim() || defaultSeed(name, id);
  // Drawn once per seed and size. It is a few hundred bytes of SVG, and a
  // staff list renders forty of them.
  const svg = useMemo(
    () => blobatar(use, { background: "circle" }),
    [use]);
  return (
    <span
      className={`blobatar ${className}`.trim()}
      style={{ width: size, height: size }}
      title={title ?? name ?? undefined}
      // The face carries no information a screen reader needs that the name
      // beside it does not already give, and reading out "avatar" before every
      // row is noise.
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
