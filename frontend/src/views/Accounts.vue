<script setup>
import { ref, computed, onMounted } from 'vue'
import { Button, Badge } from 'frappe-ui'
import { getAccounts } from '@/data/api'
import PageHeader from '@/components/PageHeader.vue'
import StatTiles from '@/components/StatTiles.vue'
import DataTable from '@/components/DataTable.vue'
import ShareSheet from '@/components/ShareSheet.vue'
import { useRowActions } from '@/composables/useRowActions'
import MoneySheet from '@/components/MoneySheet.vue'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideSend from '~icons/lucide/send'
import LucideArrowDownLeft from '~icons/lucide/arrow-down-left'
import LucideArrowUpRight from '~icons/lucide/arrow-up-right'
import LucideArrowLeftRight from '~icons/lucide/arrow-left-right'

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
	{ label: 'Cash on hand', value: data.value.cash_total, type: 'currency', icon: 'money' },
	{ label: 'In the bank', value: data.value.bank_total, type: 'currency', icon: 'landmark' },
	{
		label: 'Customers owe us',
		value: data.value.receivable,
		type: 'currency',
		icon: 'users',
		tone: data.value.receivable > 0 ? 'warn' : 'good',
	},
	{
		label: 'We owe suppliers',
		value: data.value.payable,
		type: 'currency',
		icon: 'truck',
		tone: data.value.payable > 0 ? 'bad' : 'good',
	},
])

/**
 * The three things a shop does with money, next to the balances they change.
 *
 * They were all reachable already — receiving through the credit screen, paying
 * a supplier only from the desk, transferring not at all — but not from the
 * screen that shows the balances, which is where somebody is standing when they
 * decide to do one. See `MoneySheet` for why one dialog serves all three.
 */
const moneyOpen = ref(false)
const moneyMode = ref('transfer')
const toast = ref(null)

function openMoney(mode) {
	moneyMode.value = mode
	moneyOpen.value = true
}

function notify({ message, tone }) {
	toast.value = { message, tone }
	setTimeout(() => (toast.value = null), 3500)
}

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

		<!-- Directly under the figures each one moves. -->
		<div class="grid shrink-0 grid-cols-1 gap-2 px-4 pb-3 sm:grid-cols-3">
			<Button
				variant="subtle"
				:icon-left="LucideArrowDownLeft"
				label="Receive payment"
				@click="openMoney('receive')"
			/>
			<Button
				variant="subtle"
				:icon-left="LucideArrowUpRight"
				label="Make payment"
				@click="openMoney('pay-supplier')"
			/>
			<Button
				variant="subtle"
				:icon-left="LucideArrowLeftRight"
				label="Transfer funds"
				@click="openMoney('transfer')"
			/>
		</div>

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

		<MoneySheet v-model="moneyOpen" :mode="moneyMode" @done="load" @notify="notify" />

		<div
			v-if="toast"
			class="pos-toast pointer-events-none absolute bottom-5 left-1/2 -translate-x-1/2 rounded-lg px-4 py-2.5 text-p-sm font-medium text-ink-white shadow-lg"
			:class="toast.tone === 'bad' ? 'bg-surface-red-5' : 'bg-surface-green-3'"
		>
			{{ toast.message }}
		</div>
	</div>
</template>
