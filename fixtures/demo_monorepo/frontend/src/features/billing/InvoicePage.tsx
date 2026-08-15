import { gql } from "@apollo/client";
import { InvoiceForm } from "./InvoiceForm";
import { useInvoice } from "./useInvoice";

const INVOICE_QUERY = gql`
  query Invoice($id: ID!) {
    invoice {
      total
      status
    }
  }
`;

export function InvoicePage() {
  const { data } = useInvoice("1");
  void INVOICE_QUERY;
  return (
    <section>
      <h1>Invoice {data?.id}</h1>
      <InvoiceForm invoice={data} />
    </section>
  );
}
