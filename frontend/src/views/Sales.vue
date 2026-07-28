<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Button, Badge, FormControl } from 'frappe-ui'
import { getSales } from '@/data/api'
import PageHeader from '@/components/PageHeader.vue'
import StatTiles from '@/components/StatTiles.vue'
import DataTable from '@/components/DataTable.vue'
import LucideRefreshCw from '~icons/lucide/refresh-cw'

const rows = ref([])
const totals = ref({})
const period = ref({})
const days = ref(30)
const loading = ref(false)

const PERIODS = [
	{ label: 'Last 7 days', value: 7 },
	{ label: 'Last 30 days', value: 30 },
	{ label: 'Last 90 days', value: 90 },
	{ label: 'Last year', value: 365 },
]

const COLUMNS = [
	{ label: 'Invoice', key: 'name', type: 'text' },
	{ label: 'Date', key: 'posting_date', type: 'text' },
	{ label: 'Customer', key: 'customer', type: 'text' },
	{ label: 'Channel', key: 'is_pos', type: 'text' },
	{ label: 'Status', key: 'status', type: 'text' },
	{ label: 'Total', key: 'grand_total', type: 'currency' },
	{ label: 'Outstanding', key: 'outstanding_amount', type: 'currency' },
]

const stats = computed(() => [
	{ label: 'Revenue', value: totals.value.revenue, type: 'currency' },
	{ label: 'Invoices', value: totals.value.count, type: 'number' },
	{
		label: 'Unpaid',
		value: totals.value.outstanding,
		type: 'currency',
		tone: totals.value.outstanding > 0 ? 'warn' : 'good',
	},
	{ label: 'Over the counter', value: totals.value.pos, type: 'number' },
])

onMounted(load)
watch(days, load)

async function load() {
	loading.value = true
	try {
		const data = await getSales({ days: days.value })
		rows.value = data.rows || []
		totals.value = data.totals || {}
		period.value = data.period || {}
	} catch (e) {
		console.error('[sales]', e)
		rows.value = []
	} finally {
		loading.value = false
	}
}
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col overflow-hidden">
		<PageHeader
			title="Sales"
			:subtitle="period.from ? `${period.from} to ${period.to}` : 'Invoices raised at the till and off it'"
		>
			<template #actions>
				<div class="w-[160px]">
					<FormControl type="select" v-model="days" :options="PERIODS" />
				</div>
				<Button variant="subtle" :icon-left="LucideRefreshCw" :loading="loading" @click="load" />
			</template>
		</PageHeader>

		<StatTiles :stats="stats" />
		<DataTable
			:columns="COLUMNS"
			:rows="rows"
			row-key="name"
			:loading="loading"
			empty-text="No sales in this period."
		>
			<!-- is_pos is a flag in the data but a word to a human. -->
			<template #cell-is_pos="{ value }">
				<Badge
					:theme="value ? 'green' : 'gray'"
					variant="subtle"
					:label="value ? 'Till' : 'Invoice'"
				/>
			</template>
			<template #cell-status="{ value }">
				<Badge
					:theme="value === 'Paid' ? 'green' : value === 'Overdue' ? 'red' : 'gray'"
					variant="subtle"
					:label="value || '—'"
				/>
			</template>
		</DataTable>
	</div>
</template>
