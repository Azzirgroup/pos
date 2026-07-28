/**
 * Activities per module, shown as sub-tabs.
 *
 * Kept as data rather than markup so the rail, the router and the sub-tabs
 * cannot drift out of step — every entry here has a matching route.
 */
export const MODULE_TABS = {
	inventory: [
		{ label: 'Stock levels', to: '/inventory' },
		{ label: 'Reorder levels', to: '/reorder' },
		{ label: 'Price updates', to: '/pricing' },
		{ label: 'Stock movement', to: '/inventory/movement' },
	],
	purchasing: [
		{ label: 'Overview', to: '/purchasing' },
		{ label: 'Material requests', to: '/purchasing/requests' },
	],
	sales: [
		{ label: 'Invoices', to: '/sales' },
		{ label: 'Customers', to: '/customers' },
	],
	accounts: [
		{ label: 'Balances', to: '/accounts' },
		{ label: 'Receivables', to: '/accounts/receivables' },
		{ label: 'Payables', to: '/accounts/payables' },
	],
}

/** Which module a route belongs to, so the right tab strip renders. */
export function moduleFor(path) {
	if (path.startsWith('/inventory') || path.startsWith('/reorder') || path.startsWith('/pricing'))
		return 'inventory'
	if (path.startsWith('/purchasing')) return 'purchasing'
	if (path.startsWith('/sales') || path.startsWith('/customers')) return 'sales'
	if (path.startsWith('/accounts')) return 'accounts'
	return null
}
