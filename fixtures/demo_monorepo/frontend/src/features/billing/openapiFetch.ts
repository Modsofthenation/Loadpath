declare const client: {
  GET: (path: string, init?: unknown) => Promise<unknown>;
};

export function getInvoiceTyped(id: string) {
  return client.GET("/api/invoices/{id}", { params: { path: { id } } });
}
