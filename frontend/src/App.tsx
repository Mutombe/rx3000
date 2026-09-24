/** The fork in the road: the pharmacy's own staff, or one of its customers.
 *
 *  WHY THE PORTALS SIT ABOVE EVERYTHING
 *
 *  The four public portals used to be routes inside the staff application,
 *  which meant a patient opening a link from an SMS mounted `ConnectionProvider`
 *  and `ScannerProvider` and then sat there polling `/api/health` from a phone
 *  on a Zimbabwean mobile connection, and downloaded a 645 KB stylesheet
 *  written for a point-of-sale system to find out whether their tablets were
 *  ready. `PatientPortal.tsx` opened by insisting a patient "must never load
 *  its bundle". It did.
 *
 *  So the split is made here, at the very top, before a single provider is
 *  mounted. A portal route reaches its own small chunk and nothing else; the
 *  staff application — every provider, every page and the stylesheet they are
 *  drawn with — is behind one lazy boundary that a customer never crosses.
 */
import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";

// Their own chunks, their own stylesheet, no sidebar and no session.
const PatientPortal = lazy(() => import("./portal/PatientPortal"));
const DoctorPortal = lazy(() => import("./portal/DoctorPortal"));
const SupplierQuote = lazy(() => import("./portal/SupplierQuote"));
const SupplierOrders = lazy(() => import("./portal/SupplierOrders"));

// Everything a member of staff ever sees, including the sign-in.
const Staff = lazy(() => import("./Staff"));

export default function App() {
  return (
    <Suspense fallback={null}>
      <Routes>
        {/* Public, unauthenticated, and above the staff application on purpose
            so a patient is never bounced to a staff sign-in screen. */}
        <Route path="/portal/patient/:token" element={<PatientPortal />} />
        <Route path="/portal/doctor/:token" element={<DoctorPortal />} />
        {/* A wholesaler quoting from a link in an email, at the short address
            on purpose: this one is pasted into emails and read off screens by
            people who have never heard of us, and /quote/ is what it is. */}
        <Route path="/quote/:token" element={<SupplierQuote />} />
        {/* A wholesaler's standing link: the orders this pharmacy has sent
            them, and where they say when each one is coming. */}
        <Route path="/supplier/:token" element={<SupplierOrders />} />
        <Route path="/*" element={<Staff />} />
      </Routes>
    </Suspense>
  );
}
