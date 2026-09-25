/** Head office: the estate on a map, and the controls a group needs.
 *
 *  Twelve branches in a list is a list. On a map it is a business — where the
 *  takings are, which shop has gone quiet this week, and which two sit close
 *  enough to share stock rather than each order it.
 *
 *  Three things here that a single shop never thinks about and a group cannot
 *  run without:
 *
 *  **Freezing a branch.** Under investigation, mid stock-take, or a manager has
 *  walked out with the keys. Head office needs the shop to stop moving money
 *  without waiting for anybody there to agree, and reading deliberately stays
 *  open, because a branch that cannot check an allergy will work around the
 *  freeze on paper, where nobody can see it at all.
 *
 *  **Acting as somebody.** "It does not work on my screen" is unanswerable from
 *  head office, and the alternative is asking a branch for their password. The
 *  session is short and declares itself, and every row written while it lasts
 *  carries both names.
 *
 *  **Authority, bounded.** "May void a sale" is not how anybody delegates. It
 *  is "may void a sale under twenty dollars, at this branch, until the locum
 *  leaves, and anything larger needs me."
 */
import { useCallback, useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { Snowflake, Warning } from "@phosphor-icons/react";
import { api, errorText, money } from "../api";
import BusyButton from "../components/BusyButton";
import PageTabs, { TabDef, TabStrip, usePageTabs } from "../components/PageTabs";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import { useAsk, useConfirm } from "../components/Confirm";
import { CANCELLED, useStepUp } from "../components/StepUp";
import { useToast } from "../components/Toast";
import HqPermissions from "../components/HqPermissions";
import RoleMatrix from "../components/RoleMatrix";
import EstateStock from "../components/EstateStock";
import PageHead from "../components/PageHead";
import Th from "../components/Th";

interface BranchRow {
  branch_id: number; branch: string; code: string; city: string;
  address: string; phone: string;
  latitude: number | null; longitude: number | null; pinned: boolean;
  frozen: boolean; frozen_reason: string; frozen_by: string;
  taken: number; sales: number; previous: number; change: number | null;
}
interface PinReport {
  staff: number; with_pin: number;
  without_pin: { id: number; full_name: string; username: string;
                 role: string; signs_controlled: boolean }[];
  locked_out: { id: number; full_name: string; until: string }[];
  says: string;
}
interface Directory {
  types: { user_type: string; what: string; signs_in_with: string;
           reaches: string; needs_pin: boolean }[];
  users: Record<string, { id: number; full_name: string; username: string;
                          role: string; active: boolean; has_pin: boolean }[]>;
  counts: Record<string, number>;
  patients_with_portal_access: number;
  note: string;
}
interface Estate {
  days: number; branches: BranchRow[]; total: number;
  unpinned: string[]; frozen: string[]; quiet: string[]; headline: string;
}

type Tab = "map" | "stock" | "people" | "authority" | "logins";

export default function HeadOffice() {
  const [estate, setEstate] = useState<Estate | null>(null);
  const [days, setDays] = useState(1);
  const [loading, setLoading] = useState(true);
  const [pins, setPins] = useState<PinReport | null>(null);
  const [types, setTypes] = useState<Directory | null>(null);
  const toast = useToast();
  const confirm = useConfirm();
  const ask = useAsk();
  // Only so the tab can carry a count. The tab's own screen loads its own.
  const [transit, setTransit] = useState<unknown[] | null>(null);
  useEffect(() => {
    api.get<unknown[]>("/api/branches/transfers/in-transit")
      .then(setTransit).catch(() => setTransit([]));
  }, []);

  const TABS: TabDef<Tab>[] = [
    { key: "map", label: "The estate", count: estate?.branches.length,
      hint: "Where the shops are and what they have taken" },
    // Beside the estate rather than under administration: moving stock
    // between shops is a daily operational decision for a group, and the
    // question it answers, who has this and who needs it, can only be asked
    // from a screen that can see every branch at once.
    { key: "stock", label: "Stock across the estate",
      count: transit?.length || undefined,
      hint: "Move stock between branches, and what is on the road" },
    { key: "people", label: "Branches & people",
      hint: "Who works where, and what each may do" },
    { key: "authority", label: "Authority",
      hint: "What each role may do, and what one person may do on top of it" },
    { key: "logins", label: "Who signs in", count: pins?.without_pin.length,
      hint: "The three kinds of login, and who cannot sign in their own name" },
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "map");

  const load = useCallback(() => {
    setLoading(true);
    api.get<PinReport>("/api/hq/pins").then(setPins).catch(() => undefined);
    api.get<Directory>("/api/hq/user-types").then(setTypes).catch(() => undefined);
    api.get<Estate>(`/api/hq/overview?days=${days}`)
      .then(setEstate)
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
  }, [days]);
  useEffect(load, [load]);

  async function freeze(b: BranchRow) {
    const answer = await ask({
      title: `Stop ${b.branch} trading?`,
      body: (
        <>
          <p>
            Nobody there will be able to take a sale, dispense, move stock or
            cash up until it is released.
          </p>
          <p className="muted">
            Reading stays open. A branch that cannot check an allergy works
            around the freeze on paper, where head office cannot see it at all.
          </p>
        </>
      ),
      field: "Why",
      placeholder: "Stock take, investigation, keys not returned",
      required: true,
      confirmLabel: "Freeze it",
      destructive: true,
    });
    if (!answer.ok) return;
    try {
      const r = await api.post<{ message: string }>(
        `/api/hq/branches/${b.branch_id}/freeze`, { reason: answer.value });
      toast.ok(r.message);
      load();
    } catch (e) {
      toast.error(errorText(e));
    }
  }

  async function unfreeze(b: BranchRow) {
    const ok = await confirm({
      title: `Let ${b.branch} trade again?`,
      body: b.frozen_reason
        ? `It was stopped for: ${b.frozen_reason}`
        : undefined,
      confirmLabel: "Release it",
    });
    if (!ok) return;
    try {
      const r = await api.post<{ message: string }>(
        `/api/hq/branches/${b.branch_id}/unfreeze`, {});
      toast.ok(r.message);
      load();
    } catch (e) {
      toast.error(errorText(e));
    }
  }

  async function pin(b: BranchRow) {
    const answer = await ask({
      title: `Where is ${b.branch}?`,
      body: "Latitude and longitude, comma separated. The pair you get from "
          + "dropping a pin in any maps application. Harare's centre is about "
          + "-17.83, 31.05.",
      field: "Latitude, longitude",
      placeholder: "-17.8252, 31.0335",
      required: true,
      confirmLabel: "Pin it",
    });
    if (!answer.ok) return;
    const [lat, lng] = answer.value.split(",").map((n) => Number(n.trim()));
    try {
      const r = await api.put<{ message: string }>(
        `/api/hq/branches/${b.branch_id}/location`,
        { latitude: lat, longitude: lng });
      toast.ok(r.message);
      load();
    } catch (e) {
      // The server refuses a pair outside sane bounds and says the usual cause
      // is the two the wrong way round. Shown as written.
      toast.error(errorText(e));
    }
  }

  return (
    <div className="page">
      <PageHead title="Head office" sub={estate?.headline ?? "The estate, and the controls above it."} />

      <PageTabs tabs={TABS} tab={tab} setTab={setTab} />

      <Refreshable loading={loading} hasData={!!estate}
        skeleton={<TableSkeleton cols={5} rows={5} />}>
        {estate && tab === "map" && (
          <>
            {estate.frozen.length > 0 && (
              <div className="alert error">
                <Snowflake size={16} weight="fill" />{" "}
                <b>{estate.frozen.join(", ")}</b>{" "}
                {estate.frozen.length === 1 ? "is" : "are"} frozen and
                recording nothing.
              </div>
            )}
            {estate.quiet.length > 0 && (
              <div className="alert warn">
                <Warning size={16} weight="fill" />{" "}
                <b>{estate.quiet.join(", ")}</b> down more than a quarter on the
                period before. Measured against each branch's own normal, not
                against the biggest shop in the group.
              </div>
            )}

            <div className="wc-bands">
              <div className="wl-stat">
                <b>{money(estate.total)}</b>
                <span>Taken across the estate</span>
              </div>
              <div className="wl-stat">
                <b>{estate.branches.length}</b><span>Branches</span>
              </div>
              <div className={`wl-stat${estate.unpinned.length ? " wc-stale" : ""}`}>
                <b>{estate.unpinned.length}</b><span>Not on the map yet</span>
              </div>
            </div>

            <EstateMap branches={estate.branches} />

            <div className="dt-scroll">
              <table className="dt">
                <thead>
                  <tr>
                    <Th className="col-name">Branch</Th><Th className="num">Taken</Th>
                    <Th className="num">Sales</Th>
                    <Th className="num">On the period before</Th>
                    <Th>Standing</Th><th className="actions" />
                  </tr>
                </thead>
                <tbody>
                  {estate.branches.map((b) => (
                    <tr key={b.branch_id}
                        className={b.frozen ? "row-danger" : undefined}>
                      <td>
                        <b>{b.branch}</b>
                        <div className="muted small">
                          {b.city || b.code}
                          {!b.pinned && " · not pinned"}
                        </div>
                      </td>
                      <td className="num mono">{money(b.taken)}</td>
                      <td className="num">{b.sales}</td>
                      <td className="num">
                        {b.change === null ? <span className="muted">None</span> : (
                          <b className={b.change <= -25 ? "tone-danger"
                            : b.change > 0 ? "tone-ok" : undefined}>
                            {b.change > 0 ? "+" : ""}{b.change}%
                          </b>
                        )}
                      </td>
                      <td>
                        {b.frozen ? (
                          <>
                            <span className="badge bad">Frozen</span>
                            <div className="muted small wrap">
                              {b.frozen_reason}
                              {b.frozen_by && ` · ${b.frozen_by}`}
                            </div>
                          </>
                        ) : <span className="badge ok">Trading</span>}
                      </td>
                      <td className="actions">
                        {b.frozen
                          ? <BusyButton className="btn primary sm"
                              onClick={() => unfreeze(b)} busyLabel="Releasing…">
                              Release
                            </BusyButton>
                          : <BusyButton className="btn ghost sm"
                              onClick={() => freeze(b)} busyLabel="Freezing…">
                              Freeze
                            </BusyButton>}
                        {!b.pinned && (
                          <button className="btn ghost sm" onClick={() => pin(b)}>
                            Pin
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {tab === "stock" && <EstateStock />}
        {estate && tab === "people" && <BranchPeople branches={estate.branches} />}
        {/* The floor, then the ceiling, in that reading order. What a role
            gets by default is the thing to settle first; what one named person
            gets on top of it. With a limit, a set of hours, an end date. Only
            makes sense once you can see what they already had. */}
        {tab === "authority" && <RoleMatrix />}
        {tab === "authority" && <HqPermissions />}
        {tab === "logins" && <WhoSignsIn pins={pins} types={types} />}
      </Refreshable>
    </div>
  );
}

/** The estate, drawn.
 *
 *  A branch with no coordinates is left OFF rather than placed at nought
 *  degrees, which is a spot in the Gulf of Guinea — a map that quietly invents
 *  a location is worse than one that admits it does not know.
 */
function EstateMap({ branches }: { branches: BranchRow[] }) {
  const holder = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);

  useEffect(() => {
    if (!holder.current || map.current) return;
    const m = L.map(holder.current, { zoomControl: true });
    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
      { maxZoom: 19, attribution: "&copy; OpenStreetMap &copy; CARTO" }).addTo(m);
    layer.current = L.layerGroup().addTo(m);
    map.current = m;
    // Harare, until there is something to fit to.
    m.setView([-17.8252, 31.0335], 11);
    return () => { m.remove(); map.current = null; layer.current = null; };
  }, []);

  useEffect(() => {
    const group = layer.current;
    const m = map.current;
    if (!group || !m) return;
    group.clearLayers();

    const pinned = branches.filter((b) => b.pinned);
    if (!pinned.length) return;

    const most = Math.max(...pinned.map((b) => b.taken), 1);
    for (const b of pinned) {
      // Sized by what it took, so the map reads as a business rather than as a
      // set of addresses. Square-rooted, or one big shop makes every other
      // branch invisible.
      const radius = 8 + 22 * Math.sqrt(Math.max(b.taken, 0) / most);
      L.circleMarker([b.latitude!, b.longitude!], {
        radius,
        color: b.frozen ? "#a8341f" : b.change !== null && b.change <= -25
          ? "#8a5a12" : "#2f6f3c",
        fillColor: b.frozen ? "#a8341f" : b.change !== null && b.change <= -25
          ? "#8a5a12" : "#2f6f3c",
        fillOpacity: 0.35, weight: 2,
      })
        .bindTooltip(
          `<b>${b.branch}</b><br>${b.taken.toLocaleString(undefined,
            { style: "currency", currency: "USD" })} · ${b.sales} sale(s)`
          + (b.frozen ? `<br><b>frozen</b>. ${b.frozen_reason}` : ""),
          { direction: "top" })
        .addTo(group);
    }
    m.fitBounds(L.latLngBounds(pinned.map(
      (b) => [b.latitude!, b.longitude!] as [number, number])).pad(0.25));
  }, [branches]);

  const unpinned = branches.filter((b) => !b.pinned);
  return (
    <div className="card">
      <div ref={holder} className="hq-map" />
      {unpinned.length > 0 && (
        <p className="muted small">
          {/* Named rather than silently absent. A branch missing from a map is
              indistinguishable from a branch that has closed. */}
          Not on the map: {unpinned.map((b) => b.branch).join(", ")}. Pin them
          from the table below and they appear here.
        </p>
      )}
    </div>
  );
}

/** Who works where, and what each of them may do. */
function BranchPeople({ branches }: { branches: BranchRow[] }) {
  const [open, setOpen] = useState<number | null>(
    branches[0]?.branch_id ?? null);
  const [people, setPeople] = useState<any | null>(null);
  const toast = useToast();
  const confirm = useConfirm();
  const { guarded, prompt: stepUpPrompt } = useStepUp();

  const load = useCallback(() => {
    if (!open) return;
    api.get<any>(`/api/hq/branches/${open}/people`)
      .then(setPeople)
      .catch((e) => toast.error(errorText(e)));
  }, [open]);

  useEffect(() => { setPeople(null); load(); }, [open, load]);

  /** Take somebody's till code away so they can set a new one.
   *
   *  The recovery path for a forgotten code, and the reason asking for the
   *  current code before changing one does not strand anybody. Clearing is all
   *  a manager can do: choosing somebody's code would mean an action carrying
   *  their name proved nothing, which is the whole point of having one.
   */
  async function clearCode(person: any) {
    const ok = await confirm({
      title: `Clear ${person.full_name}'s till code?`,
      body: "They set a new one themselves, with their password. Until they do, "
          + "their till will not lock and the authorisation prompts ask for "
          + "their password instead. You cannot choose a code for them.",
      confirmLabel: "Clear the code",
      destructive: true,
    });
    if (!ok) return;
    const done = await guarded(
      "user.manage",
      (token) => api.delete(`/api/auth/pin/${person.id}`, token),
      `Clear the till code for ${person.full_name}`,
    );
    if (done === CANCELLED) return;
    toast.ok(`${person.full_name} can set a new code now.`);
    load();
  }

  return (
    <>
      <TabStrip>
        {branches.map((b) => (
          <button key={b.branch_id}
            className={open === b.branch_id ? "active" : ""}
            onClick={() => setOpen(b.branch_id)}>
            {b.branch}{b.frozen ? " · frozen" : ""}
          </button>
        ))}
      </TabStrip>
      {!people ? <TableSkeleton cols={5} rows={6} rowHeight={62} />
       : !people.people.length ? (
        /* A branch with nobody in it drew a header and then nothing, which
           reads as a table that failed to load rather than a branch with no
           staff on it. */
        <div className="empty">
          <b>Nobody is assigned to {people.branch} yet.</b>
          <p>
            Staff are placed on a branch from their own record. Until somebody
            is, this branch has no one who can sign in at its till.
          </p>
        </div>
      ) : (
        <div className="dt-scroll">
          <table className="dt">
            <thead>
              <tr><Th>Person</Th><Th>Role</Th><Th>Till code</Th>
                <Th>Also allowed</Th><Th>Prevented from</Th></tr>
            </thead>
            <tbody>
              {people.people.map((p: any) => (
                <tr key={p.id} className={p.active ? undefined : "row-muted"}>
                  <td>
                    <b>{p.full_name}</b>
                    <div className="muted small mono">{p.username}</div>
                    {!p.active && (
                      <span className="badge muted">Login stopped</span>
                    )}
                  </td>
                  <td>{p.role}</td>
                  {/* Set or not, locked or not, and the one thing a manager
                      can do about it. Never the code itself: the whole feature
                      rests on nobody but the owner having known it. */}
                  <td className="hq-code">
                    {p.has_pin ? (
                      <>
                        <span className={`badge ${p.pin_locked_for ? "warn" : "ok"}`}>
                          {p.pin_locked_for
                            ? `locked ${Math.max(1, Math.round(p.pin_locked_for / 60))}m`
                            : "set"}
                        </span>
                        <button type="button" className="ghost small"
                                onClick={() => clearCode(p)}>
                          Clear
                        </button>
                      </>
                    ) : (
                      <span className="muted small">
                        none yet, they set their own
                      </span>
                    )}
                  </td>
                  <td className="muted small wrap">
                    {p.extra.length ? p.extra.join(", ") : "none"}
                  </td>
                  <td className="wrap">
                    {p.denied.length
                      ? <span className="badge bad">{p.denied.join(", ")}</span>
                      : <span className="muted">None</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {stepUpPrompt}
    </>
  );
}


/** The three doors into this pharmacy, and who cannot sign for their own work.
 *
 *  Staff were listable and the other two were not, so "who can reach this
 *  pharmacy's data" had no answer that included the patient holding a live
 *  portal link.
 *
 *  The PIN list underneath is the finding. A member of staff without one is not
 *  somebody who declined a convenience — every dispensing they check is
 *  recorded against whoever opened the till that morning, so the controlled
 *  register names the wrong person on every line they touched.
 */
function WhoSignsIn({ pins, types }: {
  pins: PinReport | null; types: Directory | null;
}) {
  if (!types) return <TableSkeleton cols={4} rows={5} />;
  return (
    <>
      <div className="dt-scroll">
        <table className="dt">
          <thead>
            <tr><Th>Kind</Th><Th className="num">How many</Th>
              <Th>How they prove it</Th><Th>What they reach</Th></tr>
          </thead>
          <tbody>
            {types.types.map((t) => (
              <tr key={t.user_type}>
                <td>
                  <b>{t.what}</b>
                  <div className="muted small mono">{t.user_type}</div>
                  {t.needs_pin && (
                    <span className="badge warn">Needs a till PIN</span>
                  )}
                </td>
                <td className="num">
                  {t.user_type === "patient"
                    ? types.patients_with_portal_access.toLocaleString()
                    : (types.counts[t.user_type] ?? 0)}
                </td>
                <td className="wrap muted small">{t.signs_in_with}</td>
                <td className="wrap muted small">{t.reaches}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">{types.note}</p>

      {pins && (
        <>
          <h4 className="cu-section">Signing in their own name</h4>
          <div className={`alert ${pins.without_pin.length ? "warn" : ""}`}>
            <Warning size={16} weight="fill" /> <span>{pins.says}</span>
          </div>
          {pins.without_pin.length > 0 && (
            <div className="dt-scroll">
              <table className="dt">
                <thead>
                  <tr><Th>Nobody can tell it was them</Th><Th>Role</Th>
                    <Th>Why it matters</Th></tr>
                </thead>
                <tbody>
                  {pins.without_pin.map((u) => (
                    <tr key={u.id}
                        className={u.signs_controlled ? "row-flag" : undefined}>
                      <td>
                        <b>{u.full_name}</b>
                        <div className="muted small mono">{u.username}</div>
                      </td>
                      <td>{u.role}</td>
                      <td className="wrap muted small">
                        {u.signs_controlled
                          ? "They sign for controlled medicines. Without a PIN "
                            + "the register names whoever opened the till."
                          : "Their work is recorded against whoever opened the "
                            + "till that morning."}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="hint">
            A PIN is set by the person themselves, in their own profile. Head
            office cannot set it for them, because a PIN somebody else chose is
            a PIN two people know, and the whole point is that it identifies
            one.
          </p>
        </>
      )}
    </>
  );
}
