import {
  ArrowsClockwise,
  ArrowsLeftRight,
  BellRinging,
  Buildings,
  CalendarCheck,
  CaretLeft,
  CaretRight,
  ChartLineUp,
  ClipboardText,
  Coins,
  ClockCountdown,
  Desktop,
  Funnel,
  HandCoins,
  Headset,
  Megaphone,
  Notebook,
  Package,
  PauseCircle,
  Prescription,
  PaperPlaneTilt,
  Presentation,
  Receipt,
  Scales,
  SealCheck,
  SignOut,
  SlidersHorizontal,
  Sparkle,
  SquaresFour,
  Storefront,
  Truck,
  UserPlus,
  Users,
  Van,
  Vault,
} from "@phosphor-icons/react";
import { ReactNode, useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { api, configureLocale, setToken } from "../api";
import { User } from "../types";

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

const NAV = [
  {
    section: "Dispensary",
    links: [
      { to: "/dispense", label: "Dispensary", icon: Prescription, tier: 1 },
      { to: "/patients", label: "Patients", icon: Users, tier: 1 },
      { to: "/to-follows", label: "To follows", icon: ClockCountdown },
      { to: "/repeats", label: "Repeats", icon: ArrowsClockwise },
      { to: "/register", label: "Controlled Register", icon: Notebook },
      { to: "/deliveries", label: "Deliveries", icon: Van },
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
    ],
  },
  {
    section: "Stock",
    links: [
      { to: "/stock", label: "Inventory", icon: Package },
      { to: "/orders", label: "Procurement", icon: Truck },
      { to: "/stock-take", label: "Stock Take", icon: ClipboardText },
    ],
  },
  {
    section: "Accounts",
    links: [
      // Batching and sending claims is the weekly round; "Claims held" is the
      // exception queue for ones that could not go. Sending comes first.
      { to: "/claiming", label: "Claiming", icon: PaperPlaneTilt },
      { to: "/authorisations", label: "Authorisations", icon: SealCheck },
      { to: "/claims-held", label: "Claims held", icon: PauseCircle },
      { to: "/remittances", label: "Remittances", icon: Coins },
      { to: "/reconciliation", label: "Reconciliation", icon: ArrowsLeftRight },
      { to: "/ledger", label: "Ledger", icon: Scales },
      { to: "/periods", label: "Periods", icon: CalendarCheck },
    ],
  },
  {
    section: "Insight",
    links: [
      { to: "/", label: "Command Centre", icon: SquaresFour },
      { to: "/reports", label: "Analytics", icon: ChartLineUp },
      { to: "/assistant", label: "Pulse AI", icon: Sparkle },
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
    ],
  },
];

export default function Layout({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [, setReady] = useState(0);
  const navigate = useNavigate();

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
    return localStorage.getItem("rx3000_rail") === "1";
  });
  useEffect(() => {
    localStorage.setItem("rx3000_rail", collapsed ? "1" : "0");
  }, [collapsed]);

  function logout() {
    setToken(null);
    navigate("/login");
  }

  return (
    <div className={`shell${collapsed ? " is-collapsed" : ""}`}>
      <aside className="sidebar">
        <div className="brand">
          <img className="logo" src="/logo.png" alt="RX3000" />
          {/* The wordmark is what collapses; the logo stays, so the rail keeps
              an anchor and the eye has something to land on. */}
          <div className="brand-text">
            RX3000
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
                  title={collapsed ? l.label : undefined}
                  onClick={() => {
                    if (window.matchMedia("(max-width: 860px)").matches) setCollapsed(true);
                  }}
                  className={({ isActive }) =>
                    [isActive ? "active" : "", l.tier === 1 ? "nav-primary" : ""]
                      .filter(Boolean).join(" ")}
                >
                  <span className="icon"><l.icon size={18} weight={l.tier === 1 ? "fill" : "regular"} /></span>
                  <span className="nav-label">{l.label}</span>
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-footer">
          <NavLink to="/profile" className="me" title={collapsed ? "Your profile" : undefined}>
            <span className="me-avatar">{initials(user?.full_name)}</span>
            <span className="me-text">
              <span className="who">{user?.full_name ?? "…"}</span>
              <span className="role">{user?.role}</span>
            </span>
          </NavLink>
          <button className="signout" onClick={logout} title="Sign out">
            <SignOut size={16} />
            <span className="nav-label">Sign out</span>
          </button>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}
