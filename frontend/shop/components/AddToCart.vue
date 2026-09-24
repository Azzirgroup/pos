<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { state, addToCart } from '../store'
import { get } from '../api'
import Icon from './Icon.vue'
import QtyStepper from './QtyStepper.vue'

/**
 * The product page's buy box: live stock count, quantity, Add to cart / Buy
 * now. The count is what the shop can still sell online — shelf stock less
 * paid orders and other shoppers' held carts — so it may read lower than the
 * shelf, never higher.
 */
const props = defineProps({ code: String, name: String, price: String, stock: Number })
const available = ref(props.stock)
const loaded = ref(false)
const qty = ref(1)

const inCart = computed(() => state.cart?.lines?.find((l) => l.item_code === props.code)?.qty || 0)
const canAdd = computed(() => Math.max(0, available.value - inCart.value))
const busy = computed(() => !!state.busy[props.code])

async function refresh() {
	try {
		const res = await get('shop_orders.availability', { item_codes: JSON.stringify([props.code]) })
		available.value = res[props.code] ?? 0
	} catch (e) {
		/* keep the server-rendered figure */
	}
	loaded.value = true
}
onMounted(refresh)
watch(() => state.customer, refresh)
watch(canAdd, (n) => { if (qty.value > n) qty.value = Math.max(1, n) })

async function add(checkout = false) {
	const ok = await addToCart(props.code, qty.value, { open: !checkout })
	if (ok) {
		qty.value = 1
		if (checkout) location.href = '/shop/checkout'
	}
}
</script>

<template>
	<div class="buybox">
		<div class="stock-line" :class="{ low: available > 0 && available <= 5, out: available <= 0 }">
			<span class="stock-dot" />
			<span v-if="available <= 0">Out of stock</span>
			<span v-else-if="available <= 5">Only <b>{{ available }}</b> left in stock</span>
			<span v-else><b>{{ available }}</b> in stock</span>
			<span v-if="inCart" class="in-cart">· {{ inCart }} in your cart</span>
		</div>
		<div v-if="available > 0" class="buy-row">
			<QtyStepper v-model="qty" :max="Math.max(1, canAdd)" :busy="busy" />
			<button type="button" class="btn btn-primary grow" :disabled="busy || canAdd <= 0" @click="add(false)">
				<Icon name="bag" size="i-md" />{{ canAdd <= 0 ? 'All in your cart' : busy ? 'Adding…' : 'Add to cart' }}
			</button>
		</div>
		<button v-if="available > 0 && canAdd > 0" type="button" class="btn btn-dark btn-block" :disabled="busy" @click="add(true)">Buy now</button>
		<p v-if="available > 0 && qty >= canAdd && canAdd > 0" class="buy-note">That is the most we can sell you right now.</p>
	</div>
</template>
