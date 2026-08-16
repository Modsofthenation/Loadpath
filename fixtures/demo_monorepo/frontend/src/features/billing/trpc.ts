declare const trpc: {
  invoice: { get: { useQuery: (args: { id: string }) => unknown } };
};

export function useInvoiceRpc(id: string) {
  return trpc.invoice.get.useQuery({ id });
}
