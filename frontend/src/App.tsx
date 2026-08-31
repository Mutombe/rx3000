import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";

const WillCall = lazy(() => import("./pages/WillCall"));
const Samples = lazy(() => import("./pages/Samples"));
const Recall = lazy(() => import("./pages/Recall"));
const Payables = lazy(() => import("./pages/Payables"));
const ClaimBatchDetail = lazy(() => import("./pages/ClaimBatchDetail"));
const WaybillDetail = lazy(() => import("./pages/WaybillDetail"));
const DispensingHistory = lazy(() => import("./pages/DispensingHistory"));
const MoneyOwed = lazy(() => import("./pages/MoneyOwed"));
const WillCallBag = lazy(() => import("./pages/WillCallBag"));
const ToFollowDetail = lazy(() => import("./pages/ToFollowDetail"));
const SchemeCalendar = lazy(() => import("./pages/SchemeCalendar"));
const SupplierDetail = lazy(() => import("./pages/SupplierDetail"));
const ClaimDetail = lazy(() => import("./pages/ClaimDetail"));
const BatchDetail = lazy(() => import("./pages/BatchDetail"));
const PrescriptionDetail = lazy(() => import("./pages/PrescriptionDetail"));
const StaffDetail = lazy(() => import("./pages/StaffDetail"));
const PrescriberDetail = lazy(() => import("./pages/PrescriberDetail"));
const ShiftDetail = lazy(() => import("./pages/ShiftDetail"));
const MessageDetail = lazy(() => import("./pages/MessageDetail"));
const CampaignDetail = lazy(() => import("./pages/CampaignDetail"));
const InvoiceDetail = lazy(() => import("./pages/InvoiceDetail"));
const LayByDetail = lazy(() => import("./pages/LayByDetail"));
const LeadDetail = lazy(() => import("./pages/LeadDetail"));
const Welcome = lazy(() => import("./pages/Welcome"));
const Training = lazy(() => import("./pages/Training"));
import { getToken } from "./api";
import Login from "./pages/Login";
import { PageSkeleton } from "./components/Skeleton";
import { ToastProvider } from "./components/Toast";
import { ConfirmProvider } from "./components/Confirm";
import { ConnectionProvider, RequiresConnection } from "./components/Connection";

/* Every page is split out of the initial bundle. A till on a mobile
 * connection pays for the whole application on first load otherwise, and
 * a pharmacist only ever opens three or four screens. Login stays eager:
 * it is the first thing a signed-out user sees and must not wait on a
 * second round trip. */
