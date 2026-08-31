/** The bank statement against the ledger, under Reconciliation.
 *
 *  The same screen the ledger has always shown on its Bank statement tab. It
 *  is here as well because reconciling the bank is one of five things a
 *  pharmacy reconciles, and the person doing the other four should not have to
 *  know it lives inside the ledger.
 */
import BankReconcile from "../components/BankReconcile";
import SectionNav from "../components/SectionNav";
import { RECON_TABS } from "../reconTabs";

export default function BankReconciliation() {
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Bank reconciliation</h1>
          <p className="muted">
            What the bank says against what the ledger says. The two never agree
            line for line, and the difference is the point of the exercise.
          </p>
        </div>
        <div className="page-actions">
          <SectionNav tabs={RECON_TABS} end="/reconciliation" />
        </div>
      </header>
      <BankReconcile />
    </div>
  );
}
