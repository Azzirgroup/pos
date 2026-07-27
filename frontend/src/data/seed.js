/**
 * Demo catalog — fallback only.
 *
 * Used when the site has no sellable items yet, so a fresh install is still
 * clickable. A real site always serves `cosmestics.api.catalog.get_catalog`;
 * selling these fake SKUs against a real ERPNext site fails, because no Item
 * matches them.
 *
 * Raw data lives in `cosmestics/data/catalog.json` — one file shared with the
 * Python installer, so the demo the cashier sees and the demo seeded into a
 * site cannot drift apart.
 */
import catalog from '@data/catalog.json'
import { decorate } from './derive'

export const CATEGORIES = catalog.categories.map((c) => ({ name: c.name, count: 0 }))

/** Own branches — targets for a Material Transfer request. */
export const WAREHOUSES = catalog.warehouses

/**
 * Neighbouring shops we buy from when out of stock and the customer is waiting.
 * Modelled as Suppliers, not warehouses — the goods are genuinely bought and
 * resold, so they need a purchase document and a cost price.
 */
export const NEIGHBOURS = catalog.neighbours

export const ITEMS = catalog.items.map((row) =>
	decorate({
		item_code: row.item_code,
		item_name: row.item_name,
		brand: row.brand,
		category: row.category,
		price: row.price,
		stock: row.stock,
		barcodes: [row.barcode],
		uom: 'Nos',
	}),
)
