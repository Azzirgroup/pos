<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { getMe } from '@/data/api'
import { useTillStore } from '@/stores/till'
import LucidePanelLeft from '~icons/lucide/panel-left'
import LucideZap from '~icons/lucide/zap'
import LucideChevronsUpDown from '~icons/lucide/chevrons-up-down'
import LucideStore from '~icons/lucide/store'
import LucideWarehouse from '~icons/lucide/warehouse'
import LucideClock from '~icons/lucide/clock'
import LucidePlus from '~icons/lucide/plus'
import MasterSheet from '@/components/MasterSheet.vue'

const emit = defineEmits(['toggleRail'])

const route = useRoute()
const title = computed(() => route.meta?.title || 'POS')

// The signed-in account, not a hardcoded label: this is what a cashier checks
// before opening a shift, since the sale is recorded against it.
const me = ref(null)
const displayName = computed(() => me.value?.full_name || 'Loading…')
const initials = computed(() => me.value?.initials || '··')


/**
 * Which till, shop and warehouse this session sells from.
 *
 * Shown because a cashier covering someone else's counter otherwise has no way
 * to know which warehouse the app draws stock from, and a wrong one is invisible
 * until a stock report is wrong a week later. The shift chip doubles as the
 * answer to "am I open?", which used to require opening the shift sheet to find
 * out.
 */
// Shared, not local: the till screen changes the shift and this only displays
// it, so the two have to read the same thing.
const till = useTillStore()
const context = computed(() => till.context)
const masterOpen = ref(false)

const toast = ref(null)
let toastTimer = null
function onNotify({ message, tone }) {
	toast.value = { message, tone }
	clearTimeout(toastTimer)
	toastTimer = setTimeout(() => (toast.value = null), 2800)
}

const chips = computed(() => {
	const c = context.value
	if (!c) return []

	const out = []
	out.push(
		c.shift
			? { key: 'shift', icon: LucideClock, label: c.shift.name, title: `Shift open since ${c.shift.since}`, tone: 'open' }
			: { key: 'shift', icon: LucideClock, label: 'No shift', title: 'Sales will not reconcile to a shift', tone: 'shut' },
	)
	if (c.branch) {
		out.push({ key: 'branch', icon: LucideStore, label: c.branch, title: `Till ${c.branch}`, tone: 'plain' })
	}
	if (c.warehouse) {
		out.push({
			key: 'warehouse',
			icon: LucideWarehouse,
			label: c.warehouse_label || c.warehouse,
			title: `Selling from ${c.warehouse}`,
			tone: 'plain',
		})
	}
	return out
})

const CHIP_TONES = {
	open: 'bg-surface-green-2 text-ink-green-3',
	shut: 'bg-surface-amber-2 text-ink-amber-3',
	plain: 'bg-surface-gray-2 text-ink-gray-7',
}

onMounted(async () => {
	try {
		me.value = await getMe()
	} catch {
		// Never block the till on this; the corner just stays generic.
		me.value = { full_name: 'Signed in', initials: '··' }
	}
	// Separately, so a failure here cannot cost us the signed-in name.
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

		<div
			class="grid h-6 w-6 place-items-center rounded-full border border-outline-gray-2 text-ink-gray-7"
		>
			<LucideZap class="h-3 w-3" />
		</div>

		<span class="text-p-sm font-medium text-ink-gray-8">{{ title }}</span>

		<!-- Where this session is selling from. Hidden on the narrowest screens,
		     where the cart matters more than the context. -->
		<div class="ml-3 hidden min-w-0 items-center gap-1.5 md:flex">
			<span
				v-for="chip in chips"
				:key="chip.key"
				class="flex max-w-[190px] items-center gap-1 rounded-full px-2 py-0.5 text-p-xs font-medium"
				:class="CHIP_TONES[chip.tone]"
				:title="chip.title"
			>
				<component :is="chip.icon" class="h-3 w-3 shrink-0" aria-hidden="true" />
				<span class="truncate">{{ chip.label }}</span>
			</span>
		</div>

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

			<div
				class="grid h-6 w-6 place-items-center rounded-full bg-surface-gray-7 text-[10px] font-semibold text-ink-white"
				:title="me?.user"
			>
				{{ initials }}
			</div>
			<span class="hidden max-w-[160px] truncate text-p-sm text-ink-gray-7 sm:block">
				{{ displayName }}
			</span>
			<LucideChevronsUpDown class="h-3.5 w-3.5 text-ink-gray-5" />
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
