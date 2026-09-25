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
import PageHead from "../components/PageHead";

export default function BankReconciliation() {
  return (
    <div className="page">
      <PageHead title="Bank reconciliation" sub="What the bank says against what the ledger says. The two never agree line for line, and the difference is the point of the exercise." />

      {/* The family this page belongs to. It used to sit in the
          page's action slot beside a primary button, and on Authorisations
          beside a search box as well, so three different kinds of control
          shared one corner and wrapped the header to 176px against 76 on an
          ordinary page. Navigation is not an action. */}
      <SectionNav tabs={RECON_TABS} end="/reconciliation" />
      <BankReconcile />
    </div>
  );
}
