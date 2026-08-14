import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { getToken } from "./api";
import Login from "./pages/Login";
import { PageSkeleton } from "./components/Skeleton";
import { ToastProvider } from "./components/Toast";
import { ConfirmProvider } from "./components/Confirm";

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
const Deliveries = lazy(() => import("./pages/Deliveries"));
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
    <Routes>
      <Route path="/login" element={<Login />} />
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
                <Route path="/dispense" element={<Dispense />} />
                <Route path="/to-follows" element={<ToFollows />} />
                <Route path="/periods" element={<Periods />} />
                <Route path="/system" element={<System />} />
                <Route path="/claims-held" element={<DeferredClaims />} />
                <Route path="/deliveries" element={<Deliveries />} />
                <Route path="/repeats" element={<Repeats />} />
                <Route path="/ledger" element={<Ledger />} />
                <Route path="/ledger/entries/:id" element={<JournalDetail />} />
                <Route path="/ledger/accounts/:code" element={<AccountLedger />} />
                <Route path="/pos" element={<POS />} />
                <Route path="/sales/:id" element={<SaleDetail />} />
                <Route path="/stock" element={<Stock />} />
                <Route path="/products/:id" element={<ProductDetail />} />
                <Route path="/orders" element={<Orders />} />
                <Route path="/orders/:id" element={<OrderDetail />} />
                <Route path="/register" element={<Register />} />
                <Route path="/reminders" element={<Reminders />} />
                <Route path="/shifts" element={<Shifts />} />
                <Route path="/reconciliation" element={<CardReconciliation />} />
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
    </ConfirmProvider>
    </ToastProvider>
  );
}
