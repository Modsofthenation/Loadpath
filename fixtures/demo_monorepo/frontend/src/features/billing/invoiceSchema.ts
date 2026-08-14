import { z } from "zod";

export const invoiceSchema = z.object({
  customer_id: z.number(),
  total: z.string(),
  status: z.string(),
});
