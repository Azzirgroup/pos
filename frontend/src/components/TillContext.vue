<script setup>
import { ref, computed, onMounted } from 'vue'
import { getMe } from '@/data/api'
import { useTillStore } from '@/stores/till'
import LucideStore from '~icons/lucide/store'
import LucideWarehouse from '~icons/lucide/warehouse'
import LucideClock from '~icons/lucide/clock'

/**
 * Who is selling, from which till, out of which warehouse.
 *
 * Lives on the POS rather than in the app shell, because it is only true of the
 * POS. In the header it sat above every screen — reorder levels, the dashboard,
 * settings — announcing a warehouse that had nothing to do with what was on
 * screen, and taking the width that the page's own title needed.
 *
 * It matters here and only here: a cashier covering someone else's counter has
 * no other way to know which warehouse the sale draws stock from, and a wrong
 * one stays invisible until a stock report is wrong a week later. The shift chip
 * doubles as "am I open?", which otherwise takes opening a sheet to answer.
 */
const till = useTillStore()
const context = computed(() => till.context)

const me = ref(null)
const displayName = computed(() => me.value?.full_name || '…')
const initials = computed(() => me.value?.initials || '··')

onMounted(async () => {
	try {
		me.value = await getMe()
	} catch {
		// The till must never wait on this; the corner just stays generic.
		me.value = { full_name: 'Signed in', initials: '··' }
	}
})

const chips = computed(() => {
	const c = context.value
	if (!c) return []

	const out = [
		c.shift
			? {
					key: 'shift',
					icon: LucideClock,
					label: c.shift.name,
					title: `Shift open since ${c.shift.since}`,
					tone: 'open',
				}
			: {
					key: 'shift',
					icon: LucideClock,
					label: 'No shift',
					title: 'Sales will not reconcile to a shift',
					tone: 'shut',
				},
	]

	if (c.branch) {
		out.push({
			key: 'branch',
			icon: LucideStore,
			label: c.branch,
			title: `Till ${c.branch}`,
			tone: 'plain',
		})
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
</script>

<template>
	<div class="flex min-w-0 items-center gap-1.5">
		<span
			v-for="chip in chips"
			:key="chip.key"
			class="flex max-w-[170px] items-center gap-1 rounded-full px-2 py-0.5 text-p-xs font-medium"
			:class="CHIP_TONES[chip.tone]"
			:title="chip.title"
		>
			<component :is="chip.icon" class="h-3 w-3 shrink-0" aria-hidden="true" />
			<span class="truncate">{{ chip.label }}</span>
		</span>

		<!-- The account the sale will be recorded against. Beside the till context
		     rather than in the corner of the app, because "who is signed in" is
		     the same question as "whose shift is this". -->
		<span
			class="flex items-center gap-1.5 rounded-full bg-surface-gray-2 py-0.5 pl-0.5 pr-2"
			:title="me?.user"
		>
			<span
				class="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-surface-gray-7 text-[9px] font-semibold text-ink-white"
			>
				{{ initials }}
			</span>
			<span class="hidden max-w-[120px] truncate text-p-xs font-medium text-ink-gray-7 sm:block">
				{{ displayName }}
			</span>
		</span>
	</div>
</template>
