<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { state, askToSignIn, duration, when , localPhone } from '../store'
import { get } from '../api'
import Icon from '../components/Icon.vue'
import StatusChip from '../components/StatusChip.vue'

/**
 * Tracking one order. The timeline shows each stage of its flow — Draft,
 * Order Received, Processing, Out for Delivery (or Ready for Pickup),
 * Complete — with when it got there and how long it stayed, and a live
 * "for 3 hours so far" on the current stage. Refreshes itself every minute.
 */
const props = defineProps({ order: String })
const data = ref(null)
const error = ref('')
const tick = ref(0)
const placed = new URLSearchParams(location.search).has('placed')
let refresh = null
let clock = null
let loadedAt = Date.now()

async function load() {
	if (!state.customer) return
	try {
		data.value = await get('shop_orders.order', { name: props.order })
		loadedAt = Date.now()
		error.value = ''
	} catch (e) {
		error.value = e.status === 404 || /not found/i.test(e.message) ? 'We could not find that order in your account.' : e.message
	}
}

onMounted(() => {
	const wait = setInterval(() => {
		if (state.ready) {
			clearInterval(wait)
			load()
		}
	}, 50)
	refresh = setInterval(load, 60000)
	clock = setInterval(() => tick.value++, 30000)
})
onBeforeUnmount(() => {
	clearInterval(refresh)
	clearInterval(clock)
})

const stages = computed(() => {
	tick.value // re-evaluate as time passes
	const extra = Math.floor((Date.now() - loadedAt) / 1000)
	return (data.value?.timeline || []).map((s) => ({
		...s,
		live: s.state === 'current' && s.seconds !== null ? s.seconds + extra : s.seconds,
	}))
})
const progress = computed(() => {
	const list = stages.value
	if (!list.length) return 0
	const i = list.findIndex((s) => s.state === 'current')
	const done = list.filter((s) => s.state === 'done').length
	return Math.round(((i === -1 ? done - 1 : i) / Math.max(1, list.length - 1)) * 100)
})
const current = computed(() => stages.value.find((s) => s.state === 'current') || stages.value[stages.value.length - 1])
const total = computed(() => {
	const list = stages.value.filter((s) => s.entered_at && s.status !== 'Draft')
	if (!list.length) return null
	const start = new Date(list[0].entered_at.replace(' ', 'T'))
	const last = list[list.length - 1]
	const end = last.left_at ? new Date(last.left_at.replace(' ', 'T')) : null
	if (data.value.status === 'Complete' || data.value.status === 'Cancelled') {
		const fin = new Date(last.entered_at.replace(' ', 'T'))
		return Math.max(0, (fin - start) / 1000)
	}
	return Math.max(0, (new Date(data.value.server_now.replace(' ', 'T')) - start) / 1000 + (Date.now() - loadedAt) / 1000 + tick.value * 0)
})
const icons = { Draft: 'bag', 'Order Received': 'check', Processing: 'package', 'Out for Delivery': 'truck', 'Ready for Pickup': 'store', Complete: 'home', Cancelled: 'close' }
</script>

