/**
 * Activities per module, shown as sub-tabs.
 *
 * Kept as data rather than markup so the rail, the router and the sub-tabs
 * cannot drift out of step — every entry here has a matching route.
 *
 * Document types live inside the module they belong to, **in the order the
 * paperwork actually happens**: you order before you deliver, and you deliver
 * before you invoice. A flat alphabetical index of fourteen doctypes made a
 * reader work out that sequence for themselves every time; this states it.
 *
 * Each of those tabs opens the documents hub, which carries its own List ·
 * Insights · Reports tabs for that type.
 */
export const MODULE_TABS = {
	inventory: [
		{ label: 'Items', to: '/items' },
		{ label: 'Item groups', to: '/item-groups' },
		{ label: 'Item price', to: '/pricing' },
		{ label: 'Stock levels', to: '/inventory' },
		{ label: 'Barcodes', to: '/barcodes' },
		// Moving stock between stores, receiving it in, writing it off. The
		// screen and the form both existed — `/documents/stock-entry` has a
		// create spec and always has — but nothing in the app pointed at it, so
		// the only way in was to know the URL. A document type with no tab is a
		// document type nobody can raise.
		//
		// Beside Stock counts because the two are the pair a stockkeeper works
		// in: a count says what is actually there, an entry moves it.
		{ label: 'Stock entries', to: '/documents/stock-entry' },
		{ label: 'Stock counts', to: '/documents/stock-reconciliation' },
		// Filed here rather than under Purchasing because the person who notices
		// the shelf is empty is the one who raises the request; it appears in both
		// strips for that reason.
		{ label: 'Item requests', to: '/documents/material-request' },
		{ label: 'Reorder levels', to: '/reorder' },
	],
	purchasing: [
		// Buying now *happens* here rather than being summarised here — a manager
		// posts the purchase and the store keeper confirms what arrived, both on
		// this one screen. It leads the strip for that reason; the tabs after it
		// are the paperwork you go and read afterwards.
		{ label: 'Purchases', to: '/purchasing' },
		// Asking for stock, which is all a material request is. It is not a way
		// to buy anything and never was — the buying is the tab before this one.
		{ label: 'Item requests', to: '/documents/material-request' },
		{ label: 'Receipts', to: '/documents/purchase-receipt' },
		// The ERPNext-level list of what Purchases posted. Read-only from here:
		// raising one by hand would skip the store's confirmation, so the New
		// button is gone and the screen says where to go instead — see
		// `documents.NOT_CREATABLE`.
		{ label: 'Invoices', to: '/documents/purchase-invoice' },
		{ label: 'Landed costs', to: '/documents/landed-cost-voucher' },
		{ label: 'Suppliers', to: '/suppliers' },
	],
	sales: [
		{ label: 'Overview', to: '/sales' },
		// Ahead of the fulfilment tabs, in the order a sale actually happens: a
		// price is given before anything is delivered or invoiced.
		{ label: 'Quotations', to: '/documents/quotation' },
		// The shop's own delivery worklist — one drop, one address, one status —
		// ahead of ERPNext's Delivery Notes, which this shop does not raise.
		{ label: 'Delivery', to: '/deliveries' },
		{ label: 'Delivery notes', to: '/documents/delivery-note' },
		// Delivery Trips used to sit here. Removed at the shop's request: they
		// run one rider, one parcel, one address, so a tab for grouping several
		// invoices onto a van was a control nobody used and everybody had to
		// read past. The doctype and `/documents/delivery-trip` both still work
		// for anyone who has the URL — this is the strip getting shorter, not a
		// feature being deleted.
		{ label: 'Invoices', to: '/documents/sales-invoice' },
		{ label: 'Payments', to: '/documents/payment-entry' },
		{ label: 'Returns', to: '/returns' },
		{ label: 'Customers', to: '/customers' },
		// Filed under Sales rather than Purchasing: these are raised by a cashier
		// to complete a sale that is happening at that moment, and the person who
		// looks for them is the one who was standing at the till.
		{ label: 'Neighbours', to: '/neighbours' },
	],
	accounts: [
		{ label: 'Balances', to: '/accounts' },
		// The one you act on, before the one you read. `/credit` takes the money;
		// the Receivables report explains the number.
		{ label: 'Credit', to: '/credit' },
		{ label: 'Receivables', to: '/accounts/receivables' },
		{ label: 'Payables', to: '/accounts/payables' },
		{ label: 'Payments', to: '/documents/payment-entry' },
		{ label: 'Accounts', to: '/masters/account' },
	],
}

/**
 * Which module a document type belongs to.
 *
 * Which module a document type belongs to, whether or not it has a tab of its
 * own. Orders no longer do — this shop invoices directly — but the route still
 * works from the hub's index, and landing there should still show the module it
 * belongs to rather than no context at all.
 *
 * The till's own POS documents are absent deliberately: they belong to a shift
 * rather than to a back-office module.
 */
const DOCUMENT_MODULE = {
	quotation: 'sales',
	'sales-order': 'sales',
	'delivery-note': 'sales',
	'delivery-trip': 'sales',
	'sales-invoice': 'sales',
	'payment-entry': 'sales',
	'material-request': 'purchasing',
	'purchase-order': 'purchasing',
	'purchase-receipt': 'purchasing',
	'purchase-invoice': 'purchasing',
	'landed-cost-voucher': 'purchasing',
	'stock-entry': 'inventory',
	'stock-reconciliation': 'inventory',
}

/**
 * Which module a route belongs to, so the right tab strip renders.
 *
 * `current` is the module you are already in, and it wins whenever the path you
 * are opening is one of that module's own tabs. Some destinations genuinely
 * belong to two modules — a material request is raised by whoever sees the empty
 * shelf and read by whoever does the buying, so it is listed under both
 * Inventory and Purchasing. Deriving the module from the path alone meant
 * opening it from Inventory swapped the entire strip to Purchasing, which reads
 * as the tabs changing under you the moment you touch one.
 *
 * Staying put is the right answer: you asked for a page, not for a different
 * section.
 */
export function moduleFor(path, current = null) {
	if (current && (MODULE_TABS[current] || []).some((tab) => tab.to === path)) {
		return current
	}
	return _moduleForPath(path)
}

function _moduleForPath(path) {
	if (path.startsWith('/documents/')) {
		return DOCUMENT_MODULE[path.split('/')[2]] || null
	}
	if (path.startsWith('/expenses')) return 'pos'
	if (path.startsWith('/suppliers')) return 'purchasing'
	if (path.startsWith('/masters/account')) return 'accounts'
	if (
		path.startsWith('/inventory') ||
		path.startsWith('/reorder') ||
		path.startsWith('/pricing') ||
		path.startsWith('/items') ||
		path.startsWith('/item-groups') ||
		path.startsWith('/barcodes')
	)
		return 'inventory'
	if (path.startsWith('/purchasing')) return 'purchasing'
	if (
		path.startsWith('/sales') ||
		path.startsWith('/customers') ||
		path.startsWith('/returns') ||
		path.startsWith('/neighbours') ||
		path.startsWith('/deliveries')
	)
		return 'sales'
	if (path.startsWith('/accounts') || path.startsWith('/credit')) return 'accounts'
	return null
}
