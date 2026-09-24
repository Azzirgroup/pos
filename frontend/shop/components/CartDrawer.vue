<script setup>
import { computed, watch } from 'vue'
import { state, setQty, askToSignIn } from '../store'
import Icon from './Icon.vue'
import QtyStepper from './QtyStepper.vue'

const cart = computed(() => state.cart || {})
const lines = computed(() => cart.value.lines || [])
const close = () => (state.cartOpen = false)

watch(
	() => state.cartOpen,
	(open) => (document.body.style.overflow = open ? 'hidden' : '')
)
function onKey(e) {
	if (e.key === 'Escape') close()
}
</script>

<template>
	<Transition name="fade"><div v-if="state.cartOpen" class="scrim" @click="close" /></Transition>
	<Transition name="slide">
		<aside v-if="state.cartOpen" class="drawer" role="dialog" aria-label="Your cart" @keydown="onKey" tabindex="-1">
			<header class="drawer-head">
				<h2>Your cart <span v-if="cart.count">({{ cart.count }})</span></h2>
				<button type="button" class="icon-btn" aria-label="Close cart" @click="close"><Icon name="close" /></button>
			</header>

			<div v-if="!state.customer" class="drawer-empty">
				<Icon name="bag" size="i-xl" />
				<p class="drawer-empty-title">Sign in to start your order</p>
				<p>Your cart is saved to your account, so it is there on any device.</p>
				<button type="button" class="btn btn-primary" @click="askToSignIn('')">Sign in or create account</button>
			</div>

			<div v-else-if="!lines.length" class="drawer-empty">
				<Icon name="bag" size="i-xl" />
				<p class="drawer-empty-title">Your cart is empty</p>
				<p>Add something you love and it will show here.</p>
				<a class="btn btn-primary" href="/shop/catalog" @click="close">Start shopping</a>
			</div>

			<template v-else>
				<ul class="lines">
					<li v-for="l in lines" :key="l.item_code" class="line-item" :class="{ 'is-short': l.short }">
						<a :href="l.url" class="line-thumb"><img v-if="l.image" :src="l.image" :alt="l.name" /></a>
						<div class="line-info">
							<a :href="l.url" class="line-name">{{ l.name }}</a>
							<span class="line-rate">{{ l.rate_label }}</span>
							<span v-if="l.short" class="line-warn">Only {{ l.available }} left - reduce to continue</span>
							<span v-else-if="l.available - l.qty <= 3" class="line-hint">{{ l.available - l.qty > 0 ? `${l.available - l.qty} more available` : 'That is all we have' }}</span>
							<div class="line-row">
								<QtyStepper :model-value="l.qty" :max="Math.max(l.available, 1)" :min="1" small :busy="!!state.busy[l.item_code]" @update:model-value="(v) => setQty(l.item_code, v)" />
								<button type="button" class="link-btn" @click="setQty(l.item_code, 0)">Remove</button>
							</div>
						</div>
						<b class="line-amount">{{ l.amount_label }}</b>
					</li>
				</ul>
				<footer class="drawer-foot">
					<div class="sum-row"><span>Subtotal</span><b>{{ cart.subtotal_label }}</b></div>
					<p class="drawer-note"><Icon name="clock" size="i-sm" /> Items are held for you for {{ cart.hold_minutes }} minutes. Delivery is added at checkout.</p>
					<a class="btn btn-primary btn-block" :class="{ 'is-disabled': cart.has_short }" href="/shop/checkout">Checkout <Icon name="right" size="i-md" /></a>
					<button type="button" class="link-btn center" @click="close">Continue shopping</button>
				</footer>
			</template>
		</aside>
	</Transition>
</template>
