import {
  ChartBar,
  ClockCounterClockwise,
  ArrowsClockwise,
  ArrowsLeftRight,
  Bag,
  BellRinging,
  Buildings,
  CalendarCheck,
  CaretDown,
  CaretLeft,
  CaretRight,
  ChartLineUp,
  ClipboardText,
  ClockCountdown,
  Coins,
  Desktop,
  Flask,
  Funnel,
  Gear,
  HandCoins,
  Gift,
  Headset,
  Megaphone,
  Notebook,
  Package,
  PaperPlaneTilt,
  Prescription,
  Presentation,
  Receipt,
  Scales,
  SignOut,
  Siren,
  SlidersHorizontal,
  SquaresFour,
  Storefront,
  Truck,
  UserCircle,
  UserPlus,
  Users,
  Van,
  Vault,
  IdentificationCard,
  Basket,
  SealCheck,
  TrendUp,
} from "@phosphor-icons/react";
import React, { ReactNode, useEffect, useRef, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { api, configureLocale, fmtDateTime, setToken } from "../api";
import { User } from "../types";
import { readStored, writeStored } from "../storage";
import { shortCount, useNavCounts } from "../hooks/useNavCounts";
import { useRailWidth } from "../hooks/useRailWidth";
import DemoBar from "./DemoBar";
import ThemeToggle from "./ThemeToggle";
import Tooltips from "./Tooltips";
import TillLock from "./TillLock";
import ClaudeIcon from "./ClaudeIcon";

/** The navigation, ordered by how often a pharmacy actually touches each screen.
 *
 *  Two gradings are at work, and they are deliberate rather than cosmetic.
 *
 *  Sections descend by aggregate frequency: the dispensary is opened hundreds of
 *  times a day, the control panel perhaps monthly. Inside each section the same
 *  rule applies again, so the item a dispenser reaches for most is nearest the
 *  top of its group and the muscle memory that develops is the right one.
 *
 *  `tier: 1` marks the handful of screens someone lives in all day. They carry
 *  slightly more visual weight, so the eye lands on them without having to read
 *  the list. Everything else is even, because a sidebar where nine things shout
 *  is a sidebar where nothing does.
 *
 *  The previous grouping had grown a "Clinical" section holding the ledger, the
 *  trading periods and the station settings — a dumping ground rather than a
 *  category. Those belong to finance and administration, and are filed there.
 */
/** Two letters for the avatar. A single-word name still gets one rather than
 *  falling through to an empty circle. */
function initials(name?: string | null): string {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
}

/** A navigation entry. Stated rather than inferred: the icons are a mix of
 *  Phosphor components and our own Claude mark, and left to inference the array
 *  collapses into a union where `tier` exists on only some members. */
interface NavLinkDef {
  to: string;
  label: string;
  // A component, without pinning its props. Phosphor types `weight` as its own
  // union and returns ReactNode; our Claude mark takes a plain string and
  // returns an Element. Narrowing to either shape excludes the other, and the
  // nav only ever passes a size and a weight through.
  icon: React.ComponentType<any>;
  tier?: number;
}

const NAV: { section: string; links: NavLinkDef[] }[] = [
  {
    section: "Dispensary",
    links: [
      { to: "/dispense", label: "Dispensary", icon: Prescription, tier: 1 },
      { to: "/patients", label: "Patients", icon: Users, tier: 1 },
      { to: "/to-follows", label: "To follows", icon: ClockCountdown },
      { to: "/will-call", label: "Will call", icon: Bag },
      // What has already gone out, as against what is still to go. A
      // dispensary is asked about yesterday several times a day.
      { to: "/dispensing-history", label: "Dispensing history", icon: ClockCounterClockwise },
      // Scripts by their number. The history above lists dispensings —
      // the events — so a script supplied over four visits appears four
      // times there and one never dispensed appears not at all.
      { to: "/scripts", label: "Scripts", icon: Prescription },
      { to: "/repeats", label: "Repeats", icon: ArrowsClockwise },
      { to: "/compounding", label: "Compounding", icon: Flask },
      { to: "/register", label: "Controlled Register", icon: Notebook },
      { to: "/deliveries", label: "Deliveries", icon: Van },
      { to: "/drivers", label: "Drivers", icon: IdentificationCard },
      { to: "/reminders", label: "Patient Adherence", icon: BellRinging },
    ],
  },
  {
    section: "Front Shop",
    links: [
      { to: "/pos", label: "Till", icon: Storefront, tier: 1 },
      { to: "/shifts", label: "Cash Office", icon: Vault },
      // Opening and closing the fiscal day is a daily counter act, not an admin
      // setting, so it sits with the till rather than in the control panel.
      { to: "/fiscal", label: "Fiscalisation", icon: Receipt },
      { to: "/laybys", label: "Lay-bys", icon: HandCoins },
      // Medicine that has gone out unpaid for. Beside the lay-bys
      // because both are money the shop is waiting on.
      { to: "/money-owed", label: "Money owed", icon: Coins },
    ],
  },
  {
    section: "Stock",
    links: [
      { to: "/stock", label: "Inventory", icon: Package },
      { to: "/stock-categories", label: "Departments", icon: ChartBar },
      // What each line earns against the money it ties up. The buying
      // conversation, which units sold alone cannot have.
      { to: "/stock-performance", label: "Stock performance", icon: TrendUp },
      { to: "/orders", label: "Procurement", icon: Truck },
      { to: "/stock-take", label: "Stock Take", icon: ClipboardText },
      { to: "/samples", label: "Samples", icon: Gift },
      { to: "/recall", label: "Recall", icon: Siren },
      { to: "/branches", label: "Branches", icon: Storefront },
      // The paper a branch trades on, and when it dies. Three of these
      // lapsing closes the shop.
      { to: "/compliance", label: "Licences", icon: SealCheck },
    ],
  },
  {
    section: "Accounts",
    links: [
      // Batching and sending claims is the weekly round; "Claims held" is the
      // exception queue for ones that could not go. Sending comes first.
      // Claiming calendar, Authorisations and Claims held used to be three
      // more entries here. They are things you do from inside claiming, not
      // siblings of it, and in a list of fifty everything looks equally
      // important. They are tabs across the top of the claiming pages now.
      { to: "/claiming", label: "Claiming", icon: PaperPlaneTilt },
      // When each funder wants its claims and when it pays. A cut-off
      // missed costs a whole cycle, so it belongs beside the claiming.
      { to: "/remittances", label: "Remittances", icon: Coins },
      // Everything with two records of one fact: card, bank, claims, cash,
      // stock, and money out with drivers. They were in five places.
      { to: "/reconciliation", label: "Reconciliation", icon: ArrowsLeftRight },
      // Creditors sit beside the ledger rather than under Stock:
      // procurement is about getting the goods, this is about what is owed
      // for them, and the person who reads it is doing the books.
      { to: "/payables", label: "Creditors", icon: Receipt },
      { to: "/ledger", label: "Ledger", icon: Scales },
      { to: "/periods", label: "Periods", icon: CalendarCheck },
    ],
  },
  {
    section: "Insight",
    links: [
      { to: "/", label: "Command Centre", icon: SquaresFour },
      // The owner's view: which shop is working and which is quietly not.
      // It was filed under Stock, between the stock take and the recall,
      // because it reads branch data — but the question it answers is not a
      // stock question and the person asking it is not doing stock. Somebody
      // who owns three shops looks for this beside the analytics, which is
      // where every other "how are we doing" screen already lives.
      { to: "/scorecard", label: "Branch performance", icon: ChartBar, tier: 1 },
      { to: "/reports", label: "Analytics", icon: ChartLineUp },
      // What a repeat patient is worth beyond the line, and what to have
      // on the shelf before the month that sells it.
      { to: "/seasons", label: "Basket & seasons", icon: Basket },
      { to: "/assistant", label: "Pulse AI", icon: ClaudeIcon },
    ],
  },
  {
    section: "Business",
    links: [
      { to: "/helpdesk", label: "Cases", icon: Headset },
      { to: "/accounts", label: "Key Accounts", icon: Buildings },
      { to: "/leads", label: "Leads", icon: UserPlus },
      { to: "/pipeline", label: "Opportunities", icon: Funnel },
      { to: "/marketing", label: "Campaigns", icon: Megaphone },
      { to: "/crm-reports", label: "Revenue Intelligence", icon: Presentation },
    ],
  },
  {
    section: "Administration",
    links: [
      { to: "/admin", label: "Control Panel", icon: SlidersHorizontal },
      { to: "/system", label: "This Till", icon: Desktop },
      // Platform-level: creating pharmacies and deciding who belongs to which.
      // A pharmacy's own administrator gets a 403 and the page explains why, so
      // it sits in Administration rather than under Stock, where it had no
      // business being at all.
      // The estate, and the controls above it: freezing a branch, acting
      // as somebody, and bounded authority.
      { to: "/head-office", label: "Head office", icon: Buildings },
      { to: "/pharmacies", label: "Pharmacies", icon: Buildings },
    ],
  },
];

export default function Layout({ children }: { children: ReactNode }) {
  // Live counts of what needs doing, keyed by route.
  const counts = useNavCounts();
  const [user, setUser] = useState<User | null>(null);
  const [, setReady] = useState(0);
  const navigate = useNavigate();

  // Ask the API whether it is running the code that is on disk. A server left
  // running while the code moves on answers every request happily with
  // yesterday's behaviour, and the symptom is a 404 on an endpoint that plainly
  // exists — which has cost five separate diagnoses here, and once left
  // production serving an API three days older than this front end.
  const [staleApi, setStaleApi] = useState<{ started?: string; written?: string } | null>(null);
  useEffect(() => {
    api.get<{ running_stale_code?: boolean; process_started_at?: string; code_written_at?: string }>(
      "/api/health")
      .then((h) => {
        if (h.running_stale_code) {
          setStaleApi({ started: h.process_started_at, written: h.code_written_at });
        } else if (h.running_stale_code === undefined) {
          // The field is missing, which means the server predates the check
          // itself — so it is older than a version that already knew how to say
          // it was old. The first version of this banner stayed silent in exactly
          // that case, which is the one where it is most needed: a server old
          // enough to lack the field is old enough to be missing endpoints.
          setStaleApi({});
        }
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    api.get<User>("/api/auth/me").then(setUser).catch(() => {});
    // Currency and locale follow the installation's jurisdiction pack.
    api.get<{ locale: string; base_currency: { symbol: string; decimals: number } }>("/api/jurisdiction")
      .then((j) => {
        configureLocale({
          locale: j.locale,
          symbol: j.base_currency.symbol,
          decimals: j.base_currency.decimals,
        });
        setReady((n) => n + 1);   // re-render once formatting is correct
      })
      .catch(() => setReady((n) => n + 1));
  }, []);

  const [collapsed, setCollapsed] = useState(() => {
    // On a phone the sidebar is a drawer, and a drawer that starts open covers
    // the screen you came to look at. The saved preference is a desktop
    // preference; it does not apply where the control means something else.
    if (typeof window !== "undefined" && window.matchMedia("(max-width: 860px)").matches) {
      return true;
    }
    return readStored("rail") === "1";
  });
  useEffect(() => {
    writeStored("rail", collapsed ? "1" : "0");
  }, [collapsed]);

  // Declared after `collapsed`, because a collapsed rail has no width to drag.
  const rail = useRailWidth(collapsed);

  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // A menu that only closes on its own button is a menu people leave open. Any
  // click elsewhere, and Escape, put it away.
  useEffect(() => {
    if (!menuOpen) return;
    function onDown(e: MouseEvent) {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  function logout() {
    setToken(null);
    navigate("/login");
  }

  return (
    <div className={`shell${collapsed ? " is-collapsed" : ""}${rail.dragging ? " is-resizing" : ""}`}>
      {/* One tooltip for the whole application. See the note in Tooltips. */}
      <Tooltips />
      {/* The shared-till lock. It keeps the session and asks who is at the
          keyboard, rather than logging anybody out and losing their work. */}
      <TillLock user={user} onActorChange={setUser} />
      <aside className="sidebar">
        {/* The rail's own edge is the control. `separator` with an orientation
            and a value is what a screen reader needs to announce it as
            something adjustable rather than as a stray button. */}
        <button
          className="rail-resize"
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize the navigation. Arrow keys adjust, Home restores the default."
          aria-valuenow={rail.width ?? 248}
          aria-valuemin={rail.min}
          aria-valuemax={rail.max}
          onPointerDown={rail.start}
          onKeyDown={rail.nudge}
          onDoubleClick={() => rail.nudge({ key: "Home", preventDefault() {}, shiftKey: false } as any)}
        />
        <div className="brand">
          <img className="logo" src="/logo.png" alt="RX5000" />
          {/* The wordmark is what collapses; the logo stays, so the rail keeps
              an anchor and the eye has something to land on. */}
          <div className="brand-text">
            RX5000
            <small>PHARMACY SUITE</small>
          </div>
          <button
            className="rail-toggle"
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
            title={collapsed ? "Expand navigation" : "Collapse navigation"}
          >
            {collapsed ? <CaretRight size={14} weight="bold" /> : <CaretLeft size={14} weight="bold" />}
          </button>
        </div>
        <nav className="nav">
          {NAV.map((group) => (
            <div key={group.section}>
              <div className="nav-section">{group.section}</div>
              {group.links.map((l) => (
                <NavLink key={l.to} to={l.to} end={l.to === "/"}
                  // Collapsed, the label is gone, so the title attribute is the
                  // only thing naming the destination. It is not optional.
                  // Collapsed there is no label and no room for a badge, so the
                  // count goes into the title — otherwise the rail would say a
                  // number belonged to an icon without saying which number.
                  title={
                    collapsed
                      ? counts[l.to] ? `${l.label}: ${counts[l.to].toLocaleString()} need attention` : l.label
                      : counts[l.to] ? `${counts[l.to].toLocaleString()} need attention` : undefined
                  }
                  onClick={() => {
                    if (window.matchMedia("(max-width: 860px)").matches) setCollapsed(true);
                  }}
                  className={({ isActive }) =>
                    [isActive ? "active" : "", l.tier === 1 ? "nav-primary" : ""]
                      .filter(Boolean).join(" ")}
                >
                  <span className="icon">
                    <l.icon size={18} weight={l.tier === 1 ? "fill" : "regular"} />
                    {/* Collapsed to a rail there is no room for a number, but
                        hiding it entirely would mean the one view that shows
                        only icons is also the one that says nothing is waiting.
                        A dot keeps the signal without the digits. */}
                    {collapsed && counts[l.to] > 0 && <span className="nav-dot" aria-hidden="true" />}
                  </span>
                  <span className="nav-label">{l.label}</span>
                  {!collapsed && counts[l.to] > 0 && (
                    <span className="nav-count" aria-hidden="true">
                      {shortCount(counts[l.to])}
                    </span>
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
      </aside>

      <div className="content">
        {/* Who is signed in belongs where people look for it — the top right —
            rather than at the foot of a rail that collapses to icons. It also
            takes sign-out out of the navigation, where it sat one careless click
            below the last menu item. */}
        {/* Above the top bar, so the clock cannot be scrolled out of sight.
            Renders nothing at all for an ordinary account. */}
        <DemoBar user={user} />

        <header className="topbar">
          {/* Beside the profile, not inside it. Appearance is changed far more
              often than a profile is opened — a till by a window is squinted at
              twice a day — and burying it under a caret makes people live with
              the wrong one. Outside the menu's ref on purpose, so using it also
              closes an open profile menu. */}
          <ThemeToggle />
          <span className="topbar-sep" aria-hidden="true" />
          <div className="topbar-right" ref={menuRef}>
            <button
              className="me"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((o) => !o)}
            >
              <span className="me-avatar">{initials(user?.full_name)}</span>
              <span className="me-text">
                <span className="who">{user?.full_name ?? "…"}</span>
                <span className="role">{user?.role}</span>
              </span>
              <CaretDown size={12} weight="bold" className="me-caret" />
            </button>

            {menuOpen && (
              <div className="me-menu" role="menu">
                <div className="me-menu-head">
                  <span className="me-avatar">{initials(user?.full_name)}</span>
                  <span className="me-text">
                    <span className="who">{user?.full_name ?? "…"}</span>
                    <span className="role">{user?.role}</span>
                  </span>
                </div>
                <NavLink to="/profile" role="menuitem" onClick={() => setMenuOpen(false)}>
                  <UserCircle size={16} /> Your profile
                </NavLink>
                <NavLink to="/system" role="menuitem" onClick={() => setMenuOpen(false)}>
                  <Gear size={16} /> Settings
                </NavLink>
                <div className="me-menu-sep" role="separator" />
                <button role="menuitem" className="is-leave" onClick={logout}>
                  <SignOut size={16} /> Sign out
                </button>
              </div>
            )}
          </div>
        </header>

        {staleApi && (
          // Deliberately not dismissible and deliberately plain. The alternative
          // is somebody spending an hour on a 404 for an endpoint that exists.
          <div className="stale-api" role="status">
            <b>The server is running older code than is on disk.</b>{" "}
            {staleApi.started && staleApi.written ? (
              <>
                It started {fmtDateTime(staleApi.started)} and the code was last
                changed {fmtDateTime(staleApi.written)}, so endpoints added since
                then will answer 404.
              </>
            ) : (
              <>
                It is old enough that it cannot report its own version, so it is
                missing endpoints this screen calls.
              </>
            )}{" "}
            Restart the API.
          </div>
        )}

        <main className="main">{children}</main>
      </div>
    </div>
  );
}
