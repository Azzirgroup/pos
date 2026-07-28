<script setup>
import { ref } from 'vue'
import DataTable from '@/components/DataTable.vue'

/**
 * The frame every chart on the dashboard sits in.
 *
 * It exists for one reason: the table toggle. A chart that can only be read by
 * eye excludes anyone who cannot separate its colours, and it hides the exact
 * figures from everyone else. Putting the twin here means each chart gets one
 * without three components each growing their own.
 */
defineProps({
	title: { type: String, required: true },
	subtitle: { type: String, default: '' },
	/** The same data as the chart, as a table. [{label, key, type}] + rows. */
	columns: { type: Array, default: () => [] },
	rows: { type: Array, default: () => [] },
	emptyText: { type: String, default: 'Nothing to show for this period.' },
})

const asTable = ref(false)
</script>

<template>
	<section class="flex min-w-0 flex-col rounded-lg border border-outline-gray-2 bg-surface-white">
		<header class="flex items-start gap-3 px-4 pb-1 pt-3">
			<div class="min-w-0 flex-1">
				<h2 class="truncate text-p-sm font-semibold text-ink-gray-8">{{ title }}</h2>
				<p v-if="subtitle" class="truncate text-p-xs text-ink-gray-5">{{ subtitle }}</p>
			</div>
			<div class="flex shrink-0 rounded-md bg-surface-gray-2 p-0.5" role="group" aria-label="View as">
				<button
					v-for="opt in [
						{ label: 'Chart', table: false },
						{ label: 'Table', table: true },
					]"
					:key="opt.label"
					class="rounded px-2 py-0.5 text-p-xs transition-colors"
					:class="
						asTable === opt.table
							? 'bg-surface-white font-medium text-ink-gray-8 shadow-sm'
							: 'text-ink-gray-6 hover:text-ink-gray-8'
					"
					:aria-pressed="asTable === opt.table"
					@click="asTable = opt.table"
				>
					{{ opt.label }}
				</button>
			</div>
		</header>

		<div v-if="!rows.length" class="grid h-40 place-items-center px-6 text-center">
			<p class="text-p-sm text-ink-gray-5">{{ emptyText }}</p>
		</div>

		<!-- The table twin is the same numbers, not a summary of them. -->
		<div v-else-if="asTable" class="max-h-[280px] min-h-0 overflow-auto">
			<DataTable :columns="columns" :rows="rows" :empty-text="emptyText" />
		</div>

		<div v-else class="min-w-0 px-4 pb-4 pt-2">
			<slot />
		</div>
	</section>
</template>
