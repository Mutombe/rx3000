/** Browser storage keys, and carrying the old ones forward.
 *
 *  The product was renamed RX3000 → RX5000. The wordmark is just text, but the
 *  storage keys are not: `rx3000_token` is somebody's session. Renaming the key
 *  in place would have logged out every pharmacist mid-shift the first time they
 *  loaded the new build — not a migration, an outage. The saved sidebar and
 *  density preferences are the same class of thing, smaller.
 *
 *  So each key is read under the new name, falls back to the old one, and on
 *  finding an old value moves it across and deletes it. Nobody is logged out,
 *  and the old names disappear on their own as people load the app once. */

const NEW = "rx5000_";
const OLD = "rx3000_";

export function readStored(name: string): string | null {
  try {
    const current = localStorage.getItem(NEW + name);
    if (current !== null) return current;

    const legacy = localStorage.getItem(OLD + name);
    if (legacy === null) return null;

    // Found under the old name: adopt it, then let it go.
    localStorage.setItem(NEW + name, legacy);
    localStorage.removeItem(OLD + name);
    return legacy;
  } catch {
    return null; // private mode, or storage disabled
  }
}

export function writeStored(name: string, value: string | null) {
  try {
    if (value === null) {
      localStorage.removeItem(NEW + name);
      localStorage.removeItem(OLD + name); // never let a stale twin resurrect
    } else {
      localStorage.setItem(NEW + name, value);
    }
  } catch { /* private mode — the preference just does not persist */ }
}
