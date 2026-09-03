/**
 * Who is signed in, what they may do, and which shop they are standing in.
 *
 * One fetch of `/api/auth/me`, held once, read everywhere. Layout was fetching
 * it for the avatar in the corner and nothing else knew it existed, so every
 * screen showed every button to everybody and the server refused the ones it
 * had to.
 *
 * THE CLIENT NEVER WORKS OUT AN ANSWER
 *
 * `can` reads a boolean the server resolved. It does not know that a manager
 * may void a sale, and it must not learn: the rule has role defaults, grants by
 * name, denials that beat grants, ceilings, hours, days and expiry, and a
 * second implementation of that in TypeScript would drift from the first
 * within a month.
 *
 * The way that drift presents is specific and bad. A button that is visible,
 * enabled, and then refused teaches people the software is unreliable rather
 * than that they lack the authority — and the fix they reach for is somebody
 * else's password.
 *
 * So: hiding is a courtesy, the server is the rule. A screen that hides a
 * button it should have shown is a bug report. A screen that shows one the
 * server will refuse is an argument at a counter.
 */
import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
  type ReactNode,
} from "react";
import { api } from "./api";

export interface BranchBrief {
  id: number;
  name: string;
  code: string;
}

export interface Me {
  id: number;
  username: string;
  full_name: string;
  role: string;
  is_demo?: boolean;
  demo_expires_at?: string | null;
  /** capability key -> may they. Resolved by the server. */
  can: Record<string, boolean>;
  /** The shops this person may see. */
  branches: BranchBrief[];
  /** Where they work, of those. Null for head office and the unplaced. */
  branch: BranchBrief | null;
  /** True for the owner, head office, and anybody nobody has placed yet. */
  all_branches: boolean;
}

interface SessionValue {
  me: Me | null;
  /** Still fetching. Distinct from "fetched, and they may do nothing". */
  loading: boolean;
  /** May they do this? False while loading, which hides rather than flashes. */
  can: (capability: string) => boolean;
  /** Their role, or "" before the fetch lands. */
  role: string;
  /** Re-read after something changes what they may do. */
  refresh: () => void;
}

const Ctx = createContext<SessionValue>({
  me: null, loading: true, can: () => false, role: "", refresh: () => {},
});

export function SessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    api.get<Me>("/api/auth/me")
      .then((data) => setMe(data))
      // A failed read leaves `me` null, which reads as "may do nothing" and
      // hides the controls. Deliberate: the alternative is showing everything
      // to somebody whose session we could not confirm.
      .catch(() => setMe(null))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const value = useMemo<SessionValue>(() => ({
    me,
    loading,
    can: (capability: string) => Boolean(me?.can?.[capability]),
    role: me?.role ?? "",
    refresh: load,
  }), [me, loading, load]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): SessionValue {
  return useContext(Ctx);
}

/** `useCan("sale.void")` — may the signed-in person void a sale? */
export function useCan(capability: string): boolean {
  return useContext(Ctx).can(capability);
}

/**
 * Render children only if the person may do the thing.
 *
 *   <Can do="sale.void"><button>Void</button></Can>
 *
 * `otherwise` puts something in its place where the gap would be confusing —
 * a disabled control with a title saying who to ask is often kinder than a
 * button that was never there, because somebody who has used the software
 * elsewhere will look for it.
 */
export function Can({ do: capability, children, otherwise = null }: {
  do: string;
  children: ReactNode;
  otherwise?: ReactNode;
}) {
  return useCan(capability) ? <>{children}</> : <>{otherwise}</>;
}
