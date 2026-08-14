import { invoiceSchema } from "./invoiceSchema";

export function InvoiceForm({ invoice }) {
  const parsed = invoiceSchema.parse({
    customer_id: invoice?.customer_id,
    total: invoice?.total,
    status: invoice?.status,
  });
  return (
    <form>
      <input name="total" defaultValue={parsed.total} />
    </form>
  );
}
