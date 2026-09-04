/** What RX5000 is, for somebody who arrived at a sign-in screen and does not
 *  yet know what they are signing in to.
 *
 *  Public and unauthenticated, because the person reading it has no account.
 *  Written for a pharmacy owner rather than a buyer of software: what it does on
 *  a Tuesday, what it stops going wrong, and what it costs them to try.
 *
 *  Deliberately short. A prospect who wants more detail should be inside the
 *  demo, not further down a page.
 */
import { Link } from "react-router-dom";
import {
  ArrowRight, ClipboardText, Coins, Prescription, Package, Receipt, ShieldCheck,
} from "@phosphor-icons/react";

const WORK = [
  {
    Icon: Prescription,
    title: "Dispensing",
    body: "Script capture, repeats, interactions and allergies checked as you go, "
        + "and a printed label that matches what the regulator expects to see.",
  },
  {
    Icon: ClipboardText,
    title: "The controlled register",
    body: "Schedule 3 upward recorded as it is dispensed, with the checking "
        + "pharmacist named. An inspector asks for this and it is already written.",
  },
  {
    Icon: Coins,
    title: "Till and cash up",
    body: "USD and ZiG on one sale, mobile wallets, medical aid split, and a "
        + "cash-up at the end of the day that reconciles to the drawer.",
  },
  {
    Icon: Package,
    title: "Stock",
    body: "Batches and expiry, reorder levels that raise their own orders, and a "
        + "stock take that two people can count without contradicting each other.",
  },
  {
    Icon: Receipt,
    title: "Claiming",
    body: "Claims batched per pay office, remittances reconciled line by line, "
        + "and every rejection with the reason the scheme gave for it.",
  },
  {
    Icon: ShieldCheck,
    title: "Fiscalisation",
    body: "ZIMRA fiscal records raised with the sale, and a credit note where a "
        + "void would be illegal.",
  },
];

export default function Welcome() {
  return (
    <div className="pub">
      <header className="pub-head">
        <div className="brand-lg">
          <span className="brand-lockup" role="img"
               aria-label="RX5000, pharmacy operating system" />
        </div>
        <Link to="/login" className="btn small">Sign in</Link>
      </header>

      <section className="pub-hero">
        <h1>The whole pharmacy, on one screen.</h1>
        <p>
          Dispensing, the controlled register, the till, stock, medical aid
          claiming and fiscalisation. Built for how a Zimbabwean pharmacy actually
          runs: two currencies, three mobile wallets, and an inspector who wants
          the register in order.
        </p>
        <div className="pub-cta">
          <Link to="/login" className="btn primary">Try it for four hours <ArrowRight size={14} /></Link>
          <Link to="/training" className="btn secondary">Training material</Link>
        </div>
        <p className="pub-fine">
          No card, no call, and nothing switched off. When the four hours are up
          the account stops and everything you entered is kept.
        </p>
      </section>

      <section className="pub-grid">
        {WORK.map(({ Icon, title, body }) => (
          <article key={title} className="pub-card">
            <Icon size={20} weight="duotone" />
            <h2>{title}</h2>
            <p>{body}</p>
          </article>
        ))}
      </section>

      <footer className="pub-foot">
        <span>RX5000 Pharmacy Suite</span>
        <Link to="/login">Sign in</Link>
      </footer>
    </div>
  );
}
