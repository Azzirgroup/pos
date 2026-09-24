<script setup>
import { ref, reactive, computed, watch, onBeforeUnmount } from 'vue'
import { state, askToSignIn, toast, localPhone } from '../store'
import { get, post } from '../api'
import Icon from '../components/Icon.vue'
import QtyStepper from '../components/QtyStepper.vue'
import { setQty } from '../store'

/**
 * Checkout, in two steps and a payment:
 *   1. How it reaches you — delivery to an area (with its fee) or pickup.
 *   2. Review and pay — an M-Pesa prompt to the customer's phone.
 * The payment screen then waits for Safaricom (asking the shop every 3s)
 * and moves to the order's tracking page when it is confirmed.
 */
const step = ref(1)
const busy = ref(false)
const error = ref('')
const cart = computed(() => state.cart || {})
const form = reactive({ fulfilment: 'Delivery', area: '', address: '', landmark: '', phone: '', note: '' })
const payPhone = ref('')
const pay = reactive({ open: false, request: null, status: '', message: '', seconds: 0, amount: 0, order: null })
let timer = null
let clock = null

// Fill the form from the saved draft once the cart has loaded.
watch(
	() => state.cart,
	(c) => {
		if (!c || form._filled) return
		form._filled = true
		form.fulfilment = c.fulfilment || 'Delivery'
		form.area = c.area || ''
		form.address = c.address || ''
		form.landmark = c.landmark || ''
		form.phone = localPhone(c.phone || state.customer?.phone || '')
		form.note = c.note || ''
		payPhone.value = localPhone(c.phone || state.customer?.phone || '')
	},
	{ immediate: true }
)

const area = computed(() => (cart.value.areas || []).find((a) => a.name === form.area))
/** On step 1 the fee is not saved yet: preview what the chosen option will cost. */
const previewFee = computed(() => {
	if (form.fulfilment === 'Pickup') return 0
	if (cart.value.areas?.length) return area.value ? area.value.fee : null
	return cart.value.flat_fee || 0
})
const money = (n) => `${cart.value.currency || 'KES'} ${Math.round(n).toLocaleString('en-KE')}`
const shownTotal = computed(() => {
	if (step.value === 2 || previewFee.value === null) return cart.value.total_label
	return money((cart.value.subtotal || 0) + previewFee.value)
})
const needsSignIn = computed(() => state.ready && !state.customer)
const empty = computed(() => state.ready && state.customer && !(cart.value.lines || []).length)

async function saveDetails() {
	busy.value = true
	error.value = ''
	try {
		state.cart = await post('shop_orders.set_fulfilment', {
			fulfilment: form.fulfilment,
			area: form.fulfilment === 'Delivery' ? form.area : null,
			address: form.address,
			landmark: form.landmark,
			phone: form.phone,
			note: form.note,
		})
		payPhone.value = payPhone.value || form.phone
		step.value = 2
		window.scrollTo({ top: 0, behavior: 'smooth' })
	} catch (e) {
		error.value = e.message
	} finally {
		busy.value = false
	}
}

async function startPayment() {
	busy.value = true
	error.value = ''
	try {
		const res = await post('shop_payments.pay', { phone: payPhone.value })
		Object.assign(pay, { open: true, request: res.request, status: 'Pending', message: '', seconds: 0, amount: res.amount, phone: res.phone })
		poll()
		clock = setInterval(() => pay.seconds++, 1000)
	} catch (e) {
		error.value = e.message
	} finally {
		busy.value = false
	}
}

function poll() {
	clearTimeout(timer)
	timer = setTimeout(async () => {
		try {
			const res = await get('shop_payments.payment_status', { request: pay.request })
			pay.status = res.status
			pay.message = res.message
			pay.order = res.order
			if (res.status === 'Paid') {
				clearInterval(clock)
				state.cart = await get('shop_orders.cart')
				setTimeout(() => (location.href = `/shop/orders/${encodeURIComponent(res.order)}?placed=1`), 2200)
				return
			}
			if (res.status !== 'Pending') {
				clearInterval(clock)
				return
			}
		} catch (e) {
			/* keep asking; a blip should not fail the payment */
		}
		poll()
	}, 3000)
}

function closePay() {
	clearTimeout(timer)
	clearInterval(clock)
	pay.open = false
}
onBeforeUnmount(closePay)

const masked = computed(() => {
	const p = localPhone(pay.phone || payPhone.value || '').replace(/\s/g, '')
	return p.length > 6 ? `${p.slice(0, 4)} ••• ${p.slice(-3)}` : p
})
</script>

