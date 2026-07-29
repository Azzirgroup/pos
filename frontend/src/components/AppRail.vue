<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import LucideHome from '~icons/lucide/house'
import LucideShoppingCart from '~icons/lucide/shopping-cart'
import LucideBoxes from '~icons/lucide/boxes'
import LucideTruck from '~icons/lucide/truck'
import LucideReceipt from '~icons/lucide/receipt-text'
import LucideLandmark from '~icons/lucide/landmark'
import LucideTriangleAlert from '~icons/lucide/triangle-alert'
import LucideUsers from '~icons/lucide/users'
import LucideSettings from '~icons/lucide/settings-2'
import LucideChartColumn from '~icons/lucide/chart-column'

const props = defineProps({
	/** 'icons' | 'labels'. 'hidden' is handled by the shell not rendering us. */
	mode: { type: String, default: 'icons' },
})

const route = useRoute()
const router = useRouter()

const expanded = computed(() => props.mode === 'labels')

/**
 * Module rail. Collapsed to icons by default: this column is permanent, so
 * every pixel it takes is taken from the item grid for the whole shift.
 */
const GROUPS = [
	[
		{ to: '/dashboard', icon: LucideHome, label: 'Dashboard' },
		{ to: '/pos', icon: LucideShoppingCart, label: 'Point of sale' },
	],
	[
		{ to: '/inventory', icon: LucideBoxes, label: 'Inventory' },
		{ to: '/reorder', icon: LucideTriangleAlert, label: 'Reorder levels' },
		{ to: '/purchasing', icon: LucideTruck, label: 'Purchasing' },
	],
	[
		{ to: '/sales', icon: LucideReceipt, label: 'Sales' },
		{ to: '/customers', icon: LucideUsers, label: 'Customers' },
		{ to: '/accounts', icon: LucideLandmark, label: 'Accounts' },
	],
	// Documents and Records were removed from here on purpose: every document
	// type now sits inside the module it belongs to, in the order the paperwork
	// happens, and records are reached from the "New" button and from the
	// Suppliers / Customers / Accounts tabs. Both routes still exist for anyone
	// who has one bookmarked.
	[{ to: '/reports', icon: LucideChartColumn, label: 'Reports' }],
]

function isActive(to) {
	return route.path.startsWith(to)
}
</script>

<template>
	<nav
		class="flex shrink-0 flex-col border-r border-outline-gray-2 bg-surface-white py-2 transition-[width] duration-150"
		:class="expanded ? 'w-[180px] items-stretch px-2' : 'w-[52px] items-center'"
	>
		<template v-for="(group, gi) in GROUPS" :key="gi">
			<div v-if="gi > 0" class="my-1.5 h-px bg-outline-gray-2" :class="expanded ? 'mx-1' : 'w-6'" />
			<button
				v-for="item in group"
				:key="item.to"
				class="group relative my-0.5 flex h-9 items-center rounded-lg transition-colors"
				:class="[
					expanded ? 'w-full gap-2.5 px-2.5' : 'w-9 justify-center',
					isActive(item.to)
						? 'bg-surface-gray-3 font-medium text-ink-gray-9'
						: 'text-ink-gray-6 hover:bg-surface-gray-2 hover:text-ink-gray-8',
				]"
				:aria-label="item.label"
				@click="router.push(item.to)"
			>
				<component :is="item.icon" class="h-[18px] w-[18px] shrink-0" />
				<span v-if="expanded" class="truncate text-p-sm">{{ item.label }}</span>
				<!-- Tooltip only when collapsed; with labels shown it would duplicate. -->
				<span
					v-else
					class="pointer-events-none absolute left-full top-1/2 z-50 ml-2 -translate-y-1/2 whitespace-nowrap rounded-md bg-surface-gray-7 px-2 py-1 text-p-xs font-medium text-ink-white opacity-0 shadow-md transition-opacity group-hover:opacity-100"
				>
					{{ item.label }}
				</span>
			</button>
		</template>

		<div class="mt-auto" :class="expanded ? '' : 'flex flex-col items-center'">
			<button
				class="flex h-9 items-center rounded-lg transition-colors"
				:class="[
					expanded ? 'w-full gap-2.5 px-2.5' : 'w-9 justify-center',
					isActive('/settings')
						? 'bg-surface-gray-3 font-medium text-ink-gray-9'
						: 'text-ink-gray-6 hover:bg-surface-gray-2 hover:text-ink-gray-8',
				]"
				aria-label="Settings"
				@click="router.push('/settings')"
			>
				<LucideSettings class="h-[18px] w-[18px] shrink-0" />
				<span v-if="expanded" class="truncate text-p-sm">Settings</span>
			</button>
		</div>
	</nav>
</template>
