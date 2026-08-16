import { createApi, fetchBaseQuery } from "@reduxjs/toolkit/query/react";

export const invoiceApi = createApi({
  reducerPath: "invoiceApi",
  baseQuery: fetchBaseQuery({ baseUrl: "/api" }),
  endpoints: (builder) => ({
    getInvoice: builder.query({
      query: (id: string) => `/invoices/${id}`,
    }),
    saveInvoice: builder.mutation({
      query: (body: unknown) => ({ url: "/invoices", method: "POST", body }),
    }),
  }),
});
