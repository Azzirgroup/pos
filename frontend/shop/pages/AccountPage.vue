<script setup>
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { state, askToSignIn, signOut, toast, when , localPhone } from '../store'
import { get, post } from '../api'
import Icon from '../components/Icon.vue'
import StatusChip from '../components/StatusChip.vue'

/** My orders and account details. */
const tab = ref(location.hash === '#profile' ? 'profile' : 'orders')
const orders = ref(null)
const error = ref('')
const profile = reactive({ full_name: '', email: '', phone: '' })
const pw = reactive({ current: '', next: '' })
const busy = ref(false)

async function load() {
	if (!state.customer) return
	profile.full_name = state.customer.name
	profile.email = state.customer.email || ''
	try {
		orders.value = await get('shop_orders.my_orders')
	} catch (e) {
		error.value = e.message
	}
}
watch(() => state.customer, load)
onMounted(load)

const active = computed(() => (orders.value || []).filter((o) => !['Complete', 'Cancelled', 'Draft'].includes(o.status)))
const past = computed(() => (orders.value || []).filter((o) => ['Complete', 'Cancelled'].includes(o.status)))
const draft = computed(() => (orders.value || []).find((o) => o.status === 'Draft'))

function setTab(t) {
	tab.value = t
	history.replaceState(null, '', t === 'profile' ? '#profile' : location.pathname)
}

async function saveProfile() {
	busy.value = true
	try {
		const res = await post('shop_account.update_profile', { full_name: profile.full_name, email: profile.email, phone: profile.phone || null })
		state.customer = res.customer
		toast('Details saved')
	} catch (e) {
		toast(e.message, 'error')
	} finally {
		busy.value = false
	}
}

async function changePassword() {
	busy.value = true
	try {
		await post('shop_account.change_password', { current: pw.current, new: pw.next })
		pw.current = pw.next = ''
		toast('Password changed')
	} catch (e) {
		toast(e.message, 'error')
	} finally {
		busy.value = false
	}
}
</script>

<template>
	<div class="acct wide">
		<nav class="crumbs"><a href="/shop">Home</a><span>/</span><span class="here">My account</span></nav>

		<div v-if="!state.ready" class="co-loading"><span class="spinner" /> Loading…</div>
		<div v-else-if="!state.customer" class="co-empty">
			<Icon name="user" size="i-xl" />
			<h1>Sign in to see your orders</h1>
			<p>Track deliveries, see receipts and pick up where you left off.</p>
			<button type="button" class="btn btn-primary" @click="askToSignIn('')">Sign in or create account</button>
		</div>

		<template v-else>
			<header class="acct-head">
				<span class="acct-avatar">{{ state.customer.first_name?.[0] }}</span>
				<div>
					<h1>Hello, {{ state.customer.first_name }}</h1>
					<p>{{ localPhone(state.customer.phone) }}<template v-if="state.customer.email"> · {{ state.customer.email }}</template></p>
				</div>
			</header>
			<div class="seg seg-left" role="tablist">
				<button type="button" role="tab" :class="{ on: tab === 'orders' }" @click="setTab('orders')">My orders</button>
				<button type="button" role="tab" :class="{ on: tab === 'profile' }" @click="setTab('profile')">Account details</button>
			</div>

			<section v-if="tab === 'orders'">
				<div v-if="orders === null" class="co-loading"><span class="spinner" /> Loading your orders…</div>
				<template v-else>
					<a v-if="draft" class="draft-banner" href="/shop/checkout">
						<Icon name="bag" />
						<span><b>You have {{ draft.count }} item{{ draft.count === 1 ? '' : 's' }} in your cart</b><small>{{ draft.total_label }} · finish checking out to place the order</small></span>
						<span class="btn btn-primary">Continue</span>
					</a>

					<div v-if="!active.length && !past.length && !draft" class="co-empty small">
						<Icon name="package" size="i-xl" />
						<h2>No orders yet</h2>
						<p>When you place an order it will show here, with live tracking.</p>
						<a class="btn btn-primary" href="/shop/catalog">Start shopping</a>
					</div>

					<h2 v-if="active.length" class="acct-h">In progress</h2>
					<a v-for="o in active" :key="o.name" class="order-card" :href="`/shop/orders/${encodeURIComponent(o.name)}`">
						<span class="order-thumbs"><img v-for="(img, i) in o.images.filter(Boolean).slice(0, 3)" :key="i" :src="img" alt="" /></span>
						<span class="order-main"><b>{{ o.name }}</b><small>{{ when(o.placed_at) || o.date }} · {{ o.count }} item{{ o.count === 1 ? '' : 's' }} · {{ o.fulfilment }}</small></span>
						<StatusChip :status="o.status" />
						<b class="order-total">{{ o.total_label }}</b>
						<Icon name="right" size="i-md" />
					</a>

					<h2 v-if="past.length" class="acct-h">Past orders</h2>
					<a v-for="o in past" :key="o.name" class="order-card" :href="`/shop/orders/${encodeURIComponent(o.name)}`">
						<span class="order-thumbs"><img v-for="(img, i) in o.images.filter(Boolean).slice(0, 3)" :key="i" :src="img" alt="" /></span>
						<span class="order-main"><b>{{ o.name }}</b><small>{{ when(o.placed_at) || o.date }} · {{ o.count }} item{{ o.count === 1 ? '' : 's' }}</small></span>
						<StatusChip :status="o.status" />
						<b class="order-total">{{ o.total_label }}</b>
						<Icon name="right" size="i-md" />
					</a>
				</template>
			</section>

			<section v-else class="acct-forms">
				<form class="co-card form" @submit.prevent="saveProfile">
					<h2>Your details</h2>
					<label>Full Name<input v-model="profile.full_name" required /></label>
					<label>Email <span class="opt">(Optional)</span><input v-model.trim="profile.email" type="email" /></label>
					<label v-if="state.customer.needs_phone">Phone Number<input v-model.trim="profile.phone" type="tel" inputmode="tel" placeholder="0712 345 678" /><small>Add your number so the shop and rider can reach you, and to sign in with it.</small></label>
					<label v-else>Phone<input :value="localPhone(state.customer.phone)" disabled /><small>To change your phone number, contact the shop.</small></label>
					<button class="btn btn-primary" :disabled="busy">Save details</button>
				</form>
				<form v-if="state.customer.has_password" class="co-card form" @submit.prevent="changePassword">
					<h2>Change password</h2>
					<label>Current Password<input v-model="pw.current" type="password" autocomplete="current-password" required /></label>
					<label>New Password<input v-model="pw.next" type="password" autocomplete="new-password" minlength="6" required /></label>
					<button class="btn btn-primary" :disabled="busy">Change password</button>
					<hr />
					<button type="button" class="btn btn-soft" @click="signOut"><Icon name="logout" size="i-md" />Sign out</button>
				</form>
			</section>
		</template>
	</div>
</template>
