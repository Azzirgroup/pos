<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { state, askToSignIn, signOut, openCart , localPhone } from '../store'
import Icon from './Icon.vue'

const menu = ref(false)
const box = ref(null)
const count = computed(() => state.cart?.count || 0)

function outside(e) {
	if (box.value && !box.value.contains(e.target)) menu.value = false
}
onMounted(() => document.addEventListener('click', outside))
onBeforeUnmount(() => document.removeEventListener('click', outside))
</script>

<template>
	<div ref="box" class="hx">
		<button v-if="!state.customer" type="button" class="hx-btn" @click="askToSignIn('')">
			<Icon name="user" />
			<span class="hx-label">Sign in</span>
		</button>
		<div v-else class="hx-menu-wrap">
			<button type="button" class="hx-btn" :aria-expanded="menu" @click="menu = !menu">
				<span class="hx-avatar">{{ state.customer.first_name?.[0] || '?' }}</span>
				<span class="hx-label">{{ state.customer.first_name }}</span>
			</button>
			<Transition name="pop">
				<div v-if="menu" class="hx-menu" role="menu">
					<div class="hx-menu-head">
						<b>{{ state.customer.name }}</b>
						<span>{{ localPhone(state.customer.phone) }}</span>
					</div>
					<a href="/shop/account" role="menuitem"><Icon name="package" size="i-md" />My orders</a>
					<a href="/shop/account#profile" role="menuitem"><Icon name="user" size="i-md" />Account details</a>
					<button type="button" role="menuitem" @click="signOut"><Icon name="logout" size="i-md" />Sign out</button>
				</div>
			</Transition>
		</div>
		<button type="button" class="hx-btn hx-cart" aria-label="Open cart" @click="openCart">
			<Icon name="bag" />
			<span class="hx-label">Cart</span>
			<span v-if="count" class="hx-count">{{ count }}</span>
		</button>
	</div>
</template>
