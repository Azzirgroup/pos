import { createRouter, createWebHistory } from 'vue-router'

/**
 * Every module is lazily chunked. The till is the only screen a cashier loads
 * on a slow connection, so it must not pay for the back-office code.
 */
const routes = [
	{ path: '/', redirect: '/pos' },
	{ path: '/pos', name: 'Sell', meta: { title: 'POS' }, component: () => import('@/views/Sell.vue') },
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
]

export default createRouter({
	history: createWebHistory('/pos'),
	routes,
})
