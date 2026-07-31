<script setup>
import { ref, computed, onMounted } from 'vue'
import { Button, Badge } from 'frappe-ui'
import { getAccounts } from '@/data/api'
import PageHeader from '@/components/PageHeader.vue'
import StatTiles from '@/components/StatTiles.vue'
import DataTable from '@/components/DataTable.vue'
import ShareSheet from '@/components/ShareSheet.vue'
import { useRowActions } from '@/composables/useRowActions'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideSend from '~icons/lucide/send'

const data = ref({ balances: [], receivable: 0, payable: 0, cash_total: 0, bank_total: 0 })
const loading = ref(false)

const COLUMNS = [
	{ label: 'Account', key: 'label', type: 'text' },
	{ label: 'Type', key: 'type', type: 'text' },
	{ label: 'Balance', key: 'balance', type: 'currency' },
]

const { shareOpen, sharePayload, shareList, actionsFor } = useRowActions({
	columns: COLUMNS,
	title: (row) => row.label || row.account,
})

const stats = computed(() => [
	{ label: 'Cash on hand', value: data.value.cash_total, type: 'currency' },
	{ label: 'In the bank', value: data.value.bank_total, type: 'currency' },
	{
		label: 'Customers owe us',
		value: data.value.receivable,
		type: 'currency',
		tone: data.value.receivable > 0 ? 'warn' : 'good',
	},
	{
		label: 'We owe suppliers',
		value: data.value.payable,
		type: 'currency',
		tone: data.value.payable > 0 ? 'bad' : 'good',
	},
])

onMounted(load)

async function load() {
	loading.value = true
	try {
		data.value = await getAccounts()
	} catch (e) {
		console.error('[accounts]', e)
	} finally {
		loading.value = false
	}
}
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col overflow-hidden">
		<PageHeader title="Accounts" subtitle="Where the money is, and which way it is owed">
			<template #actions>
				<Button
					variant="subtle"
					:icon-left="LucideSend"
					:disabled="!data.balances.length"
					label="Share list"
					@click="shareList(data.balances, 'Account balances')"
				/>
				<Button variant="subtle" :icon-left="LucideRefreshCw" :loading="loading" @click="load" />
			</template>
		</PageHeader>

		<StatTiles :stats="stats" />

		<DataTable
			:columns="COLUMNS"
			:rows="data.balances"
			row-key="account"
			:loading="loading"
			:actions="actionsFor"
			empty-text="No cash or bank accounts configured for this company."
		>
			<template #cell-type="{ value }">
				<Badge :theme="value === 'Cash' ? 'green' : 'blue'" variant="subtle" :label="value" />
			</template>
		</DataTable>

		<ShareSheet v-model="shareOpen" :payload="sharePayload" />
	</div>
</template>
