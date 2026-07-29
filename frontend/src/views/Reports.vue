<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Button, FormControl } from 'frappe-ui'
import { listReports, runReport, getWarehouses } from '@/data/api'
import { useRoute } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import DataTable from '@/components/DataTable.vue'
import ShareSheet from '@/components/ShareSheet.vue'
import { useRowActions } from '@/composables/useRowActions'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideDownload from '~icons/lucide/download'
import LucideSend from '~icons/lucide/send'

/**
 * Also used inside the documents hub, where the report list is narrowed to the
 * ones that say something about the document type on screen. Props win over
 * route meta so the same component serves a route and an embed without either
 * knowing about the other.
 */
const props = defineProps({
	/** Lock the view to one report. */
	report: { type: String, default: null },
	/** Restrict the picker to these report keys. */
	only: { type: Array, default: null },
	/** Inside another screen: no left rail, no duplicated page title. */
	embedded: { type: Boolean, default: false },
})

const route = useRoute()
// Some routes are a single named report (Receivables, Stock movement …). They
// reuse this view with the subject locked, rather than duplicating the table.
const pinned = computed(() => props.report || route.meta?.report || null)

const reports = ref([])
const active = ref(props.report || route.meta?.report || props.only?.[0] || 'sales_summary')
const days = ref(30)
// Select filters out options with a falsy value, so 'all' needs a real token.
const ALL = '__all__'
const warehouse = ref(ALL)
const warehouses = ref([])
const result = ref({ columns: [], rows: [], totals: {} })
const loading = ref(false)

const PERIODS = [
	{ label: 'Last 7 days', value: 7 },
	{ label: 'Last 30 days', value: 30 },
	{ label: 'Last 90 days', value: 90 },
	{ label: 'Last year', value: 365 },
]

/** The reports this instance may show, in the order the caller asked for. */
const available = computed(() => {
	if (!props.only?.length) return reports.value
	return props.only.map((key) => reports.value.find((r) => r.key === key)).filter(Boolean)
})

/** Reports grouped as the rail groups modules, so the list stays scannable. */
const grouped = computed(() => {
	const m = {}
	for (const r of available.value) (m[r.group] ||= []).push(r)
	return m
})

const activeReport = computed(() => reports.value.find((r) => r.key === active.value))

/**
 * Report rows are computed figures, not documents, so there is nothing to
 * attach — the numbers are the message. Columns come through as a getter
 * because every report has its own.
 */
const { shareOpen, sharePayload, shareList, actionsFor } = useRowActions({
	columns: () => result.value.columns || [],
	title: () => activeReport.value?.label || 'Report',
})

// Only stock reports vary by location; showing the picker elsewhere implies a
// filter that does nothing.
const usesWarehouse = computed(() => activeReport.value?.group === 'Inventory')

const warehouseOptions = computed(() => [
	{ label: 'All warehouses', value: ALL },
	...warehouses.value.map((w) => ({ label: w.label, value: w.name })),
])

onMounted(async () => {
	const [list, whs] = await Promise.all([
		listReports().catch(() => []),
		getWarehouses().catch(() => []),
	])
	reports.value = list
	warehouses.value = whs
	// An embedded picker may not include whatever the default was.
	if (props.only?.length && !props.only.includes(active.value)) active.value = props.only[0]
	run()
})

// The hub keeps one mounted instance and swaps the doctype under it, so the
// allowed list changing has to move the selection with it.
watch(
	() => props.only,
	(only) => {
		if (only?.length && !only.includes(active.value)) active.value = only[0]
	},
)

watch([active, days, warehouse], run)

async function run() {
	loading.value = true
	try {
		result.value = await runReport({
			report: active.value,
			days: days.value,
			warehouse: usesWarehouse.value && warehouse.value !== ALL ? warehouse.value : null,
		})
	} catch (e) {
		console.error('[reports]', e)
		result.value = { columns: [], rows: [], totals: {} }
	} finally {
		loading.value = false
	}
}

