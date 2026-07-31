<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Button, FormControl } from 'frappe-ui'
import { getInventory, getWarehouses } from '@/data/api'
import PageHeader from '@/components/PageHeader.vue'
import StatTiles from '@/components/StatTiles.vue'
import DataTable from '@/components/DataTable.vue'
import ShareSheet from '@/components/ShareSheet.vue'
import { useRowActions } from '@/composables/useRowActions'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideSend from '~icons/lucide/send'

const rows = ref([])
const totals = ref({ value: 0, lines: 0 })
const warehouses = ref([])
// Select filters out options with a falsy value, so 'all' needs a real token.
const ALL = '__all__'
const warehouse = ref(ALL)
const search = ref('')
const loading = ref(false)

const COLUMNS = [
	{ label: 'Item', key: 'item_name', type: 'text' },
	{ label: 'Code', key: 'item_code', type: 'text' },
	{ label: 'Warehouse', key: 'warehouse', type: 'text' },
	{ label: 'On hand', key: 'actual_qty', type: 'number' },
	{ label: 'Reserved', key: 'reserved_qty', type: 'number' },
	{ label: 'Projected', key: 'projected_qty', type: 'number' },
	{ label: 'Rate', key: 'valuation_rate', type: 'currency' },
	{ label: 'Value', key: 'value', type: 'currency' },
]

// A stock line is not a document, so this shares the figures as text — which is
// what "how many of these have we got?" is answered with anyway.
const { shareOpen, sharePayload, shareList, actionsFor } = useRowActions({
	columns: COLUMNS,
	title: (row) => `${row.item_name || row.item_code} · ${row.warehouse}`,
})

const stats = computed(() => [
	{ label: 'Stock value', value: totals.value.value, type: 'currency' },
	{ label: 'Stock lines', value: totals.value.lines, type: 'number' },
	{
		label: 'Reserved',
		value: rows.value.reduce((s, r) => s + Number(r.reserved_qty || 0), 0),
		type: 'number',
		tone: 'warn',
	},
	{
		label: 'Locations',
		value: new Set(rows.value.map((r) => r.warehouse)).size,
		type: 'number',
	},
])

const warehouseOptions = computed(() => [
	{ label: 'All warehouses', value: ALL },
	...warehouses.value.map((w) => ({ label: w.label, value: w.name })),
])

onMounted(async () => {
	warehouses.value = await getWarehouses().catch(() => [])
	load()
})

let timer = null
watch([warehouse, search], () => {
	clearTimeout(timer)
	timer = setTimeout(load, 250)
})

async function load() {
	loading.value = true
	try {
		const data = await getInventory({ warehouse: warehouse.value === ALL ? null : warehouse.value, search: search.value })
		rows.value = data.rows || []
		totals.value = data.totals || { value: 0, lines: 0 }
	} catch (e) {
		console.error('[inventory]', e)
		rows.value = []
	} finally {
		loading.value = false
	}
}
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col overflow-hidden">
		<PageHeader title="Inventory" subtitle="Stock on hand and what it is worth">
			<template #actions>
				<div class="w-[190px]">
					<FormControl type="select" v-model="warehouse" :options="warehouseOptions" />
				</div>
				<div class="w-[190px]">
					<FormControl v-model="search" type="text" placeholder="Search item…" />
				</div>
				<Button
					variant="subtle"
					:icon-left="LucideSend"
					:disabled="!rows.length"
					label="Share list"
					@click="shareList(rows, 'Stock on hand')"
				/>
				<Button variant="subtle" :icon-left="LucideRefreshCw" :loading="loading" @click="load" />
			</template>
		</PageHeader>

		<StatTiles :stats="stats" />
		<DataTable
			:columns="COLUMNS"
			:rows="rows"
			:loading="loading"
			:actions="actionsFor"
			empty-text="No stock found. Receive stock, or clear the filters."
		/>

		<ShareSheet v-model="shareOpen" :payload="sharePayload" />
	</div>
</template>
