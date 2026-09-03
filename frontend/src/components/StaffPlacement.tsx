/**
 * Which shop somebody works in, what else they cover, and every move they made.
 *
 * The scoping in `branch_scope` narrows what a person sees once they have a
 * branch. Until this existed nothing could give them one, so it narrowed
 * nobody — which is the same as not having been written, and is the shape of
 * failure this codebase keeps producing: a capability that is complete,
 * correct, and unreachable.
 *
 * WHY THE HISTORY IS ON THE SCREEN AND NOT JUST IN THE TABLE
 *
 * Because the question it answers is asked by an inspector, out loud, in the
 * shop: who was working here on the fourteenth. A column that has been
 * overwritten four times cannot answer it, and a history nobody can read
 * cannot either.
 */
import { useCallback, useEffect, useState } from "react";
import { api, errorText, fmtDate } from "../api";
import { Panel } from "./RecordPage";
import { Highlights } from "./record";
import BusyButton from "./BusyButton";
import { useConfirm } from "./Confirm";
import { useToast } from "./Toast";
import { useSession } from "../session";
import { closeThenSave } from "../hooks/useOptimisticList";

interface BranchRow { id: number; name: string; code: string }

interface Cover {
  branch_id: number;
  branch: string;
  until: string | null;
  expired: boolean;
  reason: string;
  added_by: string;
}

interface Move {
  id: number;
  from: string | null;
  to: string | null;
  on: string | null;
  reason: string;
  by: string;
}

interface Placement {
  branch: BranchRow | null;
  all_branches: boolean;
  /** What they can actually see, said in words, so nobody has to infer it. */
  sees: string;
  cover: Cover[];
  moves: Move[];
}

