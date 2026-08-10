<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Button, FormControl } from 'frappe-ui'
import { listReturns, getRecentSales } from '@/data/api'
import { fmtMoney } from '@/utils/format'
import PageHeader from '@/components/PageHeader.vue'
import StatTiles from '@/components/StatTiles.vue'
import DataTable from '@/components/DataTable.vue'
import ShareSheet from '@/components/ShareSheet.vue'
import ReturnSheet from '@/components/ReturnSheet.vue'
import BottomSheet from '@/components/BottomSheet.vue'
import DocumentModal from '@/components/DocumentModal.vue'
import { useRowActions } from '@/composables/useRowActions'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideSend from '~icons/lucide/send'
import LucideUndo from '~icons/lucide/undo-2'

/**
 * Goods coming back, and the way in to sending them back.
 *
 * The mechanism has existed since returns were built — `ReturnSheet` posts a
 * credit note and adjusts the drawer — but the only door to it was the Recent
 * sales list at the till, which is scoped to the open shift. A customer walking
 * in on Thursday with Monday's receipt had nowhere to be served from, and
 * nothing in the app listed what had already been taken back.
 *
 * So: the history, and a way to start one from any sale rather than only from
 * today's. Started from a sale either way — a free-form return would let
 * somebody be refunded for goods they never bought.
 */
const data = ref({ rows: [], total: 0, count: 0 })
const days = ref(30)
const loading = ref(false)

const PERIODS = [
	{ label: 'Last 7 days', value: 7 },
	{ label: 'Last 30 days', value: 30 },
	{ label: 'Last 90 days', value: 90 },
	{ label: 'Last year', value: 365 },
]

const COLUMNS = [
	{ label: 'Credit note', key: 'name', type: 'text' },
	{ label: 'Against', key: 'against', type: 'text' },
	{ label: 'Customer', key: 'customer', type: 'text' },
	{ label: 'Date', key: 'date', type: 'text' },
	{ label: 'Refunded as', key: 'refund', type: 'text' },
	{ label: 'By', key: 'by', type: 'text' },
	{ label: 'Value', key: 'value', type: 'currency' },
]

const rows = computed(() => data.value.rows || [])

const stats = computed(() => [
	{ label: 'Returns', value: data.value.count, type: 'number', icon: 'ban' },
	{ label: 'Given back', value: data.value.total, type: 'currency', icon: 'money' },
	{
		label: 'Cash refunds',
		value: rows.value.filter((r) => r.refund === 'Cash').length,
		type: 'number',
		icon: 'wallet',
	},
	{
		label: 'On account',
		value: rows.value.filter((r) => r.refund !== 'Cash').length,
		type: 'number',
		icon: 'users',
	},
])

/** A credit note is a real document, so sharing one sends the document. */
const { shareOpen, sharePayload, shareList, actionsFor } = useRowActions({
	columns: COLUMNS,
	title: (row) => `${row.name} · ${row.customer || 'Walk-in'}`,
	documentFor: (row) => ({ doctype: 'Sales Invoice', name: row.name }),
})

/* ---------- starting a return ---------- */

/**
 * Which sale is coming back.
 *
 * A picker rather than a text box for the invoice number: a customer hands over
 * a receipt, and a cashier reading a number off it and typing it into a field
 * that then says "not found" has no way to tell a typo from a sale made at
 * another till. The recent list is searchable and shows the customer and the
 * amount, which is what the receipt in their hand also shows.
 */
const pickOpen = ref(false)
const pickLoading = ref(false)
const candidates = ref([])
const search = ref('')
const returnInvoice = ref('')
const returnOpen = ref(false)

async function openPicker() {
	pickOpen.value = true
	pickLoading.value = true
	try {
		// Every sale, not this shift's: the whole point of this screen is the
		// customer who comes back on a different day.
		const res = await getRecentSales({ limit: 100, mine: false, thisShift: false })
		candidates.value = (res.rows || []).filter((r) => !r.is_return)
	} catch (e) {
		candidates.value = []
		notify(e.message || 'Could not load sales', 'bad')
	} finally {
		pickLoading.value = false
	}
}

const matches = computed(() => {
	const q = search.value.trim().toLowerCase()
	if (!q) return candidates.value
	return candidates.value.filter(
		(r) =>
			String(r.name).toLowerCase().includes(q) ||
			String(r.customer || '').toLowerCase().includes(q),
	)
})

function startReturn(row) {
	returnInvoice.value = row.name
	pickOpen.value = false
	returnOpen.value = true
}

