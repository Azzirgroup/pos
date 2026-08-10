<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useTillStore } from '@/stores/till'
import { getMe } from '@/data/api'
import LucidePanelLeft from '~icons/lucide/panel-left'
import LucidePlus from '~icons/lucide/plus'
import LucideLogOut from '~icons/lucide/log-out'
import LucideUserRound from '~icons/lucide/user-round'
import MasterSheet from '@/components/MasterSheet.vue'

const emit = defineEmits(['toggleRail'])

/**
 * Bound rather than written inline in `src`, so the bundler treats it as a
 * runtime URL. An absolute `/assets/…` path in a plain `src` attribute is
 * something Rollup tries to resolve at build time, and it fails the build
 * because the file lives in the app's public folder rather than this tree.
 */
const LOGO = '/assets/cosmestics/images/logo.svg'

const route = useRoute()
const title = computed(() => route.meta?.title || 'POS')



const till = useTillStore()
const masterOpen = ref(false)

/**
 * Who is signed in, and how to stop being them.
 *
 * A till is a shared machine. Without this there was no way off it at all — a
 * cashier finishing their shift left the browser logged in as themselves, and
 * the next person's sales were recorded against the wrong name. That is not a
 * missing convenience; it is the invoice owner being wrong, which is exactly
 * what the shift roster depends on being right.
 */
const me = ref(null)
const userMenu = ref(false)

/**
 * Frappe's own endpoints, not an app one.
 *
 * `/api/method/logout` clears the session cookie server-side; a client-side
 * "forget the user" that leaves the cookie alive is a logout button that does
 * not log anybody out. The full page load afterwards is deliberate — it drops
 * every cached catalog, cart and shift in memory, none of which belongs to
 * whoever signs in next.
 */
async function logout() {
	try {
		await fetch('/api/method/logout', { method: 'GET', credentials: 'same-origin' })
	} catch (e) {
		console.warn('[pos] logout failed', e)
	}
	window.location.href = '/login'
}

/**
 * Sign in as somebody else. Same as logging out, but comes back here rather
 * than to the desk — a cashier handing the counter over is mid-shift, not
 * leaving.
 */
async function switchUser() {
	try {
		await fetch('/api/method/logout', { method: 'GET', credentials: 'same-origin' })
	} catch (e) {
		console.warn('[pos] logout failed', e)
	}
	window.location.href = `/login?redirect-to=${encodeURIComponent('/pos/pos')}`
}

function onUserBlur(event) {
	if (!event.currentTarget.contains(event.relatedTarget)) userMenu.value = false
}

const toast = ref(null)
let toastTimer = null
function onNotify({ message, tone }) {
	toast.value = { message, tone }
	clearTimeout(toastTimer)
	toastTimer = setTimeout(() => (toast.value = null), 2800)
}



onMounted(async () => {
	// The shell still warms the till context, because the header chip on other
	// screens and the POS both read it from the store.
	till.refresh()
	try {
		me.value = await getMe()
	} catch (e) {
		// The menu still works without a name on it — signing out must not depend
		// on having successfully looked up who you are.
		console.warn('[pos] session lookup failed', e)
	}
})


</script>

<template>
	<header
		class="relative flex h-11 shrink-0 items-center gap-2 border-b border-outline-gray-2 bg-surface-white px-2.5"
	>
		<button
			class="grid h-7 w-7 place-items-center rounded-md text-ink-gray-6 transition-colors hover:bg-surface-gray-2"
			aria-label="Toggle sidebar"
			@click="emit('toggleRail')"
		>
			<LucidePanelLeft class="h-[17px] w-[17px]" />
		</button>

		<!-- The app's own mark, top left. Served from the app's public folder
		     rather than the built frontend so the desk and the till show the same
		     one. `alt` is empty on purpose: the title beside it already names the
		     app, and a screen reader announcing "Cosmetics POS logo, Cosmetics
		     POS" is worse than silence. -->
		<img
			:src="LOGO"
			alt=""
			width="22"
			height="22"
			class="h-[22px] w-[22px] shrink-0 rounded"
		/>

		<span class="text-p-sm font-medium text-ink-gray-8">{{ title }}</span>

		<div class="ml-auto flex items-center gap-2">
			<!-- Creating a customer or a supplier is something a shop does mid-task,
			     so it lives in the shell rather than on one screen. -->
			<button
				class="flex h-7 items-center gap-1 rounded-md px-2 text-p-xs font-medium text-ink-gray-7 transition-colors hover:bg-surface-gray-2"
				@click="masterOpen = true"
			>
				<LucidePlus class="h-3.5 w-3.5" />
				<span class="hidden sm:block">New</span>
			</button>

			<!-- Who is signed in, and the way off this machine. A till is shared:
			     without this the previous cashier stays signed in and the next
			     person's sales are recorded against their name. -->
			<div class="relative" @focusout="onUserBlur">
				<button
					class="flex h-7 items-center gap-1.5 rounded-md pl-1 pr-1.5 text-p-xs font-medium text-ink-gray-7 transition-colors hover:bg-surface-gray-2"
					:aria-label="me ? `Signed in as ${me.full_name}` : 'Account'"
					:title="me?.user || 'Account'"
					@click="userMenu = !userMenu"
				>
					<span
						class="grid h-[22px] w-[22px] shrink-0 place-items-center rounded-full bg-surface-gray-3 text-[10px] font-semibold text-ink-gray-7"
					>
						<template v-if="me?.initials">{{ me.initials }}</template>
						<LucideUserRound v-else class="h-3 w-3" />
					</span>
					<span class="hidden max-w-[10rem] truncate md:block">
						{{ me?.full_name || 'Account' }}
					</span>
				</button>

				<div
					v-if="userMenu"
					class="absolute right-0 z-20 mt-1 w-56 rounded-xl border border-outline-gray-2 bg-surface-white py-1 shadow-lg"
				>
					<div class="border-b border-outline-gray-2 px-3 py-2">
						<div class="truncate text-p-sm font-medium text-ink-gray-9">
							{{ me?.full_name || 'Signed in' }}
						</div>
						<div class="truncate text-p-xs text-ink-gray-5">{{ me?.user }}</div>
					</div>
					<button
						class="flex min-h-touch w-full items-center gap-2 px-3 py-2 text-left text-p-sm text-ink-gray-7 hover:bg-surface-gray-2"
						@click="switchUser"
					>
						<LucideUserRound class="h-4 w-4 shrink-0 text-ink-gray-5" />
						Switch user
					</button>
					<button
						class="flex min-h-touch w-full items-center gap-2 px-3 py-2 text-left text-p-sm text-ink-red-3 hover:bg-surface-red-1"
						@click="logout"
					>
						<LucideLogOut class="h-4 w-4 shrink-0" />
						Sign out
					</button>
				</div>
			</div>
		</div>

		<MasterSheet v-model:open="masterOpen" @notify="onNotify" />

		<Transition
			enter-active-class="transition-all duration-200"
			leave-active-class="transition-all duration-200"
			enter-from-class="opacity-0 -translate-y-2"
			leave-to-class="opacity-0"
		>
			<div
				v-if="toast"
				class="pointer-events-none pos-toast absolute left-1/2 top-14 -translate-x-1/2 rounded-lg px-4 py-2.5 text-p-sm font-medium text-ink-white shadow-lg"
				:class="toast.tone === 'bad' ? 'bg-surface-red-5' : 'bg-surface-green-3'"
			>
				{{ toast.message }}
			</div>
		</Transition>
	</header>
</template>
