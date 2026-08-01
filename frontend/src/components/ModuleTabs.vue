<script setup>
import { useRoute, useRouter } from 'vue-router'

/**
 * Activities within a module. The rail says which module you are in; this says
 * what you can do there, so neither has to carry both jobs.
 */
defineProps({
	/** [{ label, to, badge }] */
	tabs: { type: Array, required: true },
})

const route = useRoute()
const router = useRouter()
</script>

<template>
	<nav
		class="flex shrink-0 items-center gap-4 overflow-x-auto border-b border-outline-gray-2 bg-surface-white px-4 py-2.5"
	>
		<button
			v-for="t in tabs"
			:key="t.to"
			class="flex shrink-0 items-center gap-1.5 rounded-lg px-4 py-2 text-p-sm transition-colors"
			:class="
				route.path === t.to
					? 'bg-surface-violet-1 font-medium text-violet-600 ring-1 ring-violet-200'
					: 'text-ink-gray-6 hover:bg-surface-gray-2 hover:text-ink-gray-8'
			"
			@click="router.push(t.to)"
		>
			{{ t.label }}
			<span
				v-if="t.badge"
				class="tabular rounded-full bg-surface-red-5 px-1.5 text-[10px] font-semibold text-ink-white"
			>
				{{ t.badge }}
			</span>
		</button>
	</nav>
</template>
