import { frappeRequest } from 'frappe-ui'

/**
 * Thin wrapper over the POS endpoints.
 *
 * Kept deliberately dumb: no caching, no retry policy. The outbox that makes
 * checkout feel instant belongs in the cart flow, not here.
 */
function call(method, args) {
	return frappeRequest({
		url: `/api/method/${method}`,
		method: 'POST',
		params: args,
	})
}

/** Submit a completed sale. Resolves with {invoice, grand_total, change, …}. */
export function submitSale({ items, payment, customer }) {
	return call('cosmestics.api.pos.submit_sale', {
		items: items.map((l) => ({
			item_code: l.item_code,
			qty: l.qty,
			rate: l.rate,
			discount_pct: l.discountPct,
			sourced: l.sourced ? { supplier: l.sourced.supplier, buy_rate: l.sourced.buyRate } : null,
		})),
		payment,
		customer: customer || null,
	})
}

/* ---------- catalog ---------- */

/** Whole sellable catalog in one call; searched locally thereafter. */
export const getCatalog = () => call('cosmestics.api.catalog.get_catalog')

/* ---------- shift ---------- */

export const getProfiles = () => call('cosmestics.api.shift.get_profiles')
export const getOpenShift = () => call('cosmestics.api.shift.get_open_shift')
export const getClosingSummary = () => call('cosmestics.api.shift.get_closing_summary')

export const openShift = ({ posProfile, balances }) =>
	call('cosmestics.api.shift.open_shift', { pos_profile: posProfile, balances })

export const closeShift = ({ counted }) =>
	call('cosmestics.api.shift.close_shift', { counted })

/* ---------- customers ---------- */

export const searchCustomers = (query) =>
	call('cosmestics.api.customers.search', { query: query || '' })

export const createCustomer = ({ customerName, mobileNo }) =>
	call('cosmestics.api.customers.create', {
		customer_name: customerName,
		mobile_no: mobileNo || null,
	})

/** Raise a Material Transfer request for stock held at another branch. */
export function requestTransfer({ items, fromWarehouse }) {
	return call('cosmestics.api.stock.request_transfer', {
		items: items.map((i) => ({ item_code: i.item_code, qty: i.qty })),
		from_warehouse: fromWarehouse,
	})
}