function onReturned(res) {
	notify(`${fmtMoney(res.refunded)} refunded · ${res.name}`, 'good')
	load()
}

const toast = ref(null)
let toastTimer = null
function notify(message, tone = 'good') {
	toast.value = { message, tone }
	clearTimeout(toastTimer)
	toastTimer = setTimeout(() => (toast.value = null), 2800)
}

onMounted(load)
watch(days, load)

async function load() {
	loading.value = true
	try {
		data.value = await listReturns({ days: days.value, limit: 200 })
	} catch (e) {
		data.value = { rows: [], total: 0, count: 0 }
		notify(e.message || 'Could not load returns', 'bad')
	} finally {
		loading.value = false
	}
}
/**
 * Open the document behind a row.
 *
 * The first column is a link now, and it goes to the same modal the documents
 * hub uses — one detail view for a Sales Invoice wherever it is listed, rather
 * than a second one per screen that drifts from it.
 */
const docKey = ref(null)
const docName = ref(null)
const docOpen = ref(false)

function openDoc(key, name) {
	if (!name) return
	docKey.value = key
	docName.value = name
	docOpen.value = true
}
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col overflow-hidden">
		<PageHeader title="Returns" subtitle="Goods that came back, and what was given for them">
			<template #primary>
				<Button
					theme="gray"
					variant="solid"
					:icon-left="LucideUndo"
					label="Take goods back"
					@click="openPicker"
				/>
			</template>
			<template #actions>
				<div class="w-[160px]">
					<FormControl type="select" v-model="days" :options="PERIODS" />
				</div>
				<Button
					variant="subtle"
					:icon-left="LucideSend"
					:disabled="!rows.length"
					label="Share list"
					@click="shareList(rows, 'Returns')"
				/>
				<Button variant="subtle" :icon-left="LucideRefreshCw" :loading="loading" @click="load" />
			</template>
		</PageHeader>

		<StatTiles :stats="stats" />

		<DataTable
			row-link
			@row-click="(r) => openDoc('sales-invoice', r.name)"
			:columns="COLUMNS"
			:rows="rows"
			row-key="name"
			:loading="loading"
			:actions="actionsFor"
			empty-text="Nothing has been returned in this period."
		/>

		<ShareSheet v-model="shareOpen" :payload="sharePayload" />

		<!-- Pick the sale first. Everything about what may come back, and how much
		     of it is left, is derived from the original — see `ReturnSheet`. -->
		<BottomSheet v-model="pickOpen" title="Which sale is coming back?" tall>
			<div class="flex flex-col gap-2 px-4 pb-5">
				<input
					v-model="search"
					type="text"
					placeholder="Invoice number or customer…"
					class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
				/>

				<p v-if="pickLoading" class="px-1 text-p-sm text-ink-gray-5">Loading sales…</p>
				<p v-else-if="!matches.length" class="px-1 text-p-sm text-ink-gray-5">
					No sales match that.
				</p>

				<button
					v-for="row in matches"
					:key="row.name"
					class="flex items-center gap-3 rounded-xl border border-outline-gray-2 px-3 py-2.5 text-left transition-colors hover:bg-surface-gray-2"
					@click="startReturn(row)"
				>
					<div class="min-w-0 flex-1">
						<div class="truncate text-p-base font-medium text-ink-gray-9">
							{{ row.customer || 'Walk-in Customer' }}
						</div>
						<div class="truncate text-p-xs text-ink-gray-5">
							{{ row.name }} · {{ row.posting_date }}
						</div>
					</div>
					<span class="tabular shrink-0 text-p-base font-semibold text-ink-gray-9">
						{{ fmtMoney(row.grand_total) }}
					</span>
				</button>
			</div>
		</BottomSheet>

		<ReturnSheet v-model="returnOpen" :invoice="returnInvoice" @returned="onReturned" />

		<Transition
			enter-active-class="transition-all duration-200"
			leave-active-class="transition-all duration-200"
			enter-from-class="opacity-0 translate-y-2"
			leave-to-class="opacity-0"
		>
			<div
				v-if="toast"
				class="pos-toast pointer-events-none absolute bottom-5 left-1/2 -translate-x-1/2 rounded-lg px-4 py-2.5 text-p-sm font-medium text-ink-white shadow-lg"
				:class="toast.tone === 'bad' ? 'bg-surface-red-5' : 'bg-surface-green-3'"
			>
				{{ toast.message }}
			</div>
		</Transition>
		<DocumentModal v-model:open="docOpen" :doc-key="docKey" :name="docName" />
	</div>
</template>
