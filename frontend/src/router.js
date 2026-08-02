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
		path: '/returns',
		name: 'Returns',
		meta: { title: 'Returns' },
		component: () => import('@/views/Returns.vue'),
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
		// The Items tab under Inventory. Same screen as Records, with the type
		// already chosen and its picker hidden — arriving here from a module tab,
		// the other record types are not what you came for.
		path: '/items',
		name: 'Items',
		meta: { title: 'Items', masterKey: 'item', focusedMaster: true },
		component: () => import('@/views/Masters.vue'),
	},
	{
		// The categories every item form asks for. Same screen as Records with the
		// type fixed, exactly like /items.
		path: '/item-groups',
		name: 'ItemGroups',
		meta: { title: 'Item groups', masterKey: 'item_group', focusedMaster: true },
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
		// Money out of the drawer that is not a purchase. Its own page rather than
		// a tab inside the closing sheet — see the component for why.
		path: '/expenses',
		name: 'TillExpenses',
		meta: { title: 'Expenses' },
		component: () => import('@/views/TillExpenses.vue'),
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

const router = createRouter({
	history: createWebHistory('/pos'),
	routes,
})

/**
 * Recover from a deploy that happened under an open tab.
 *
 * Every screen is a dynamic import of a hashed chunk, and a rebuild renames all
 * of them. A till left open all day is therefore running an index chunk that
 * asks for `Masters-BB8x8YCo.js` when the server now has `Masters-Ba2H_eUg.js`,
 * and the navigation dies with "error loading dynamically imported module" —
 * the tab looks broken to a cashier who has done nothing wrong, and the fix is
 * a hard reload nobody would think of.
 *
 * Reloading lands on the freshly rendered page (`pos.html` is `no_cache`), which
 * carries the new chunk names. Guarded by a session flag so a genuinely missing
 * chunk — a bad deploy rather than a stale tab — fails visibly instead of
 * reloading forever; the flag clears on the next successful navigation.
 */
const RELOAD_FLAG = 'cosmetics:chunk-reload'

router.onError((error) => {
	const message = String(error?.message || '')
	const isChunkMiss =
		/dynamically imported module|Importing a module script failed|Failed to fetch/i.test(message)

	if (!isChunkMiss || sessionStorage.getItem(RELOAD_FLAG)) return

	sessionStorage.setItem(RELOAD_FLAG, '1')
	// Reload where we stand rather than navigating to the route that failed.
	// Building a URL here means constructing the app's own base by hand, and
	// getting that wrong sends a cashier out of the app entirely — a far worse
	// outcome than the tab they are already looking at reloading itself. The
	// failed navigation never changed the address bar, so this comes back to the
	// same screen with the new chunks, and the tap works the second time.
	window.location.reload()
})

router.afterEach(() => sessionStorage.removeItem(RELOAD_FLAG))

export default router
