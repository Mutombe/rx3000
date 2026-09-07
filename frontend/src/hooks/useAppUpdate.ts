/** Is there a newer till application, and does the person want it now?
 *
 *  Until this existed, a pharmacy learned about a new version because somebody
 *  told them, then downloaded an installer and ran it. Six branches and a
 *  release every few weeks is a support call every few weeks.
 *
 *  THREE RULES, AND THEY ARE ALL ABOUT A COUNTER
 *
 *  **Nothing installs by itself.** A till restarting on its own in the middle
 *  of a sale is worse than a till running last month's version. The update is
 *  fetched and verified in the background and then waits — indefinitely, if
 *  that is what the day is like.
 *
 *  **Nothing blocks.** No modal on launch. The offer lives in the top bar
 *  beside the branch, where somebody notices it between customers rather than
 *  being interrupted by it.
 *
 *  **It is silent when there is nothing to say.** No "you are up to date"
 *  toast, no spinner on launch. A notification that appears when nothing has
 *  happened is one people learn to dismiss without reading.
 *
 *  ONLY IN THE DESKTOP SHELL
 *
 *  The browser has no installer to run: it updates by loading the page. Every
 *  call here is behind that check, so nothing is imported or attempted in a
 *  tab.
 */
import { useCallback, useEffect, useRef, useState } from "react";

export type UpdateStage =
  /** Nothing to offer, or not the desktop application. */
  | "none"
  /** A newer version exists and has not been fetched yet. */
  | "available"
  /** Downloading and verifying it. */
  | "fetching"
  /** On disk, verified, waiting for somebody to say when. */
  | "ready"
  /** The install is running; the window is about to close. */
  | "installing"
  /** It did not work, and the message says why. */
  | "failed";

export interface AppUpdate {
  stage: UpdateStage;
  /** The version being offered, once one is known. */
  version: string;
  /** What is in it, as published with the release. */
  notes: string;
  /** Set when `stage` is "failed". */
  error: string;
  /** Bytes fetched so far, for the progress line. */
  progress: number;
  /** Fetch and verify it. Safe to call twice. */
  download: () => Promise<void>;
  /** Install and restart. Only meaningful once ready. */
  install: () => Promise<void>;
  /** Ask again now. */
  check: () => Promise<void>;
}

/** Is this the Tauri shell rather than a browser tab? */
export function inDesktopApp(): boolean {
  return typeof globalThis !== "undefined"
    && "__TAURI_INTERNALS__" in (globalThis as object);
}

/** How often to look. Four hours: often enough that a pharmacy is never more
 *  than half a day behind, rare enough to be invisible. */
const EVERY_MS = 4 * 60 * 60 * 1000;

export function useAppUpdate(): AppUpdate {
  const [stage, setStage] = useState<UpdateStage>("none");
  const [version, setVersion] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [progress, setProgress] = useState(0);
  /** The Update object from the plugin, kept so `download` and `install` act
   *  on the one that was found rather than looking again. */
  const found = useRef<any>(null);

  const check = useCallback(async () => {
    if (!inDesktopApp()) return;
    try {
      const { check: ask } = await import("@tauri-apps/plugin-updater");
      const update = await ask();
      if (!update) {
        // Nothing newer. Deliberately silent — see the note at the top.
        setStage("none");
        return;
      }
      found.current = update;
      setVersion(update.version ?? "");
      setNotes((update.body ?? "").trim());
      setStage("available");
    } catch (e: any) {
      // A failed check is not worth telling anybody about: the network is down,
      // or the site is. The till goes on working and it asks again later.
      setStage("none");
      void e;
    }
  }, []);

  const download = useCallback(async () => {
    const update = found.current;
    if (!update) return;
    setStage("fetching");
    setProgress(0);
    try {
      let got = 0;
      await update.download((event: any) => {
        if (event?.event === "Progress") {
          got += event.data?.chunkLength ?? 0;
          setProgress(got);
        }
      });
      setStage("ready");
    } catch (e: any) {
      setError(String(e?.message ?? e ?? "The update could not be downloaded."));
      setStage("failed");
    }
  }, []);

  const install = useCallback(async () => {
    const update = found.current;
    if (!update) return;
    setStage("installing");
    try {
      await update.install();
      // Windows hands over to the installer and closes this process. On the
      // platforms that do not, the restart has to be asked for.
      const { relaunch } = await import("@tauri-apps/plugin-process");
      await relaunch();
    } catch (e: any) {
      setError(String(e?.message ?? e ?? "The update could not be installed."));
      setStage("failed");
    }
  }, []);

  useEffect(() => {
    if (!inDesktopApp()) return;
    check();
    const timer = window.setInterval(check, EVERY_MS);
    return () => window.clearInterval(timer);
  }, [check]);

  return { stage, version, notes, error, progress, download, install, check };
}
