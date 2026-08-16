import { InvoiceForm } from "../../../features/billing/InvoiceForm";
import { saveInvoice } from "./actions";

export default function InvoicesPage({ params }: { params: { id: string } }) {
  return (
    <section>
      <InvoiceForm invoice={{ id: params.id }} />
      <form action={saveInvoice}>
        <button type="submit">Save</button>
      </form>
    </section>
  );
}