const AccountDetail = lazy(() => import("./pages/AccountDetail"));
const Profile = lazy(() => import("./pages/Profile"));
// Outside the staff application entirely: their own chunks, their own
// stylesheet, no sidebar and no session. A patient checking whether their
// tablets are ready must not download a point-of-sale system to find out.
const PatientPortal = lazy(() => import("./portal/PatientPortal"));
const DoctorPortal = lazy(() => import("./portal/DoctorPortal"));
const Accounts = lazy(() => import("./pages/Accounts"));
const Admin = lazy(() => import("./pages/Admin"));
const Assistant = lazy(() => import("./pages/Assistant"));
const CardReconciliation = lazy(() => import("./pages/CardReconciliation"));
const CaseDetail = lazy(() => import("./pages/CaseDetail"));
const ContactDetail = lazy(() => import("./pages/ContactDetail"));
const CrmReports = lazy(() => import("./pages/CrmReports"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const DealDetail = lazy(() => import("./pages/DealDetail"));
const DeferredClaims = lazy(() => import("./pages/DeferredClaims"));
const Scorecard = lazy(() => import("./pages/Scorecard"));
const BranchPerformance = lazy(() => import("./pages/BranchPerformance"));
const StockCategories = lazy(() => import("./pages/StockCategories"));
const Pharmacies = lazy(() => import("./pages/Pharmacies"));
const RemittanceDetail = lazy(() => import("./pages/RemittanceDetail"));
const Deliveries = lazy(() => import("./pages/Deliveries"));
const Drivers = lazy(() => import("./pages/Drivers"));
const Reconciliation = lazy(() => import("./pages/Reconciliation"));
const Seasons = lazy(() => import("./pages/Seasons"));
const Compliance = lazy(() => import("./pages/Compliance"));
const Settlements = lazy(() => import("./pages/Settlements"));
const StockPerformance = lazy(() => import("./pages/StockPerformance"));
const DispensingDetail = lazy(() => import("./pages/DispensingDetail"));
const RepeatDetail = lazy(() => import("./pages/RepeatDetail"));
const BankReconciliation = lazy(() => import("./pages/BankReconciliation"));
const DriverDetail = lazy(() => import("./pages/DriverDetail"));
const Dispense = lazy(() => import("./pages/Dispense"));
const HelpDesk = lazy(() => import("./pages/HelpDesk"));
const AccountLedger = lazy(() => import("./pages/AccountLedger"));
const JournalDetail = lazy(() => import("./pages/JournalDetail"));
const Leads = lazy(() => import("./pages/Leads"));
const Ledger = lazy(() => import("./pages/Ledger"));
const Marketing = lazy(() => import("./pages/Marketing"));
const OrderDetail = lazy(() => import("./pages/OrderDetail"));
const Orders = lazy(() => import("./pages/Orders"));
const POS = lazy(() => import("./pages/POS"));
const PatientDetail = lazy(() => import("./pages/PatientDetail"));
const Patients = lazy(() => import("./pages/Patients"));
const Periods = lazy(() => import("./pages/Periods"));
const Pipeline = lazy(() => import("./pages/Pipeline"));
const ProductDetail = lazy(() => import("./pages/ProductDetail"));
const Register = lazy(() => import("./pages/Register"));
const Reminders = lazy(() => import("./pages/Reminders"));
const Repeats = lazy(() => import("./pages/Repeats"));
const Reports = lazy(() => import("./pages/Reports"));
const SaleDetail = lazy(() => import("./pages/SaleDetail"));
const Shifts = lazy(() => import("./pages/Shifts"));
const Fiscal = lazy(() => import("./pages/Fiscal"));
const Claiming = lazy(() => import("./pages/Claiming"));
const StockTake = lazy(() => import("./pages/StockTake"));
const LayBys = lazy(() => import("./pages/LayBys"));
const Remittances = lazy(() => import("./pages/Remittances"));
const Authorisations = lazy(() => import("./pages/Authorisations"));
const Compounding = lazy(() => import("./pages/Compounding"));
const Branches = lazy(() => import("./pages/Branches"));
const Stock = lazy(() => import("./pages/Stock"));
const System = lazy(() => import("./pages/System"));
const ToFollows = lazy(() => import("./pages/ToFollows"));


function Protected({ children }: { children: JSX.Element }) {
  if (!getToken()) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <ToastProvider>
    <ConfirmProvider>
    <ConnectionProvider>
    <Routes>
      <Route path="/login" element={<Login />} />
      {/* Public, because the person reading either of these has no account yet.
          Lazily loaded: neither is on the path of anybody who works here, and a
          till on a slow branch line should not pay for them at startup. */}
      <Route path="/welcome" element={<Suspense fallback={null}><Welcome /></Suspense>} />
      <Route path="/training" element={<Suspense fallback={null}><Training /></Suspense>} />
      {/* Public, unauthenticated, and deliberately above the Protected route so
          a patient is never bounced to a staff sign-in screen. */}
      <Route
        path="/portal/patient/:token"
        element={<Suspense fallback={null}><PatientPortal /></Suspense>}
      />
      <Route
        path="/portal/doctor/:token"
        element={<Suspense fallback={null}><DoctorPortal /></Suspense>}
      />
      <Route
        path="/*"
        element={
          <Protected>
            <Layout>
              {/* Inside Layout on purpose: the chrome stays put and only
                  the page area waits. A boundary above this would blank
                  the whole application on every navigation. */}
              <Suspense fallback={<PageSkeleton />}>
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/patients" element={<Patients />} />
                <Route path="/patients/:id" element={<PatientDetail />} />
                <Route path="/dispense" element={
                  <RequiresConnection what="Dispensing"><Dispense /></RequiresConnection>} />
                <Route path="/to-follows" element={<ToFollows />} />
                <Route path="/will-call" element={<WillCall />} />
                <Route path="/samples" element={<Samples />} />
                <Route path="/recall" element={<Recall />} />
                <Route path="/payables" element={<Payables />} />
                <Route path="/dispensing-history" element={<DispensingHistory />} />
                <Route path="/dispensings/:id" element={<DispensingDetail />} />
                <Route path="/money-owed" element={<MoneyOwed />} />
                <Route path="/will-call/:id" element={<WillCallBag />} />
                <Route path="/to-follows/:id" element={<ToFollowDetail />} />
                <Route path="/claiming-calendar" element={<SchemeCalendar />} />
                <Route path="/suppliers/:id" element={<SupplierDetail />} />
                <Route path="/claims/:id" element={<ClaimDetail />} />
                <Route path="/claim-batches/:id" element={<ClaimBatchDetail />} />
                <Route path="/batches/:id" element={<BatchDetail />} />
                <Route path="/prescriptions/:id" element={<PrescriptionDetail />} />
                <Route path="/staff/:id" element={<StaffDetail />} />
                <Route path="/prescribers/:id" element={<PrescriberDetail />} />
                <Route path="/shifts/:id" element={<ShiftDetail />} />
                <Route path="/messages/:id" element={<MessageDetail />} />
                <Route path="/campaigns/:id" element={<CampaignDetail />} />
                <Route path="/payables/invoices/:id" element={<InvoiceDetail />} />
                <Route path="/laybys/:id" element={<LayByDetail />} />
                <Route path="/leads/:id" element={<LeadDetail />} />
                <Route path="/periods" element={<Periods />} />
                <Route path="/system" element={<System />} />
                <Route path="/claims-held" element={<DeferredClaims />} />
                <Route path="/scorecard" element={<Scorecard />} />
                <Route path="/branches/:id/performance" element={<BranchPerformance />} />
                <Route path="/stock-categories" element={<StockCategories />} />
                <Route path="/pharmacies" element={<Pharmacies />} />
                <Route path="/remittances/:id" element={<RemittanceDetail />} />
                <Route path="/deliveries" element={<Deliveries />} />
                <Route path="/waybills/:id" element={<WaybillDetail />} />
                <Route path="/drivers" element={<Drivers />} />
                <Route path="/drivers/:id" element={<DriverDetail />} />
                <Route path="/repeats" element={<Repeats />} />
                <Route path="/repeats/:id" element={<RepeatDetail />} />
                <Route path="/ledger" element={<Ledger />} />
                <Route path="/ledger/entries/:id" element={<JournalDetail />} />
                <Route path="/ledger/accounts/:code" element={<AccountLedger />} />
                <Route path="/pos" element={<POS />} />
                <Route path="/sales/:id" element={<SaleDetail />} />
                <Route path="/stock" element={<Stock />} />
                <Route path="/products/:id" element={<ProductDetail />} />
                <Route path="/orders" element={<Orders />} />
                <Route path="/orders/:id" element={<OrderDetail />} />
                <Route path="/register" element={
                  <RequiresConnection what="The controlled register"><Register /></RequiresConnection>} />
                <Route path="/reminders" element={<Reminders />} />
                <Route path="/shifts" element={<Shifts />} />
                <Route path="/fiscal" element={<Fiscal />} />
                <Route path="/claiming" element={<Claiming />} />
                <Route path="/stock-take" element={<StockTake />} />
                <Route path="/laybys" element={<LayBys />} />
                <Route path="/remittances" element={<Remittances />} />
                <Route path="/authorisations" element={<Authorisations />} />
                <Route path="/compounding" element={<Compounding />} />
                <Route path="/branches" element={<Branches />} />
                {/* The hub, then the two that need a file uploaded. Cash,
                    claims and stock keep the screens they already had and
                    are reached from the same strip. */}
                <Route path="/seasons" element={<Seasons />} />
                <Route path="/stock-performance" element={<StockPerformance />} />
                <Route path="/compliance" element={<Compliance />} />
                <Route path="/reconciliation/settlements" element={<Settlements />} />
                <Route path="/reconciliation" element={<Reconciliation />} />
                <Route path="/reconciliation/card" element={<CardReconciliation />} />
                <Route path="/reconciliation/bank" element={<BankReconciliation />} />
                <Route path="/leads" element={<Leads />} />
                <Route path="/pipeline" element={<Pipeline />} />
                <Route path="/deals/:id" element={<DealDetail />} />
                <Route path="/crm-reports" element={<CrmReports />} />
                <Route path="/profile" element={<Profile />} />
                <Route path="/accounts" element={<Accounts />} />
                <Route path="/accounts/:id" element={<AccountDetail />} />
                <Route path="/contacts/:id" element={<ContactDetail />} />
                <Route path="/marketing" element={<Marketing />} />
                <Route path="/helpdesk" element={<HelpDesk />} />
                <Route path="/cases/:id" element={<CaseDetail />} />
                <Route path="/reports" element={<Reports />} />
                <Route path="/assistant" element={<Assistant />} />
                <Route path="/admin" element={<Admin />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
              </Suspense>
            </Layout>
          </Protected>
        }
      />
    </Routes>
    </ConnectionProvider>
    </ConfirmProvider>
    </ToastProvider>
  );
}
