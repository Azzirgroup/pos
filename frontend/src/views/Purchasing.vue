<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Button, Badge, FormControl } from 'frappe-ui'
import { getPurchasing } from '@/data/api'
import PageHeader from '@/components/PageHeader.vue'
import PillTabs from '@/components/PillTabs.vue'
import StatTiles from '@/components/StatTiles.vue'
import DataTable from '@/components/DataTable.vue'
import ShareSheet from '@/components/ShareSheet.vue'
import DocumentModal from '@/components/DocumentModal.vue'
import { useRowActions } from '@/composables/useRowActions'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideSend from '~icons/lucide/send'

const data = ref({ invoices: [], orders: [], requests: [], totals: {}, period: {} })
const days = ref(30)
const tab = ref('invoices')
const loading = ref(false)

const PERIODS = [
	{ label: 'Last 7 days', value: 7 },
	{ label: 'Last 30 days', value: 30 },
	{ label: 'Last 90 days', value: 90 },
]

const TABS = [
	{ label: 'Invoices', value: 'invoices' },
	{ label: 'Orders', value: 'orders' },
	{ label: 'Requests', value: 'requests' },
]

const COLUMNS = {
	invoices: [
		{ label: 'Invoice', key: 'name', type: 'text' },
		{ label: 'Date', key: 'date', type: 'text' },
		{ label: 'Supplier', key: 'supplier', type: 'text' },
		{ label: 'Status', key: 'status', type: 'text' },
		{ label: 'Total', key: 'grand_total', type: 'currency' },
		{ label: 'Owed', key: 'outstanding_amount', type: 'currency' },
	],
	orders: [
		{ label: 'Order', key: 'name', type: 'text' },
		{ label: 'Date', key: 'date', type: 'text' },
		{ label: 'Supplier', key: 'supplier', type: 'text' },
		{ label: 'Status', key: 'status', type: 'text' },
		{ label: 'Received %', key: 'per_received', type: 'number' },
		{ label: 'Total', key: 'grand_total', type: 'currency' },
	],
	requests: [
		{ label: 'Request', key: 'name', type: 'text' },
		{ label: 'Date', key: 'date', type: 'text' },
		{ label: 'Type', key: 'material_request_type', type: 'text' },
		{ label: 'Status', key: 'status', type: 'text' },
		{ label: 'Ordered %', key: 'per_ordered', type: 'number' },
	],
}

const rows = computed(() => data.value[tab.value] || [])
const columns = computed(() => COLUMNS[tab.value])

/**
 * Columns are passed as a getter because they change with the tab — sharing a
 * row from Orders must describe an order, not the invoice columns that happened
 * to be on screen when the page loaded.
 *
 * All three tabs are real documents, so the share carries the PDF.
 */
const DOCTYPE_BY_TAB = {
	invoices: 'Purchase Invoice',
	orders: 'Purchase Order',
	requests: 'Material Request',
}

/** The documents-hub key for each tab, so the first column can open the row. */
const DOC_KEY_BY_TAB = {
	invoices: 'purchase-invoice',
	orders: 'purchase-order',
	requests: 'material-request',
}

const { shareOpen, sharePayload, shareList, actionsFor } = useRowActions({
	columns: () => columns.value,
	title: (row) => `${row.name}${row.supplier ? ` · ${row.supplier}` : ''}`,
	documentFor: (row) => ({ doctype: DOCTYPE_BY_TAB[tab.value], name: row.name }),
})

const stats = computed(() => {
	const t = data.value.totals || {}
	return [
		{ label: 'Spend', value: t.spend, type: 'currency', icon: 'money' },
		{
			label: 'Owed to suppliers',
			value: t.owed,
			type: 'currency',
			icon: 'truck',
			tone: t.owed > 0 ? 'warn' : 'good',
		},
		{ label: 'Open orders', value: t.open_orders, type: 'number', icon: 'clipboard' },
		{ label: 'Open requests', value: t.open_requests, type: 'number', icon: 'file' },
	]
})

onMounted(load)
watch(days, load)

async function load() {
	loading.value = true
	try {
		data.value = await getPurchasing({ days: days.value })
	} catch (e) {
		console.error('[purchasing]', e)
	} finally {
		loading.value = false
	}
}

/** Open whichever document type this tab is listing. */
const docKey = ref(null)
const docName = ref(null)
const docOpen = ref(false)

function openRow(row) {
	if (!row?.name) return
	docKey.value = DOC_KEY_BY_TAB[tab.value]
	docName.value = row.name
	docOpen.value = true
}
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col overflow-hidden">
		<PageHeader
			title="Purchasing"
			:subtitle="
				data.period?.from ? `${data.period.from} to ${data.period.to}` : 'What we bought and still owe'
			"
		>
			<template #actions>
				<div class="w-[160px]">
					<FormControl type="select" v-model="days" :options="PERIODS" />
				</div>
				<!-- New/Bulk receipt and invoice live on the Receipts and Invoices
				     tabs themselves now, not here — this overview mixes both
				     document types in one table, and "new" only ever means one of
				     them at a time. -->
				<Button
					variant="subtle"
					:icon-left="LucideSend"
					:disabled="!rows.length"
					label="Share list"
					@click="shareList(rows, `Purchasing · ${tab}`)"
				/>
				<Button variant="subtle" :icon-left="LucideRefreshCw" :loading="loading" @click="load" />
			</template>
		</PageHeader>

		<StatTiles :stats="stats" />

		<div class="shrink-0 px-4 pb-2">
			<PillTabs v-model="tab" :buttons="TABS" />
		</div>

		<DataTable
			row-link
			@row-click="openRow"
			:columns="columns"
			:rows="rows"
			row-key="name"
			:loading="loading"
			:actions="actionsFor"
			:empty-text="`No ${tab} in this period.`"
		>
			<template #cell-status="{ value }">
				<Badge
					:theme="['Completed', 'Paid', 'Received'].includes(value) ? 'green' : value === 'Overdue' ? 'red' : 'gray'"
					variant="subtle"
					:label="value || '—'"
				/>
			</template>
		</DataTable>

		<ShareSheet v-model="shareOpen" :payload="sharePayload" />
		<DocumentModal v-model:open="docOpen" :doc-key="docKey" :name="docName" />
	</div>
</template>
