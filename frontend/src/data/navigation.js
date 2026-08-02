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
		{ label: 'Stock counts', to: '/documents/stock-reconciliation' },
		// Filed here rather than under Purchasing because the person who notices
		// the shelf is empty is the one who raises the request; it appears in both
		// strips for that reason.
		{ label: 'Material requests', to: '/documents/material-request' },
		{ label: 'Reorder levels', to: '/reorder' },
	],
	purchasing: [
		{ label: 'Overview', to: '/purchasing' },
		{ label: 'Requests', to: '/documents/material-request' },
		{ label: 'Orders', to: '/documents/purchase-order' },
		{ label: 'Receipts', to: '/documents/purchase-receipt' },
		{ label: 'Bills', to: '/documents/purchase-invoice' },
		{ label: 'Landed costs', to: '/documents/landed-cost-voucher' },
		{ label: 'Suppliers', to: '/suppliers' },
	],
	sales: [
		{ label: 'Overview', to: '/sales' },
		{ label: 'Orders', to: '/documents/sales-order' },
		{ label: 'Deliveries', to: '/documents/delivery-note' },
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
		{ label: 'Receivables', to: '/accounts/receivables' },
		{ label: 'Payables', to: '/accounts/payables' },
		{ label: 'Payments', to: '/documents/payment-entry' },
		{ label: 'Accounts', to: '/masters/account' },
	],
}

/**
 * Which module a document type belongs to.
 *
 * Only the types that appear as a module tab are listed. The rest — the till's
 * own POS documents — are reached from the hub's own index, because they belong
 * to a shift rather than to a back-office module.
 */
const DOCUMENT_MODULE = {
	'sales-order': 'sales',
	'delivery-note': 'sales',
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
		path.startsWith('/neighbours')
	)
		return 'sales'
	if (path.startsWith('/accounts')) return 'accounts'
	return null
}
