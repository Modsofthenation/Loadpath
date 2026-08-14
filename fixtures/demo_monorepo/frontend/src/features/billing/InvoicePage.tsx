import { InvoiceForm } from "./InvoiceForm";
import { useInvoice } from "./useInvoice";

export function InvoicePage() {
  const { data } = useInvoice("1");
  return (
    <section>
      <h1>Invoice {data?.id}</h1>
      <InvoiceForm invoice={data} />
    </section>
  );
}
