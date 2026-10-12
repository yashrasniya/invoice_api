import api from './api';

export type Category = { id: number; name: string; description: string | null };

export type InventoryProduct = {
  id: number;
  sku: string;
  name: string;
  description: string | null;
  category: number | null;
  category_name: string | null;
  price: string;
  gst_percentage: string;
  current_stock: number;
  reorder_level: number;
};

export type Movement = {
  id: number;
  product: number;
  quantity: number;
  movement_type: 'IN' | 'OUT';
  date: string;
  notes: string | null;
};

// The inventory endpoints are unpaginated today; tolerate a DRF page wrapper if that is ever switched on.
const rows = <T,>(d: T[] | { results: T[] }): T[] => (Array.isArray(d) ? d : d.results);

export const isLowStock = (p: InventoryProduct) => p.current_stock <= p.reorder_level;

export async function listInventory(search = '') {
  const { data } = await api.get<InventoryProduct[] | { results: InventoryProduct[] }>('inventory/products/', {
    params: search ? { search } : {},
  });
  return rows(data);
}

/** Barcodes are matched against the SKU (the product has no separate barcode field). */
export async function findBySku(code: string) {
  const hits = await listInventory(code);
  return hits.find((p) => p.sku.toLowerCase() === code.trim().toLowerCase()) ?? null;
}

export const getInventoryProduct = async (id: number) =>
  (await api.get<InventoryProduct>(`inventory/products/${id}/`)).data;

export type ProductInput = {
  sku: string;
  name: string;
  description: string;
  category: number | null;
  price: string;
  gst_percentage: string;
  reorder_level: string;
  /** only sent on create; afterwards stock changes through movements so history stays true */
  current_stock?: string;
};

export async function saveInventoryProduct(input: ProductInput, id?: number) {
  const body: Record<string, unknown> = {
    sku: input.sku.trim(),
    name: input.name.trim(),
    description: input.description.trim() || null,
    category: input.category,
    price: input.price.trim(),
    gst_percentage: input.gst_percentage.trim() || '0',
    reorder_level: Number(input.reorder_level || 0),
  };
  if (!id) body.current_stock = Number(input.current_stock || 0);
  return id
    ? (await api.patch<InventoryProduct>(`inventory/products/${id}/`, body)).data
    : (await api.post<InventoryProduct>('inventory/products/', body)).data;
}

export const deleteInventoryProduct = (id: number) => api.delete(`inventory/products/${id}/`);

export async function listCategories() {
  const { data } = await api.get<Category[] | { results: Category[] }>('inventory/categories/');
  return rows(data);
}
export const createCategory = async (name: string) =>
  (await api.post<Category>('inventory/categories/', { name: name.trim() })).data;
export const deleteCategory = (id: number) => api.delete(`inventory/categories/${id}/`);

export async function listMovements(product: number) {
  const { data } = await api.get<Movement[] | { results: Movement[] }>('inventory/stock-movements/', { params: { product } });
  return rows(data).sort((a, b) => (a.date < b.date ? 1 : -1));
}

export const addMovement = async (m: { product: number; quantity: number; movement_type: 'IN' | 'OUT'; notes?: string }) =>
  (await api.post<Movement>('inventory/stock-movements/', m)).data;
