/**
 * A small read cache for the screens you keep coming back to.
 *
 * The server is not the slow part — the endpoints behind these screens answer
 * in tens of milliseconds. The wait is the round trip: a shop in Nairobi
 * talking to a server in Frankfurt pays a few hundred milliseconds *per
 * request*, every time a tab is opened, including the tab that was open ten
 * seconds ago.
 *
 * So: **stale-while-revalidate**. A cached answer is returned immediately and a
 * fresh one is fetched in the background; when it lands the screen updates
 * itself. Revisiting a tab is instant, and what you end up looking at is still
 * current within one round trip.
 *
 * ## What is allowed in here, and what is not
 *
 * Only the methods named in `CACHEABLE`. It is an explicit list rather than a
 * pattern because the cost of a wrong guess is not symmetric: a slightly stale
 * dashboard is a non-event, while a stale drawer total, stock figure or open
 * shift is a cashier making a decision on a number that is not true any more.
 * Anything to do with the till — `pos.*`, `shift.*`, `returns.*`, `sourcing.*`
 * — is deliberately absent and always goes to the server.
 *
 * ## Invalidation
 *
 * Any call that is *not* in the list is treated as a write and empties the
 * cache. Blunt, and right: after saving something the next screen must show it,
 * and a shop is not making so many requests that rebuilding the cache costs
 * anything noticeable. Getting clever here — invalidating by doctype, say —
 * would mean maintaining a second map of which endpoint touches what, and the
 * first entry anybody forgot to add would show stale data with no clue why.
 */

/** How long an entry may be served before it is considered stale. */
const TTL_MS = 60_000

/**
 * Read endpoints worth remembering between visits.
 *
 * Chosen on two grounds: the screen is revisited often, and a value up to a
 * minute old changes no decision. Reports and dashboards qualify; money at the
 * counter does not.
 */
const CACHEABLE = new Set([
	// Dashboard tabs — the most revisited screens in the app.
	'cosmestics.api.dashboard.overview',
	'cosmestics.api.dashboard.filters',
	// Today is the one tab where a minute of staleness is actually noticeable,
	// but stale-while-revalidate answers that: it paints immediately and
	// corrects itself a round trip later, which is what "live" looks like.
	'cosmestics.api.dashboard.today',
	'cosmestics.api.dashboard.sales',
	'cosmestics.api.dashboard.branches',
	'cosmestics.api.dashboard.warehouses',
	'cosmestics.api.dashboard.procurement',
	'cosmestics.api.dashboard.accounts',
	// Module lists and reports — read, shared, never edited in place.
	'cosmestics.api.modules.sales',
	'cosmestics.api.modules.inventory',
	'cosmestics.api.modules.purchasing',
	'cosmestics.api.modules.accounts',
	'cosmestics.api.modules.warehouses',
	'cosmestics.api.documents.list_documents',
	'cosmestics.api.documents.list_types',
	'cosmestics.api.documents.insights',
	'cosmestics.api.reports.list_reports',
	'cosmestics.api.reports.run',
	'cosmestics.api.barcodes.list_items',
	// Lookups that barely change and are asked for by every filter bar.
	'cosmestics.api.master.list_types',
	'cosmestics.api.pricing.get_filters',
	'cosmestics.api.pricing.get_price_list_options',
	'cosmestics.api.reorder.get_warehouse_tree',
	'cosmestics.api.settings.link_options',
	'cosmestics.api.session.context',
	'cosmestics.api.session.me',
	// Crosses the network twice — to this server and on to the WhatsApp bridge.
	// Easily the slowest read in the app and the one that changes least.
	'cosmestics.api.notifications.list_groups',
	'cosmestics.api.notifications.contact_numbers',
])

/**
 * Two deliberate omissions, for a reason that is not staleness.
 *
 * `pricing.get_prices` and `master.list_records` feed tables the user then
 * edits. A cache hands every caller the *same object*, so a screen that mutates
 * a row in place would quietly rewrite what the next screen reads — a bug with
 * no visible cause and no request to look at. Read-only screens only.
 */


/** method + args → { at, value } */
const store = new Map()
/** method + args → Promise, so two components asking at once make one request. */
const inflight = new Map()

function keyFor(method, args) {
	return args && Object.keys(args).length ? `${method}::${JSON.stringify(args)}` : method
}

export function clearCache() {
	store.clear()
}

/**
 * @param method  whitelisted dotted path
 * @param args    call arguments
 * @param fetcher () => Promise, the real request
 */
export function withCache(method, args, fetcher) {
	if (!CACHEABLE.has(method)) {
		// A write. Let it run, then drop everything — the next read must see it.
		return fetcher().then(
			(value) => {
				clearCache()
				return value
			},
			(error) => {
				// Cleared on failure too: a half-applied write is exactly the case
				// where a remembered "before" picture is most misleading.
				clearCache()
				throw error
			},
		)
	}

	const key = keyFor(method, args)
	const hit = store.get(key)
	const fresh = hit && Date.now() - hit.at < TTL_MS

	// Deduplicate concurrent identical reads regardless of cache state.
	if (!inflight.has(key)) {
		const request = fetcher()
			.then((value) => {
				store.set(key, { at: Date.now(), value })
				return value
			})
			.finally(() => inflight.delete(key))
		inflight.set(key, request)
		// Nobody is waiting on the background copy, so an error here must not
		// surface as an unhandled rejection.
		if (hit) request.catch(() => {})
	}

	// Something cached and still warm: hand it back now, let the refetch land.
	if (hit && fresh) return Promise.resolve(hit.value)
	// Stale or missing: wait for the real answer, but fall back to whatever we
	// had if the network fails — a screen of slightly old figures beats a screen
	// of error text when the connection drops at a counter.
	return inflight.get(key).catch((error) => {
		if (hit) return hit.value
		throw error
	})
}
