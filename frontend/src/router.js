import { createRouter, createWebHistory } from 'vue-router'

/**
 * Every module is lazily chunked. The till is the only screen a cashier loads
 * on a slow connection, so it must not pay for the back-office code.
 */
const routes = [
	// The till stays the landing screen. A cashier opening a bookmarked link on a
	// slow connection should not first pay for a dashboard's worth of SQL — the
	// dashboard is one click away on the rail, which is where a manager starts.
	{ path: '/', redirect: '/pos' },
	{ path: '/pos', name: 'Sell', meta: { title: 'POS' }, component: () => import('@/views/Sell.vue') },
	{
		path: '/dashboard',
		name: 'Dashboard',
		meta: { title: 'Dashboard' },
		component: () => import('@/views/Dashboard.vue'),
	},
	{
		// The document type is a route parameter, not eleven routes: they differ
		// only in which registry key they carry.
		path: '/documents/:key?',
		name: 'Documents',
		meta: { title: 'Documents' },
		component: () => import('@/views/Documents.vue'),
	},
	{
		path: '/inventory',
		name: 'Inventory',
		meta: { title: 'Inventory' },
		component: () => import('@/views/Inventory.vue'),
	},
	{
		path: '/reorder',
		name: 'Reorder',
		meta: { title: 'Reorder levels' },
		component: () => import('@/views/Reorder.vue'),
	},
	{
		path: '/purchasing',
		name: 'Purchasing',
		meta: { title: 'Purchasing' },
		component: () => import('@/views/Purchasing.vue'),
	},
	{
		path: '/sales',
		name: 'Sales',
		meta: { title: 'Sales' },
		component: () => import('@/views/Sales.vue'),
	},
	{
		path: '/customers',
		name: 'Customers',
		meta: { title: 'Customers' },
		component: () => import('@/views/Customers.vue'),
	},
	{
		path: '/accounts',
		name: 'Accounts',
		meta: { title: 'Accounts' },
		component: () => import('@/views/Accounts.vue'),
	},
	{
		path: '/pricing',
		name: 'Pricing',
		meta: { title: 'Price updates' },
		component: () => import('@/views/Pricing.vue'),
	},
	{
		// The records a shop maintains itself. Same shape as /documents: the type
		// is a parameter, not five near-identical routes.
		path: '/masters/:key?',
		name: 'Masters',
		meta: { title: 'Records' },
		component: () => import('@/views/Masters.vue'),
	},
	{
		path: '/barcodes',
		name: 'Barcodes',
		meta: { title: 'Barcodes' },
		component: () => import('@/views/Barcodes.vue'),
	},
	// These are reports with a fixed subject, so they reuse the report view
	// rather than duplicating a table five times.
	{
		path: '/inventory/movement',
		meta: { title: 'Stock movement', report: 'stock_movement' },
		component: () => import('@/views/Reports.vue'),
	},
	{
		path: '/purchasing/requests',
		meta: { title: 'Material requests', report: 'below_reorder' },
		component: () => import('@/views/Reports.vue'),
	},
	{
		path: '/accounts/receivables',
		meta: { title: 'Receivables', report: 'receivables' },
		component: () => import('@/views/Reports.vue'),
	},
	{
		path: '/accounts/payables',
		meta: { title: 'Payables', report: 'payables' },
		component: () => import('@/views/Reports.vue'),
	},
	{
		path: '/reports',
		name: 'Reports',
		meta: { title: 'Reports' },
		component: () => import('@/views/Reports.vue'),
	},
	{
		path: '/previous-shifts',
		name: 'PreviousShifts',
		meta: { title: 'Previous shifts' },
		component: () => import('@/views/PreviousShifts.vue'),
	},
	{
		path: '/suppliers',
		name: 'Suppliers',
		meta: { title: 'Suppliers' },
		component: () => import('@/views/Suppliers.vue'),
	},
	{
		path: '/neighbours',
		name: 'Neighbours',
		meta: { title: 'Neighbour purchases' },
		component: () => import('@/views/Neighbours.vue'),
	},
	{
		path: '/settings',
		name: 'Settings',
		meta: { title: 'Settings' },
		component: () => import('@/views/Settings.vue'),
	},
]

export default createRouter({
	history: createWebHistory('/pos'),
	routes,
})
