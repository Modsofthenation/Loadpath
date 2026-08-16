"use server";

export async function saveInvoice(formData: FormData) {
  const id = String(formData.get("id") || "");
  return id;
}