/** CSV, because the next thing a manager does with a report is mail it. */
function exportCsv() {
	const cols = result.value.columns
	const head = cols.map((c) => `"${c.label}"`).join(',')
	const body = result.value.rows
		.map((r) => cols.map((c) => `"${String(r[c.key] ?? '').replace(/"/g, '""')}"`).join(','))
		.join('\n')

	const blob = new Blob([`${head}\n${body}`], { type: 'text/csv;charset=utf-8;' })
	const url = URL.createObjectURL(blob)
	const a = document.createElement('a')
	a.href = url
	a.download = `${active.value}-${new Date().toISOString().slice(0, 10)}.csv`
	a.click()
	URL.revokeObjectURL(url)
}
</script>

<template>
	<div class="flex min-h-0 flex-1 overflow-hidden">
		<!-- Report picker. A permanent list beats a dropdown here: a manager
		     compares several reports in one sitting. -->
		<aside
			v-if="!pinned && !embedded"
			class="hidden w-[200px] shrink-0 overflow-y-auto border-r border-outline-gray-2 bg-surface-white py-2 lg:block"
		>
			<div v-for="(items, group) in grouped" :key="group" class="mb-3">
				<div class="px-3 pb-1 text-p-xs font-medium uppercase tracking-wide text-ink-gray-5">
					{{ group }}
				</div>
				<button
					v-for="r in items"
					:key="r.key"
					class="block w-full px-3 py-1.5 text-left text-p-sm transition-colors"
					:class="
						active === r.key
							? 'bg-surface-gray-3 font-medium text-ink-gray-9'
							: 'text-ink-gray-7 hover:bg-surface-gray-2'
					"
					@click="active = r.key"
				>
					{{ r.label }}
				</button>
			</div>
		</aside>

		<div class="flex min-w-0 flex-1 flex-col overflow-hidden">
			<PageHeader
				:title="activeReport?.label || 'Reports'"
				:subtitle="`${result.rows.length} row${result.rows.length === 1 ? '' : 's'}`"
			>
				<template #actions>
					<!-- Embedded, the picker is a short row of chips: the list is already
					     narrowed to this document type, so a rail would be a column of
					     three items beside a table. -->
					<div v-if="embedded && available.length > 1" class="flex flex-wrap items-center gap-1">
						<button
							v-for="r in available"
							:key="r.key"
							class="rounded-md px-2.5 py-1.5 text-p-sm transition-colors"
							:class="
								active === r.key
									? 'bg-surface-gray-3 font-medium text-ink-gray-9'
									: 'text-ink-gray-6 hover:bg-surface-gray-2 hover:text-ink-gray-8'
							"
							@click="active = r.key"
						>
							{{ r.label }}
						</button>
					</div>
					<div v-else-if="!pinned && !embedded" class="w-[170px] lg:hidden">
						<FormControl
						type="select"
							v-model="active"
							:options="available.map((r) => ({ label: r.label, value: r.key }))"
						/>
					</div>
					<div v-if="usesWarehouse" class="w-[180px]">
						<FormControl type="select" v-model="warehouse" :options="warehouseOptions" />
					</div>
					<div class="w-[150px]">
						<FormControl type="select" v-model="days" :options="PERIODS" />
					</div>
					<Button variant="subtle" :icon-left="LucideRefreshCw" :loading="loading" @click="run" />
					<Button
						variant="subtle"
						:icon-left="LucideDownload"
						label="CSV"
						:disabled="!result.rows.length"
						@click="exportCsv"
					/>
					<!-- CSV is for a spreadsheet; this is for a person. A report that
					     has to be downloaded, opened and re-attached does not reach
					     the person who asked for it over the phone. -->
					<Button
						variant="subtle"
						:icon-left="LucideSend"
						label="Share"
						:disabled="!result.rows.length"
						@click="shareList(result.rows, activeReport?.label || 'Report')"
					/>
				</template>
			</PageHeader>

			<DataTable
				:columns="result.columns"
				:rows="result.rows"
				:loading="loading"
				:actions="actionsFor"
				empty-text="Nothing to report for this period."
			/>

			<ShareSheet v-model="shareOpen" :payload="sharePayload" />
		</div>
	</div>
</template>
