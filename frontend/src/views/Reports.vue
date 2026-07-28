<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Button, FormControl } from 'frappe-ui'
import { listReports, runReport, getWarehouses } from '@/data/api'
import { useRoute } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import DataTable from '@/components/DataTable.vue'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideDownload from '~icons/lucide/download'

const route = useRoute()
// Some routes are a single named report (Receivables, Stock movement …). They
// reuse this view with the subject locked, rather than duplicating the table.
const pinned = computed(() => route.meta?.report || null)

const reports = ref([])
const active = ref(route.meta?.report || 'sales_summary')
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

/** Reports grouped as the rail groups modules, so the list stays scannable. */
const grouped = computed(() => {
	const m = {}
	for (const r of reports.value) (m[r.group] ||= []).push(r)
	return m
})

const activeReport = computed(() => reports.value.find((r) => r.key === active.value))
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
	run()
})

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
			v-if="!pinned"
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
					<div v-if="!pinned" class="w-[170px] lg:hidden">
						<FormControl
						type="select"
							v-model="active"
							:options="reports.map((r) => ({ label: r.label, value: r.key }))"
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
				</template>
			</PageHeader>

			<DataTable
				:columns="result.columns"
				:rows="result.rows"
				:loading="loading"
				empty-text="Nothing to report for this period."
			/>
		</div>
	</div>
</template>
