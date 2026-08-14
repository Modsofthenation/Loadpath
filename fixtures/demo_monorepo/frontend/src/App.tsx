import { InvoicePage } from "./features/billing/InvoicePage";
import { MePage } from "./features/auth/MePage";

export function App() {
  return (
    <Routes>
      <Route path="/invoices/:id" element={<InvoicePage />} />
      <Route path="/me" element={<MePage />} />
    </Routes>
  );
}