<template>
	<div class="co wide">
		<nav class="crumbs"><a href="/shop">Home</a><span>/</span><span class="here">Checkout</span></nav>

		<div v-if="!state.ready" class="co-loading"><span class="spinner" /> Loading your cart…</div>

		<div v-else-if="needsSignIn" class="co-empty">
			<Icon name="lock" size="i-xl" />
			<h1>Sign in to check out</h1>
			<p>Your cart, payments and order tracking live in your account.</p>
			<button type="button" class="btn btn-primary" @click="askToSignIn('Sign in to check out')">Sign in or create account</button>
		</div>

		<div v-else-if="empty" class="co-empty">
			<Icon name="bag" size="i-xl" />
			<h1>Your cart is empty</h1>
			<p>Find something you love, then come back here to pay with M-Pesa.</p>
			<a class="btn btn-primary" href="/shop/catalog">Start shopping</a>
		</div>

		<div v-else class="co-grid">
			<section class="co-main">
				<ol class="co-steps">
					<li :class="{ on: step === 1, done: step > 1 }"><span>1</span>Delivery</li>
					<li :class="{ on: step === 2 }"><span>2</span>Review & pay</li>
				</ol>

				<form v-if="step === 1" class="co-card form" @submit.prevent="saveDetails">
					<h2>How should we get it to you?</h2>
					<div class="choice-cards">
						<label class="choice" :class="{ on: form.fulfilment === 'Delivery' }">
							<input v-model="form.fulfilment" type="radio" value="Delivery" />
							<Icon name="truck" />
							<span><b>Delivery</b><small>Our rider brings it to you · {{ cart.areas?.length ? 'fee by area' : cart.flat_fee_label }}</small></span>
						</label>
						<label class="choice" :class="{ on: form.fulfilment === 'Pickup' }">
							<input v-model="form.fulfilment" type="radio" value="Pickup" />
							<Icon name="store" />
							<span><b>Pick up at the shop</b><small>Free - we'll tell you when it's ready</small></span>
						</label>
					</div>

					<template v-if="form.fulfilment === 'Delivery'">
						<p v-if="cart.areas?.length" class="form-label">Delivery Area</p>
						<div v-if="cart.areas?.length" class="area-grid">
							<label v-for="a in cart.areas" :key="a.name" class="area" :class="{ on: form.area === a.name }">
								<input v-model="form.area" type="radio" :value="a.name" />
								<b>{{ a.label }}</b>
								<span>{{ a.fee ? a.fee_label : 'Free' }}<template v-if="a.eta"> · {{ a.eta }}</template></span>
							</label>
						</div>
						<label>Delivery Address<textarea v-model="form.address" rows="2" required placeholder="Building, street, house or office number" /></label>
						<label>Landmark <span class="opt">(Optional)</span><input v-model="form.landmark" placeholder="Opposite the church, next to …" /></label>
					</template>
					<div v-else-if="cart.pickup_note" class="pickup-note"><Icon name="pin" size="i-md" /><span>{{ cart.pickup_note }}</span></div>

					<label>Phone Number For This Order<input v-model.trim="form.phone" type="tel" inputmode="tel" required placeholder="0712 345 678" /><small>{{ form.fulfilment === 'Delivery' ? 'The rider calls this number.' : 'We call this number when it is ready.' }}</small></label>
					<label>Note For The Shop <span class="opt">(Optional)</span><textarea v-model="form.note" rows="2" placeholder="Gift wrap, best time to call…" /></label>
					<p v-if="error" class="form-error">{{ error }}</p>
					<button class="btn btn-primary btn-block" :disabled="busy || (form.fulfilment === 'Delivery' && cart.areas?.length && !form.area)">{{ busy ? 'Saving…' : 'Continue to payment' }}</button>
				</form>

				<div v-else class="co-card">
					<div class="review-head">
						<h2>Review your order</h2>
						<button type="button" class="link-btn" @click="step = 1">Edit details</button>
					</div>
					<dl class="review">
						<div><dt>{{ cart.fulfilment === 'Pickup' ? 'Pickup' : 'Delivery to' }}</dt>
							<dd v-if="cart.fulfilment === 'Pickup'">At the shop{{ cart.pickup_note ? ` - ${cart.pickup_note}` : '' }}</dd>
							<dd v-else>{{ cart.address }}<br /><span class="muted">{{ [area?.label, cart.landmark].filter(Boolean).join(' · ') }}</span></dd>
						</div>
						<div><dt>Phone</dt><dd>{{ localPhone(cart.phone) }}</dd></div>
						<div v-if="cart.note"><dt>Note</dt><dd>{{ cart.note }}</dd></div>
					</dl>

					<div class="mpesa">
						<div class="mpesa-head"><span class="mpesa-logo">M-PESA</span><span>Pay with M-Pesa</span></div>
						<label class="form">M-Pesa Phone Number<input v-model.trim="payPhone" type="tel" inputmode="tel" placeholder="0712 345 678" /></label>
						<p class="muted small">We'll send a payment request to this phone. Enter your M-Pesa PIN to confirm.</p>
						<p v-if="error" class="form-error">{{ error }}</p>
						<button type="button" class="btn btn-mpesa btn-block" :disabled="busy || cart.has_short" @click="startPayment">
							<Icon name="lock" size="i-md" />{{ busy ? 'Sending request…' : `Pay ${cart.total_label}` }}
						</button>
						<p v-if="cart.has_short" class="form-error">Some items sold out while you were shopping. Update your cart to continue.</p>
					</div>
				</div>
			</section>

			<aside class="co-side">
				<div class="co-card summary">
					<h2>Order summary</h2>
					<ul class="sum-lines">
						<li v-for="l in cart.lines" :key="l.item_code">
							<span class="sum-thumb"><img v-if="l.image" :src="l.image" :alt="l.name" /><i>{{ l.qty }}</i></span>
							<span class="sum-name">{{ l.name }}<small v-if="l.short" class="line-warn">Only {{ l.available }} left</small>
								<QtyStepper v-if="step === 1" :model-value="l.qty" :max="Math.max(l.available, 1)" small :busy="!!state.busy[l.item_code]" @update:model-value="(v) => setQty(l.item_code, v)" />
							</span>
							<b>{{ l.amount_label }}</b>
						</li>
					</ul>
					<div class="sum-row"><span>Subtotal</span><span>{{ cart.subtotal_label }}</span></div>
					<div class="sum-row"><span>{{ cart.fulfilment === 'Pickup' ? 'Pickup' : 'Delivery' }}</span><span>{{ step === 2 ? (cart.delivery_fee ? cart.delivery_fee_label : 'Free') : previewFee === null ? 'Choose an area' : previewFee ? money(previewFee) : 'Free' }}</span></div>
					<div class="sum-row total"><span>Total</span><b>{{ shownTotal }}</b></div>
					<p class="drawer-note"><Icon name="shield" size="i-sm" /> Genuine products, priced as at our counter.</p>
				</div>
			</aside>
		</div>

		<Transition name="fade">
			<div v-if="pay.open" class="scrim scrim-center">
				<div class="dialog pay-dialog" role="dialog" aria-modal="true" aria-label="M-Pesa payment">
					<template v-if="pay.status === 'Paid'">
						<div class="pay-icon ok"><Icon name="check" size="i-xl" /></div>
						<h2 class="dialog-title">Payment received</h2>
						<p class="dialog-sub">Thank you! Your order <b>{{ pay.order }}</b> is placed. Taking you to its tracking page…</p>
					</template>
					<template v-else-if="pay.status === 'Pending'">
						<div class="pay-phone"><Icon name="mpesa" size="i-xl" /><span class="ring" /><span class="ring r2" /></div>
						<h2 class="dialog-title">Check your phone</h2>
						<p class="dialog-sub">We sent a request for <b>KES {{ pay.amount.toLocaleString() }}</b> to <b>{{ masked }}</b>. Enter your M-Pesa PIN to pay.</p>
						<div class="pay-wait"><span class="spinner" /> Waiting for M-Pesa · {{ pay.seconds }}s</div>
						<button type="button" class="link-btn" @click="closePay">Close - I'll check my orders later</button>
					</template>
					<template v-else>
						<div class="pay-icon bad"><Icon name="close" size="i-xl" /></div>
						<h2 class="dialog-title">{{ pay.status === 'Cancelled' ? 'Payment cancelled' : pay.status === 'Timed Out' ? 'No answer from M-Pesa' : 'Payment did not go through' }}</h2>
						<p class="dialog-sub">{{ pay.message || 'Nothing was charged. Your cart is saved.' }}</p>
						<div class="pay-actions">
							<button type="button" class="btn btn-mpesa" @click="closePay(); startPayment()">Try again</button>
							<button type="button" class="btn btn-soft" @click="closePay">Back to checkout</button>
						</div>
					</template>
				</div>
			</div>
		</Transition>
	</div>
</template>
