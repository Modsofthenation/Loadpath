/** graphql-codegen types — stitch to InvoiceType by field overlap. */
export type InvoiceType = {
  __typename?: "InvoiceType";
  id: number;
  total: number;
  status: string;
};

export type InvoiceQuery = {
  __typename?: "Query";
  invoice?: InvoiceType | null;
};
