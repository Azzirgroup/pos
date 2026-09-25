<script setup>
import { ref, reactive, watch, nextTick, computed } from 'vue'
import { state, afterSignIn } from '../store'
import { post } from '../api'
import Icon from './Icon.vue'

const form = reactive({ identifier: '', password: '', full_name: '', phone: '', email: '', new_password: '', confirm: '' })
const googleId = document.querySelector('meta[name="google-client-id"]')?.content || ''
const googleBox = ref(null)
const mismatch = computed(() => form.confirm && form.confirm !== form.new_password)
const error = ref('')
const busy = ref(false)
const first = ref(null)
const show = ref(false)

watch(
	() => state.auth.open,
	async (open) => {
		error.value = ''
		document.body.style.overflow = open ? 'hidden' : ''
		if (open) {
			await nextTick()
			first.value?.focus()
			renderGoogle()
		}
	}
)

const close = () => (state.auth.open = false)
const mode = async (m) => {
	state.auth.mode = m
	error.value = ''
	await nextTick()
	renderGoogle()
}

/**
 * Sign in with Google: Google's own button (Google Identity Services), loaded
 * only when the dialog opens and the shop has a Client ID. Google hands back
 * an ID token, which the server verifies before signing the customer in.
 */
let gsi = null
function loadGoogle() {
	if (gsi) return gsi
	gsi = new Promise((resolve, reject) => {
		const s = document.createElement('script')
		s.src = 'https://accounts.google.com/gsi/client'
		s.async = true
		s.onload = () => resolve(window.google)
		s.onerror = reject
		document.head.appendChild(s)
	})
	return gsi
}
async function renderGoogle() {
	if (!googleId || !googleBox.value) return
	try {
		const google = await loadGoogle()
		google.accounts.id.initialize({ client_id: googleId, callback: onGoogle, ux_mode: 'popup', context: state.auth.mode === 'signup' ? 'signup' : 'signin' })
		googleBox.value.innerHTML = ''
		google.accounts.id.renderButton(googleBox.value, {
			theme: 'outline',
			size: 'large',
			shape: 'rectangular',
			text: state.auth.mode === 'signup' ? 'signup_with' : 'continue_with',
			width: Math.min(googleBox.value.clientWidth || 360, 400),
			logo_alignment: 'center',
		})
	} catch (e) {
		/* Google unreachable: the password form still works */
	}
}
async function onGoogle(res) {
	busy.value = true
	error.value = ''
	try {
		const out = await post('shop_account.google_login', { credential: res.credential })
		await afterSignIn(out.customer)
	} catch (e) {
		error.value = e.message
	} finally {
		busy.value = false
	}
}

async function signIn() {
	busy.value = true
	error.value = ''
	try {
		const res = await post('shop_account.login', { identifier: form.identifier, password: form.password })
		form.password = ''
		await afterSignIn(res.customer)
	} catch (e) {
		error.value = e.message
	} finally {
		busy.value = false
	}
}

async function signUp() {
	if (form.new_password !== form.confirm) {
		error.value = 'The two passwords do not match'
		return
	}
	busy.value = true
	error.value = ''
	try {
		const res = await post('shop_account.signup', {
			full_name: form.full_name,
			phone: form.phone,
			email: form.email || null,
			password: form.new_password,
			confirm_password: form.confirm,
		})
		form.new_password = form.confirm = ''
		await afterSignIn(res.customer)
	} catch (e) {
		error.value = e.message
	} finally {
		busy.value = false
	}
}
</script>

<template>
	<Transition name="fade"><div v-if="state.auth.open" class="scrim scrim-center" @click.self="close">
		<div class="dialog" role="dialog" aria-modal="true" :aria-label="state.auth.mode === 'signin' ? 'Sign in' : 'Create account'" @keydown.esc="close">
			<button type="button" class="icon-btn dialog-x" aria-label="Close" @click="close"><Icon name="close" /></button>
			<div class="dialog-brand"><Icon name="bag" size="i-lg" /></div>
			<h2 class="dialog-title">{{ state.auth.mode === 'signin' ? 'Welcome back' : 'Create your account' }}</h2>
			<p class="dialog-sub">{{ state.auth.reason || (state.auth.mode === 'signin' ? 'Sign in to shop, pay with M-Pesa and track your orders.' : 'It takes a minute. Your orders and cart follow you on any device.') }}</p>

			<div class="seg" role="tablist">
				<button type="button" role="tab" :class="{ on: state.auth.mode === 'signin' }" @click="mode('signin')">Sign in</button>
				<button type="button" role="tab" :class="{ on: state.auth.mode === 'signup' }" @click="mode('signup')">Create account</button>
			</div>

			<template v-if="googleId">
				<div ref="googleBox" class="google-btn" />
				<div class="or"><span>or</span></div>
			</template>

			<form v-if="state.auth.mode === 'signin'" class="form" @submit.prevent="signIn">
				<label>Phone Number Or Username<input ref="first" v-model.trim="form.identifier" autocomplete="username" required placeholder="0712 345 678" /></label>
				<label>Password
					<span class="pw"><input v-model="form.password" :type="show ? 'text' : 'password'" autocomplete="current-password" required /><button type="button" class="pw-toggle" @click="show = !show">{{ show ? 'Hide' : 'Show' }}</button></span>
				</label>
				<p v-if="error" class="form-error">{{ error }}</p>
				<button class="btn btn-primary btn-block" :disabled="busy">{{ busy ? 'Signing in…' : 'Sign in' }}</button>
				<p class="form-foot">New here? <button type="button" class="link-btn" @click="mode('signup')">Create an account</button></p>
			</form>

			<form v-else class="form" @submit.prevent="signUp">
				<label>Full Name<input ref="first" v-model="form.full_name" autocomplete="name" required placeholder="Jane Wanjiku" /></label>
				<label>Phone Number<input v-model.trim="form.phone" type="tel" inputmode="tel" autocomplete="tel" required placeholder="0712 345 678" /><small>Used to sign in and for M-Pesa.</small></label>
				<label>Email <span class="opt">(Optional)</span><input v-model.trim="form.email" type="email" autocomplete="email" /></label>
				<label>Password
					<span class="pw"><input v-model="form.new_password" :type="show ? 'text' : 'password'" autocomplete="new-password" minlength="6" required /><button type="button" class="pw-toggle" @click="show = !show">{{ show ? 'Hide' : 'Show' }}</button></span>
					<small>At least 6 characters.</small>
				</label>
				<label>Confirm Password
					<input v-model="form.confirm" :type="show ? 'text' : 'password'" autocomplete="new-password" required :class="{ bad: mismatch, good: form.confirm && !mismatch }" />
					<small v-if="mismatch" class="bad-text">The passwords do not match yet</small>
					<small v-else-if="form.confirm" class="good-text">Passwords match</small>
				</label>
				<p v-if="error" class="form-error">{{ error }}</p>
				<button class="btn btn-primary btn-block" :disabled="busy || mismatch">{{ busy ? 'Creating account…' : 'Create account' }}</button>
				<p class="form-foot">Already have an account? <button type="button" class="link-btn" @click="mode('signin')">Sign in</button></p>
			</form>
		</div>
	</div></Transition>
</template>
