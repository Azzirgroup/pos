/**
 * Keeping the cart and the held tickets across a reload.
 *
 * A till is a browser tab in a shop with unreliable wifi. It gets refreshed by
 * accident, the network drops mid-sale, the tablet sleeps and the tab is
 * reclaimed. Until now every one of those threw away a cart the customer was
 * standing in front of, and the cashier had to re-scan the basket from memory.
 * Held tickets went the same way — parked "until they come back", gone by the
 * time they did.
 *
 * ## Why localStorage and not the server
 *
 * The cart is not a document. Writing every keystroke to the server would need
 * a doctype, a submit path and a cleanup job for carts nobody finished, and it
 * would still fail in exactly the case this exists for: no network. The browser
 * already has durable storage that survives a reload and a closed tab, works
 * offline, and costs nothing to write.
 *
 * ## Why the key is scoped
 *
 * A till is shared. Keying on the *user and the till* means a cashier who signs
 * out mid-cart does not hand their basket to whoever signs in next, and two
 * counters on one machine cannot read each other's holds. A cart restored to
 * the wrong person is worse than a cart lost.
 *
 * ## What is deliberately not restored
 *
 * Nothing that can go stale into money: prices and stock are re-read from the
 * catalog on load, and a restored line keeps only what the cashier chose — the
 * item, the quantity, the unit and any rate they typed themselves.
 */

const VERSION = 2

/** Give up rather than restore something written by an older, different shape. */
function isCurrent(payload) {
	return payload && payload.v === VERSION && Array.isArray(payload.lines)
}

/**
 * `user` and `till` come from the session; both may be unknown on first paint,
 * and an anonymous key is still better than none — it just does not survive a
 * user switch, which is the safe direction to fail in.
 */
export function storageKey(user, till) {
	return `cosmestics:cart:${user || 'anon'}:${till || 'no-till'}`
}

export function loadCart(key) {
	try {
		const raw = window.localStorage.getItem(key)
		if (!raw) return null
		const payload = JSON.parse(raw)
		if (!isCurrent(payload)) {
			window.localStorage.removeItem(key)
			return null
		}
		return payload
	} catch {
		// Storage disabled, quota exceeded, or corrupt JSON. A till that cannot
		// remember is the situation we were already in; one that refuses to open
		// is worse.
		return null
	}
}

export function saveCart(key, payload) {
	try {
		window.localStorage.setItem(key, JSON.stringify({ v: VERSION, ...payload }))
	} catch {
		/* Out of quota or private mode — losing persistence must never break a sale. */
	}
}

export function clearStored(key) {
	try {
		window.localStorage.removeItem(key)
	} catch {
		/* nothing to do */
	}
}

/**
 * The basket of a sale that is currently being posted.
 *
 * The till clears the cart the moment payment is taken, so the next customer
 * can be served while the invoice posts behind them. That is the right trade at
 * a counter — but it means that between "paid" and "posted" the only copy of
 * the basket lives in a local variable inside the in-flight function. If the
 * post fails, or the tab is reloaded while it is in the air, that copy goes
 * with it and the cashier re-scans a basket the customer has already paid for.
 *
 * So the basket is written here first and removed once the server has
 * answered — a crash-proof copy of the one thing that cannot be reconstructed.
 * Anything found here on the next load is a sale whose outcome nobody knows.
 */
function pendingKey(key) {
	return `${key}:pending`
}

export function savePending(key, snapshot) {
	try {
		window.localStorage.setItem(pendingKey(key), JSON.stringify({ v: VERSION, ...snapshot }))
	} catch {
		/* Best-effort: never block a sale over a failed write. */
	}
}

export function loadPending(key) {
	try {
		const raw = window.localStorage.getItem(pendingKey(key))
		if (!raw) return null
		const payload = JSON.parse(raw)
		if (!isCurrent(payload)) {
			window.localStorage.removeItem(pendingKey(key))
			return null
		}
		return payload
	} catch {
		return null
	}
}

export function clearPending(key) {
	try {
		window.localStorage.removeItem(pendingKey(key))
	} catch {
		/* nothing to do */
	}
}

/**
 * Is the page on its way out?
 *
 * A sale posting when the tab navigates away has its request cancelled by the
 * browser, and the rejection arrives in the dying page looking exactly like a
 * network failure. It is not the same thing: a failed request definitely did
 * not post, whereas a cancelled one may well have reached the server and
 * committed — the answer just had nowhere to go. Treating the second as the
 * first hands the basket straight back to the cashier, who charges a customer
 * that ERPNext has already invoiced.
 *
 * `pagehide` rather than `beforeunload` alone, because it also fires when a
 * tablet reclaims a backgrounded tab, which is one of the ways a till dies
 * without anyone touching it. Reset on `pageshow`, since a page restored from
 * the back/forward cache is alive again and its next sale is an ordinary one.
 */
let unloading = false

if (typeof window !== 'undefined') {
	window.addEventListener('pagehide', () => {
		unloading = true
	})
	window.addEventListener('beforeunload', () => {
		unloading = true
	})
	window.addEventListener('pageshow', () => {
		unloading = false
	})
}

export function isUnloading() {
	return unloading
}
