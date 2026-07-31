<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useTillStore } from '@/stores/till'
import LucidePanelLeft from '~icons/lucide/panel-left'
import LucidePlus from '~icons/lucide/plus'
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

const toast = ref(null)
let toastTimer = null
function onNotify({ message, tone }) {
	toast.value = { message, tone }
	clearTimeout(toastTimer)
	toastTimer = setTimeout(() => (toast.value = null), 2800)
}



onMounted(() => {
	// The shell still warms the till context, because the header chip on other
	// screens and the POS both read it from the store.
	till.refresh()
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
