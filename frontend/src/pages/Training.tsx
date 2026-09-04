/** Training material, arranged by the job somebody has to do today.
 *
 *  Public and unauthenticated, because the person who most needs it is the new
 *  assistant on their first morning, standing at a till they cannot sign in to
 *  yet while somebody looks for their username.
 *
 *  Ordered by role rather than by feature. A cashier does not need the claiming
 *  chapter, and a manual that makes them scroll past it teaches them the manual
 *  is not for them.
 *
 *  Each item names how long it takes. That number is the difference between "I
 *  will read it later" and reading it now.
 */
import { Link } from "react-router-dom";
import { Clock, Play } from "@phosphor-icons/react";

interface Lesson { title: string; minutes: number; body: string }

const COURSES: { role: string; who: string; lessons: Lesson[] }[] = [
  {
    role: "At the till",
    who: "Cashiers and assistants, first day",
    lessons: [
      { title: "Ringing up a sale", minutes: 6,
        body: "Scanning, quantities, a price override and who is allowed to make one." },
      { title: "Taking payment in two currencies", minutes: 8,
        body: "USD and ZiG on one sale, change in either, and what the rate of the day means." },
      { title: "Mobile wallets", minutes: 5,
        body: "EcoCash, Omari and InnBucks: which currency each settles in, and recording the confirmation code." },
      { title: "Locking the till", minutes: 3,
        body: "Why it locks rather than signs out, and taking over from a colleague mid-shift." },
      { title: "Cash up", minutes: 9,
        body: "Counting the drawer, explaining a variance, and closing without leaving it open." },
    ],
  },
  {
    role: "In the dispensary",
    who: "Pharmacists and dispensary assistants",
    lessons: [
      { title: "Capturing a script", minutes: 10,
        body: "Patient, prescriber, items and directions, including the shorthand the sig field understands." },
      { title: "Repeats and to-follows", minutes: 7,
        body: "What is owed to a patient when stock runs out, and how the balance comes back to them." },
      { title: "Interactions and allergies", minutes: 6,
        body: "What is checked, what is only flagged, and what still needs your judgement." },
      { title: "The controlled register", minutes: 8,
        body: "Schedules, the checking pharmacist's initials, and why a dispensed line cannot be edited." },
      { title: "Compounding", minutes: 7,
        body: "Recipes, the schedule a preparation inherits, and costing a made-up item." },
    ],
  },
  {
    role: "Running the business",
    who: "Owners and managers",
    lessons: [
      { title: "Stock that orders itself", minutes: 8,
        body: "Reorder levels, generated orders, receiving by scan and batch expiry." },
      { title: "Claiming and remittances", minutes: 12,
        body: "Batching per pay office, reading a rejection, and reconciling what a scheme actually paid." },
      { title: "Fiscalisation", minutes: 6,
        body: "What ZIMRA receives, and why a fiscalised sale is credited rather than voided." },
      { title: "Reading the reports", minutes: 9,
        body: "The eighty-eight reports, which four you should read weekly, and what each one refuses to guess." },
      { title: "Staff, PINs and permissions", minutes: 7,
        body: "Who can do what, setting a till PIN, and what the audit trail records." },
    ],
  },
];

export default function Training() {
  const total = COURSES.reduce((s, c) => s + c.lessons.reduce((n, l) => n + l.minutes, 0), 0);

  return (
    <div className="pub">
      <header className="pub-head">
        <div className="brand-lg">
          <span className="brand-lockup" role="img"
               aria-label="RX5000, pharmacy operating system" />
          <div>RX<span>5000</span></div>
        </div>
        <Link to="/login" className="btn small">Sign in</Link>
      </header>

      <section className="pub-hero">
        <h1>Training</h1>
        <p>
          Every screen in the product, in the order somebody actually meets them.
          The whole set runs to about {Math.round(total / 60)} hours, and nobody
          needs all of it: take the section for the job you do.
        </p>
        <p className="pub-fine">
          Best followed with the product open beside you. A four hour demo account
          costs nothing and needs no password.
        </p>
      </section>

      {COURSES.map((course) => (
        <section key={course.role} className="tr-course">
          <div className="tr-course-head">
            <h2>{course.role}</h2>
            <span className="muted">{course.who}</span>
          </div>
          <ol className="tr-list">
            {course.lessons.map((l, i) => (
              <li key={l.title}>
                <span className="tr-no">{i + 1}</span>
                <div className="tr-body">
                  <b>{l.title}</b>
                  <p>{l.body}</p>
                </div>
                <span className="tr-mins"><Clock size={13} /> {l.minutes} min</span>
                <Link to="/login" className="tr-go" aria-label={`Open ${l.title}`}>
                  <Play size={14} weight="fill" />
                </Link>
              </li>
            ))}
          </ol>
        </section>
      ))}

      <footer className="pub-foot">
        <span>RX5000 Pharmacy Suite</span>
        <Link to="/welcome">What RX5000 does</Link>
      </footer>
    </div>
  );
}
