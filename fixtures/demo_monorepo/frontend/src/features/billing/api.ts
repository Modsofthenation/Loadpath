export async function fetchInvoice(id: string) {
  const res = await fetch(`/api/invoices/${id}`);
  return res.json();
}

export async function updateInvoice(id: string, body: unknown) {
  const res = await fetch(`/api/invoices/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
  return res.json();
}
