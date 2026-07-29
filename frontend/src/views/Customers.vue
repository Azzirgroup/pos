<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Button, FormControl } from 'frappe-ui'
import { searchCustomers } from '@/data/api'
import PageHeader from '@/components/PageHeader.vue'
import StatTiles from '@/components/StatTiles.vue'
import DataTable from '@/components/DataTable.vue'
import CustomerLedger from '@/components/CustomerLedger.vue'
import ShareSheet from '@/components/ShareSheet.vue'
import { useRowActions } from '@/composables/useRowActions'
import { fmtMoney } from '@/utils/format'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideSend from '~icons/lucide/send'

const rows = ref([])
const search = ref('')
const loading = ref(false)

/* ---------- account ledger ---------- */

const ledgerOpen = ref(false)
const ledgerFor = ref(null)

function openLedger(customer) {
	ledgerFor.value = customer
	ledgerOpen.value = true
}

const COLUMNS = [
	{ label: 'Customer', key: 'customer_name', type: 'text' },
	{ label: 'Phone', key: 'mobile_no', type: 'text' },
	{ label: 'Owes', key: 'outstanding', type: 'currency' },
]

/**
 * A customer is not a document, so this shares text.
 *
 * The one extra action worth having here is sending the reminder to the number
 * already in the row — chasing a balance is the reason anyone opens this screen,
 * and re-typing a phone number that is on screen is the step that stops them.
 */
const { shareOpen, sharePayload, shareRow, shareList, actionsFor } = useRowActions({
	columns: COLUMNS,
	title: (row) => row.customer_name || row.name,
	extra: (row) =>
		Number(row.outstanding) > 0
			? [
					{
						label: 'Send a reminder',
						icon: LucideSend,
						onClick: () => remind(row),
					},
				]
			: [],
})

function remind(row) {
	// Addressed to the customer rather than describing them: this one goes *to*
	// the person in the row, not to a colleague about them.
	shareRow(row, {
		title: `Remind ${row.customer_name || row.name}`,
		message:
			`Hello ${row.customer_name || row.name},\n\n` +
			`Our records show a balance of ${fmtMoney(row.outstanding)} on your account.\n` +
			`Please get in touch if this does not look right.`,
	})
}

const stats = computed(() => {
	const owing = rows.value.filter((r) => Number(r.outstanding) > 0)
	return [
		{ label: 'Customers', value: rows.value.length, type: 'number' },
		{
			label: 'Owing money',
			value: owing.length,
			type: 'number',
			tone: owing.length ? 'warn' : 'good',
		},
		{
			label: 'Total owed',
			value: owing.reduce((s, r) => s + Number(r.outstanding || 0), 0),
			type: 'currency',
			tone: owing.length ? 'warn' : 'good',
		},
	]
})

onMounted(load)

let timer = null
watch(search, () => {
	clearTimeout(timer)
	timer = setTimeout(load, 250)
})

async function load() {
	loading.value = true
	try {
		rows.value = (await searchCustomers(search.value)) || []
	} catch (e) {
		console.error('[customers]', e)
		rows.value = []
	} finally {
		loading.value = false
	}
}
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col overflow-hidden">
		<PageHeader title="Customers" subtitle="Who buys, and who still owes">
			<template #actions>
				<div class="w-[220px]">
					<FormControl v-model="search" type="text" placeholder="Search name or phone…" />
				</div>
				<Button
					variant="subtle"
					:icon-left="LucideSend"
					:disabled="!rows.length"
					label="Share list"
					@click="shareList(rows, 'Customer balances')"
				/>
				<Button variant="subtle" :icon-left="LucideRefreshCw" :loading="loading" @click="load" />
			</template>
		</PageHeader>

		<StatTiles :stats="stats" />
		<DataTable
			:columns="COLUMNS"
			:rows="rows"
			row-key="name"
			:loading="loading"
			:actions="actionsFor"
			empty-text="No customers yet. They are created at the till on a credit sale."
		>
			<!-- The name is the way in: "who is this and what do they owe" is one
			     question, so clicking the answer opens the account behind it. -->
			<template #cell-customer_name="{ row }">
				<button
					class="text-left font-medium text-ink-gray-8 underline decoration-outline-gray-3 underline-offset-2 hover:decoration-ink-gray-8"
					@click="openLedger(row.name)"
				>
					{{ row.customer_name }}
				</button>
			</template>
			<template #cell-outstanding="{ row, value }">
				<button
					class="tabular underline decoration-outline-gray-3 underline-offset-2 hover:decoration-ink-gray-8"
					:class="value > 0 ? 'font-medium text-ink-red-3' : 'text-ink-gray-8'"
					@click="openLedger(row.name)"
				>
					{{ fmtMoney(value || 0) }}
				</button>
			</template>
		</DataTable>

		<CustomerLedger v-model:open="ledgerOpen" :customer="ledgerFor" />
		<ShareSheet v-model="shareOpen" :payload="sharePayload" />
	</div>
</template>