<template>
	<div class="track wide">
		<nav class="crumbs"><a href="/shop">Home</a><span>/</span><a href="/shop/account">My orders</a><span>/</span><span class="here">{{ order }}</span></nav>

		<div v-if="!state.ready || (state.customer && !data && !error)" class="co-loading"><span class="spinner" /> Loading your order…</div>
		<div v-else-if="!state.customer" class="co-empty">
			<Icon name="lock" size="i-xl" />
			<h1>Sign in to track this order</h1>
			<button type="button" class="btn btn-primary" @click="askToSignIn('Sign in to track your order')">Sign in</button>
		</div>
		<div v-else-if="error" class="co-empty"><Icon name="package" size="i-xl" /><h1>{{ error }}</h1><a class="btn btn-primary" href="/shop/account">See my orders</a></div>

		<template v-else>
			<div v-if="placed && data.status !== 'Draft'" class="placed-banner">
				<Icon name="check" /><span><b>Thank you - your order is placed.</b> We'll keep this page up to date as it moves.</span>
			</div>

			<header class="track-head">
				<div>
					<p class="muted small">Order</p>
					<h1>{{ data.name }}</h1>
					<p class="muted">{{ data.placed_at ? `Placed ${when(data.placed_at)}` : 'Not placed yet' }} · {{ data.count }} item{{ data.count === 1 ? '' : 's' }} · {{ data.total_label }}</p>
				</div>
				<StatusChip :status="data.status" large />
			</header>

			<div class="track-grid">
				<section class="co-card">
					<div class="track-now">
						<span class="track-now-icon" :class="`st-${(current?.status || '').toLowerCase().replace(/\s+/g, '-')}`"><Icon :name="icons[current?.status] || 'package'" /></span>
						<div>
							<b>{{ current?.status }}</b>
							<p>{{ current?.description }}</p>
							<small v-if="current?.state === 'current' && current.live !== null">For {{ duration(current.live) }} so far</small>
						</div>
					</div>

					<div class="track-bar" :class="{ cancelled: data.status === 'Cancelled' }"><span :style="{ width: `${progress}%` }" /></div>

					<ol class="timeline">
						<li v-for="s in stages" :key="s.status" :class="[s.state, { cancelled: s.status === 'Cancelled' }]">
							<span class="tl-dot"><Icon v-if="s.state === 'done'" name="check" size="i-sm" /><Icon v-else :name="icons[s.status] || 'package'" size="i-sm" /></span>
							<div class="tl-body">
								<div class="tl-top">
									<b>{{ s.status }}</b>
									<span v-if="s.entered_at" class="tl-when">{{ when(s.entered_at) }}</span>
								</div>
								<p>{{ s.description }}</p>
								<p v-if="s.note" class="tl-note">{{ s.note }}</p>
								<span v-if="s.state === 'done' && s.live !== null && s.left_at" class="tl-dur"><Icon name="clock" size="i-sm" />Took {{ duration(s.live) }}</span>
								<span v-else-if="s.state === 'current' && s.live !== null" class="tl-dur live"><span class="pulse" />{{ duration(s.live) }} so far</span>
							</div>
						</li>
					</ol>
					<p v-if="total" class="track-total"><Icon name="clock" size="i-sm" />{{ data.status === 'Complete' ? `Completed in ${duration(total)} from payment` : `${duration(total)} since you paid` }}</p>
					<a v-if="data.is_cart" class="btn btn-primary btn-block" href="/shop/checkout">Continue to checkout</a>
				</section>

				<aside class="track-side">
					<div class="co-card">
						<h2>Items</h2>
						<ul class="sum-lines">
							<li v-for="(l, i) in data.lines" :key="i">
								<span class="sum-thumb"><img v-if="l.image" :src="l.image" :alt="l.name" /><i>{{ l.qty }}</i></span>
								<a :href="l.url" class="sum-name">{{ l.name }}<small>{{ l.rate_label }} each</small></a>
								<b>{{ l.amount_label }}</b>
							</li>
						</ul>
						<div class="sum-row"><span>Subtotal</span><span>{{ data.subtotal_label }}</span></div>
						<div class="sum-row"><span>{{ data.fulfilment === 'Pickup' ? 'Pickup' : 'Delivery' }}</span><span>{{ data.delivery_fee_label }}</span></div>
						<div class="sum-row total"><span>Total</span><b>{{ data.total_label }}</b></div>
						<p v-if="data.receipt" class="receipt"><span class="mpesa-logo">M-PESA</span> Receipt <b>{{ data.receipt }}</b></p>
					</div>
					<div class="co-card">
						<h2>{{ data.fulfilment === 'Pickup' ? 'Pickup' : 'Delivery' }}</h2>
						<p v-if="data.fulfilment === 'Pickup'">{{ data.pickup_note || 'Collect from the shop counter.' }}</p>
						<p v-else>{{ data.address }}<br /><span class="muted">{{ data.area }}{{ data.landmark ? ` · ${data.landmark}` : '' }}</span></p>
						<p class="muted small"><Icon name="phone" size="i-sm" /> {{ localPhone(data.phone) }}</p>
						<p v-if="data.note" class="muted small">Note: {{ data.note }}</p>
					</div>
				</aside>
			</div>
		</template>
	</div>
</template>
