<script setup>
import { computed } from 'vue'
import LucideSunrise from '~icons/lucide/sunrise'
import LucideSunset from '~icons/lucide/sunset'
import LucideLayers from '~icons/lucide/layers'
import LucideScanLine from '~icons/lucide/scan-line'
import LucideUserRound from '~icons/lucide/user-round'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideStore from '~icons/lucide/store'

const props = defineProps({
	/** 'rail' docks it beside the grid; 'sheet' stacks it inside a bottom sheet. */
	variant: { type: String, default: 'rail' },
	shift: { type: Object, default: null },
	heldCount: { type: Number, default: 0 },
	customer: { type: Object, default: null },
	cameraScan: { type: Boolean, default: false },
	refreshing: { type: Boolean, default: false },
	isDemo: { type: Boolean, default: false },
})

const emit = defineEmits(['shift', 'held', 'scan', 'customer', 'refresh'])

const actions = computed(() =>
	[
		{
			key: 'shift',
			label: props.shift ? 'Close shift' : 'Open shift',
			hint: props.shift ? props.shift.pos_profile : 'Till closed',
			icon: props.shift ? LucideSunset : LucideSunrise,
			// The dot is the only always-visible signal that the till is open.
			dot: props.shift ? 'open' : 'closed',
			event: 'shift',
		},
		{
			key: 'held',
			label: 'Held sales',
			hint: props.heldCount ? `${props.heldCount} parked` : 'None parked',
			icon: LucideLayers,
			badge: props.heldCount || null,
			event: 'held',
		},
		// Only shown where the browser can actually scan — a dead button at a busy
		// counter is worse than no button.
		props.cameraScan && {
			key: 'scan',
			label: 'Scan',
			hint: 'Use the camera',
			icon: LucideScanLine,
			event: 'scan',
		},
		{
			key: 'customer',
			label: 'Customer',
			hint: props.customer ? props.customer.customer_name || props.customer.name : 'Walk-in',
			icon: LucideUserRound,
			active: Boolean(props.customer),
			event: 'customer',
		},
		{
			key: 'refresh',
			label: 'Refresh',
			hint: props.isDemo ? 'Demo items' : 'Prices & stock',
			icon: LucideRefreshCw,
			spinning: props.refreshing,
			event: 'refresh',
		},
	].filter(Boolean),
)
</script>

<template>
	<!-- Rail: icon-first, because at a counter these are muscle memory, not reading. -->
	<nav
		v-if="variant === 'rail'"
		class="flex w-[76px] shrink-0 flex-col items-center gap-1 border-r border-outline-gray-2 bg-surface-white py-3"
	>
		<button
			v-for="a in actions"
			:key="a.key"
			class="relative grid w-[64px] place-items-center gap-1 rounded-xl px-1 py-2.5 transition-colors"
			:class="
				a.active
					? 'bg-surface-gray-3 text-ink-gray-9'
					: 'text-ink-gray-7 hover:bg-surface-gray-2 active:bg-surface-gray-3'
			"
			:title="`${a.label} — ${a.hint}`"
			@click="emit(a.event)"
		>
			<component
				:is="a.icon"
				class="h-[22px] w-[22px]"
				:class="a.spinning && 'animate-spin'"
			/>
			<span class="text-[11px] font-medium leading-tight">{{ a.label }}</span>

			<span
				v-if="a.badge"
				class="absolute right-1.5 top-1.5 grid h-5 min-w-5 place-items-center rounded-full bg-surface-gray-7 px-1 text-p-xs font-semibold text-ink-white"
			>
				{{ a.badge }}
			</span>
			<span
				v-else-if="a.dot"
				class="absolute right-2.5 top-2.5 h-2 w-2 rounded-full"
				:class="a.dot === 'open' ? 'bg-surface-green-3' : 'bg-surface-gray-4'"
			/>
		</button>

		<div class="mt-auto flex flex-col items-center gap-1 px-1 pt-2 text-center">
			<LucideStore class="h-4 w-4 text-ink-gray-4" />
			<span class="text-[10px] leading-tight text-ink-gray-5">
				{{ shift ? shift.pos_profile : 'No shift' }}
			</span>
		</div>
	</nav>

	<!-- Sheet: same actions, laid out as full-width rows for thumbs. -->
	<div v-else class="flex flex-col gap-1.5 px-4 pb-5">
		<button
			v-for="a in actions"
			:key="a.key"
			class="flex min-h-touch items-center gap-3 rounded-xl border border-outline-gray-2 px-3.5 py-3 text-left transition-colors hover:bg-surface-gray-2"
			@click="emit(a.event)"
		>
			<component
				:is="a.icon"
				class="h-5 w-5 shrink-0 text-ink-gray-6"
				:class="a.spinning && 'animate-spin'"
			/>
			<div class="min-w-0 flex-1">
				<div class="text-p-base font-medium text-ink-gray-9">{{ a.label }}</div>
				<div class="truncate text-p-sm text-ink-gray-5">{{ a.hint }}</div>
			</div>
			<span
				v-if="a.badge"
				class="grid h-6 min-w-6 shrink-0 place-items-center rounded-full bg-surface-gray-7 px-1.5 text-p-xs font-semibold text-ink-white"
			>
				{{ a.badge }}
			</span>
			<span
				v-else-if="a.dot"
				class="h-2.5 w-2.5 shrink-0 rounded-full"
				:class="a.dot === 'open' ? 'bg-surface-green-3' : 'bg-surface-gray-4'"
			/>
		</button>
	</div>
</template>
