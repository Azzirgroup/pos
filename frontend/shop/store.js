import { reactive } from 'vue'
import { get, post } from './api'

/**
 * The shop's shared state: who is signed in, their cart, and which overlay
 * is open. One reactive object — small enough that a store library would be
 * ceremony.
 */
export const state = reactive({
	ready: false,
	customer: null,
	cart: null,
	cartOpen: false,
	auth: { open: false, mode: 'signin', reason: '' },
	busy: {},
	toasts: [],
})

let pending = null // what to do after signing in (e.g. the add-to-cart that prompted it)

export function toast(message, tone = 'ok') {
	const id = Math.random().toString(36).slice(2)
	state.toasts.push({ id, message, tone })
	setTimeout(() => {
		const i = state.toasts.findIndex((t) => t.id === id)
		if (i !== -1) state.toasts.splice(i, 1)
	}, tone === 'error' ? 6000 : 3500)
}

export async function boot() {
	try {
		const [me, cart] = await Promise.all([get('shop_account.me'), get('shop_orders.cart')])
		state.customer = me.customer
		state.cart = cart
	} catch (e) {
		/* the shop still works for browsing */
	}
	state.ready = true
}

export function askToSignIn(reason, then) {
	pending = then || null
	state.auth = { open: true, mode: 'signin', reason: reason || '' }
}

export async function afterSignIn(customer) {
	state.customer = customer
	state.auth.open = false
	state.cart = await get('shop_orders.cart')
	toast(`Welcome, ${customer.first_name}`)
	if (pending) {
		const run = pending
		pending = null
		await run()
	}
}

export async function signOut() {
	await post('shop_account.logout')
	state.customer = null
	state.cart = await get('shop_orders.cart')
	toast('Signed out')
	if (location.pathname.startsWith('/shop/account') || location.pathname.startsWith('/shop/orders') || location.pathname.startsWith('/shop/checkout')) {
		location.href = '/shop'
	}
}

/** Add `qty` of a product, asking the shopper to sign in first if needed. */
export async function addToCart(code, qty = 1, { open = true } = {}) {
	if (!state.customer) {
		askToSignIn('Sign in to add items to your cart', () => addToCart(code, qty, { open }))
		return false
	}
	state.busy[code] = true
	try {
		state.cart = await post('shop_orders.set_line', { item_code: code, qty, add: 1 })
		if (open) state.cartOpen = true
		else toast('Added to your cart')
		return true
	} catch (e) {
		if (e.status === 401) askToSignIn('Sign in to add items to your cart', () => addToCart(code, qty, { open }))
		else toast(e.message, 'error')
		return false
	} finally {
		state.busy[code] = false
	}
}

export async function setQty(code, qty) {
	state.busy[code] = true
	try {
		state.cart = await post('shop_orders.set_line', { item_code: code, qty })
	} catch (e) {
		toast(e.message, 'error')
		state.cart = await get('shop_orders.cart')
	} finally {
		state.busy[code] = false
	}
}

export function openCart() {
	state.cartOpen = true
}

/** "2 days 4 hours", "3 hours 12 min", "8 min" — how long an order sat somewhere. */
export function duration(seconds) {
	if (seconds === null || seconds === undefined) return ''
	const s = Math.max(0, Math.floor(seconds))
	const d = Math.floor(s / 86400)
	const h = Math.floor((s % 86400) / 3600)
	const m = Math.floor((s % 3600) / 60)
	const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`
	if (d) return h ? `${plural(d, 'day')} ${plural(h, 'hour')}` : plural(d, 'day')
	if (h) return m ? `${plural(h, 'hour')} ${m} min` : plural(h, 'hour')
	if (m) return `${m} min`
	return 'under a minute'
}

export function when(value) {
	if (!value) return ''
	const d = new Date(value.replace(' ', 'T'))
	if (isNaN(d)) return value
	return d.toLocaleString('en-KE', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
}

/** `254712345678` → `0712 345 678`, how people write their own number. */
export function localPhone(p) {
	const d = String(p || '').replace(/\D/g, '')
	const local = d.startsWith('254') && d.length === 12 ? '0' + d.slice(3) : d
	return local.length === 10 ? `${local.slice(0, 4)} ${local.slice(4, 7)} ${local.slice(7)}` : p || ''
}