export default function StaffPlacement({ userId, name, onChanged }: {
  userId: number;
  name: string;
  onChanged?: () => void;
}) {
  const session = useSession();
  // Optimistic until the server says otherwise.
  //
  // `can()` is false while the session is still loading, so gating the fetch on
  // it meant this panel was absent for as long as that took — tens of seconds
  // on a cold server, and permanently if the read failed. An administrator
  // reads that as the feature having been removed.
  //
  // The endpoint behind it requires staff.manage, so asking is safe: somebody
  // who may not gets a 403, the catch leaves this empty, and nothing renders.
  // The same outcome, reached by asking instead of by assuming the worst.
  const may = !session.known || session.can("staff.manage");
  const toast = useToast();
  const confirm = useConfirm();

  const [p, setP] = useState<Placement | null>(null);
  const [branches, setBranches] = useState<BranchRow[]>([]);
  const [moving, setMoving] = useState(false);
  const [covering, setCovering] = useState(false);
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [until, setUntil] = useState("");

  const load = useCallback(() => {
    if (!may) return;
    api.get<Placement>(`/api/auth/users/${userId}/placement`)
      .then(setP)
      .catch(() => setP(null));
  }, [userId, may]);

  useEffect(load, [load]);
  useEffect(() => {
    if (!may) return;
    api.get<BranchRow[] | { items: BranchRow[] }>("/api/branches")
      .then((d) => setBranches(Array.isArray(d) ? d : d.items ?? []))
      .catch(() => setBranches([]));
  }, [may]);

  // Somebody who definitely may not has no business reading the transfer
  // history either: it says where every member of staff has worked, which in
  // a small group is a personnel record.
  if (session.known && !session.can("staff.manage")) return null;

  async function move() {
    const id = target ? Number(target) : null;
    await closeThenSave(
      () => { setMoving(false); setTarget(""); setReason(""); },
      () => api.post<Placement>(`/api/auth/users/${userId}/placement`,
                                { branch_id: id, reason }),
      {
        ok: (fresh) => fresh.branch
          ? `${name} now works at ${fresh.branch.name}.`
          : `${name} is no longer tied to a branch and sees every shop.`,
        failed: "That move could not be recorded. Nothing was changed",
        toast,
        after: (fresh) => { setP(fresh); onChanged?.(); session.refresh(); },
      },
    );
  }

  async function cover() {
    const id = Number(target);
    if (!id) return;
    await closeThenSave(
      () => { setCovering(false); setTarget(""); setReason(""); setUntil(""); },
      () => api.post<Placement>(`/api/auth/users/${userId}/cover`, {
        branch_id: id, reason, until: until || null,
      }),
      {
        ok: "Cover added.",
        failed: "That cover could not be added. Nothing was changed",
        toast,
        after: (fresh) => { setP(fresh); onChanged?.(); },
      },
    );
  }

  async function dropCover(row: Cover) {
    const ok = await confirm({
      title: `Stop ${name} covering ${row.branch}?`,
      body: (
        <p>
          They keep their own branch. {row.branch}'s trade stops appearing on
          their screens.
        </p>
      ),
      confirmLabel: "Stop the cover",
    });
    if (!ok) return;
    try {
      const fresh = await api.delete<Placement>(
        `/api/auth/users/${userId}/cover/${row.branch_id}`);
      setP(fresh);
      onChanged?.();
      toast.ok(`${row.branch} cover ended.`);
    } catch (e) {
      toast.error(errorText(e, "That cover could not be ended."));
    }
  }

  async function toggleReach() {
    if (!p) return;
    const widening = !p.all_branches;
    const ok = await confirm({
      title: widening
        ? `Let ${name} see every branch?`
        : `Limit ${name} to their own branch?`,
      body: widening ? (
        <p>
          Every figure on every screen becomes the group's rather than one
          shop's: the takings, the stock on hand, the cash-ups. For an owner or
          a bookkeeper that is the point. For a dispenser it is three quarters
          of a screen they cannot act on.
        </p>
      ) : (
        <p>
          They will see {p.branch ? p.branch.name : "their own branch"} only.
        </p>
      ),
      confirmLabel: widening ? "Show the whole group" : "Limit to one branch",
    });
    if (!ok) return;
    try {
      const fresh = await api.post<Placement>(
        `/api/auth/users/${userId}/reach`, { all_branches: widening });
      setP(fresh);
      onChanged?.();
      session.refresh();
      toast.ok(widening ? `${name} now sees every branch.`
                        : `${name} is limited to their own branch.`);
    } catch (e) {
      toast.error(errorText(e, "That could not be changed."));
    }
  }

  const others = branches.filter((b) => b.id !== p?.branch?.id);

  return (
    <Panel
      title="Where they work"
      aside={
        <div className="row-actions">
          <button className="btn" onClick={() => { setMoving(true); setCovering(false); }}>
            {p?.branch ? "Transfer" : "Place in a branch"}
          </button>
          <button className="btn" onClick={() => { setCovering(true); setMoving(false); }}>
            Add cover
          </button>
          <button className="btn" onClick={toggleReach}>
            {p?.all_branches ? "Limit to one branch" : "Show every branch"}
          </button>
        </div>
      }
    >
      {p && (
        <>
          {/* The resolved answer, in words, beside the branch itself. Three
              fields decide what somebody sees — the home branch, the cover
              rows and the group flag — and an administrator should not have to
              combine them in their head to know what they have just done. */}
          <Highlights items={[
            {
              label: "Branch",
              value: p.branch
                ? <span className="branch-chip">{p.branch.name}</span>
                : <span className="muted">Not placed</span>,
            },
            { label: "Sees", value: p.sees },
            {
              label: "Covers",
              value: p.cover.filter((c) => !c.expired).length || "—",
              hint: p.all_branches ? "group-wide sight" : undefined,
            },
          ]} />

          {!p.branch && !p.all_branches && (
            <p className="hint">
              Nobody has placed {name} in a shop, so they see every branch's
              trade. That is how every account worked before branches were
              tracked, and it is kept that way on purpose rather than emptying
              their screens. Placing them narrows it.
            </p>
          )}

          {moving && (
            <form className="form-row" onSubmit={(e) => { e.preventDefault(); move(); }}>
              <label className="field">
                Move to
                <select value={target} onChange={(e) => setTarget(e.target.value)}>
                  <option value="">No branch (sees every shop)</option>
                  {others.map((b) => (
                    <option key={b.id} value={b.id}>{b.name}</option>
                  ))}
                </select>
              </label>
              <label className="field span-4">
                Why
                <input value={reason} onChange={(e) => setReason(e.target.value)}
                       placeholder="Promoted, covering a resignation, opening a new shop" />
              </label>
              <BusyButton className="btn primary" onClick={move} busyLabel="Moving…">
                Record the move
              </BusyButton>
              <button type="button" className="btn" onClick={() => setMoving(false)}>
                Cancel
              </button>
            </form>
          )}

          {covering && (
            <form className="form-row" onSubmit={(e) => { e.preventDefault(); cover(); }}>
              <label className="field">
                Also covers
                <select value={target} onChange={(e) => setTarget(e.target.value)}>
                  <option value="">Choose a branch…</option>
                  {others.map((b) => (
                    <option key={b.id} value={b.id}>{b.name}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                Until
                {/* Blank is a standing arrangement. A locum's cover should
                    carry its own end date, because authority that ends when
                    somebody remembers to remove it does not end. */}
                <input type="date" value={until}
                       onChange={(e) => setUntil(e.target.value)} />
              </label>
              <label className="field span-4">
                Why
                <input value={reason} onChange={(e) => setReason(e.target.value)}
                       placeholder="Thursday relief, maternity cover" />
              </label>
              <BusyButton className="btn primary" onClick={cover} busyLabel="Adding…">
                Add the cover
              </BusyButton>
              <button type="button" className="btn" onClick={() => setCovering(false)}>
                Cancel
              </button>
            </form>
          )}

          {p.cover.length > 0 && (
            <div className="dt-scroll">
              <table className="dt">
                <caption className="sr-only">Branches this person also covers</caption>
                <thead>
                  <tr>
                    <th>Also covers</th><th>Until</th><th>Why</th>
                    <th>Added by</th><th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {p.cover.map((row) => (
                    <tr key={row.branch_id} className={row.expired ? "is-muted" : undefined}>
                      <td>{row.branch}</td>
                      <td>
                        {row.until ? fmtDate(row.until) : <span className="muted">Standing</span>}
                        {row.expired && <span className="badge warn">Ended</span>}
                      </td>
                      <td>{row.reason || <span className="muted">—</span>}</td>
                      <td>{row.added_by || <span className="muted">—</span>}</td>
                      <td className="row-actions">
                        <button className="linkish" onClick={() => dropCover(row)}>
                          Stop
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {p.moves.length > 0 && (
            <div className="dt-scroll" style={{ maxHeight: "30vh" }}>
              <table className="dt">
                <caption className="sr-only">Every branch this person has worked in</caption>
                <thead>
                  <tr><th>Moved</th><th>From</th><th>To</th><th>Why</th><th>By</th></tr>
                </thead>
                <tbody>
                  {p.moves.map((m) => (
                    <tr key={m.id}>
                      <td>{m.on ? fmtDate(m.on) : "—"}</td>
                      <td>{m.from ?? <span className="muted">Not placed</span>}</td>
                      <td>{m.to ?? <span className="muted">No branch</span>}</td>
                      <td>{m.reason || <span className="muted">—</span>}</td>
                      <td>{m.by || <span className="muted">—</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </Panel>
  );
}
