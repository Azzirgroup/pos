<script setup>
import { computed, onMounted } from 'vue'
import { state, boot } from './store'
import HeaderActions from './components/HeaderActions.vue'
import CartDrawer from './components/CartDrawer.vue'
import AuthDialog from './components/AuthDialog.vue'
import AddToCart from './components/AddToCart.vue'
import Toasts from './components/Toasts.vue'
import CheckoutPage from './pages/CheckoutPage.vue'
import AccountPage from './pages/AccountPage.vue'
import OrderPage from './pages/OrderPage.vue'

const $ = (sel) => document.querySelector(sel)
const addEl = $('#cc-add')
const pageEl = $('#cc-page')
const pages = { checkout: CheckoutPage, account: AccountPage, order: OrderPage }
const page = pageEl ? pages[pageEl.dataset.page] : null
const pageProps = pageEl ? { ...pageEl.dataset } : {}
const count = computed(() => state.cart?.count || 0)

onMounted(boot)
</script>

<template>
	<Teleport v-if="$('#cc-header-actions')" to="#cc-header-actions"><HeaderActions /></Teleport>
	<Teleport v-if="$('#cc-tab-count')" to="#cc-tab-count"><span v-if="count" class="tab-badge">{{ count }}</span></Teleport>
	<Teleport v-if="addEl" to="#cc-add">
		<AddToCart :code="addEl.dataset.code" :name="addEl.dataset.name" :price="addEl.dataset.price" :stock="Number(addEl.dataset.stock || 0)" />
	</Teleport>
	<Teleport v-if="page" to="#cc-page"><component :is="page" v-bind="pageProps" /></Teleport>
	<CartDrawer />
	<AuthDialog />
	<Toasts />
</template>
