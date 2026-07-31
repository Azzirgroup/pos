<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Button, Badge, FormControl } from 'frappe-ui'
import { listNeighbourPurchases, getReturnablePurchase, returnToNeighbour } from '@/data/api'
import PageHeader from '@/components/PageHeader.vue'
import StatTiles from '@/components/StatTiles.vue'
import DataTable from '@/components/DataTable.vue'
import ShareSheet from '@/components/ShareSheet.vue'
import { useRowActions } from '@/composables/useRowActions'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideSend from '~icons/lucide/send'
import LucideUndo from '~icons/lucide/undo-2'
import BottomSheet from '@/components/BottomSheet.vue'
import { fmtMoney } from '@/utils/format'

/**
 * What the till has bought from the shops next door.
 *
 * These are created one at a time with a customer waiting, and until now nothing
 * showed them together. The shift's closing screen lists the ones from the shift
 * in front of you; this answers the standing question — who have we been buying
 * from, and what have we still not settled.
 *
 * Unpaid is the default filter, because that is the only part of this anybody
 * has to act on. The rest is history.
 */
const data = ref({ rows: [], totals: {}, suppliers: [], reason: null })
const days = ref(30)
const status = ref('unpaid')
const loading = ref(false)

const PERIODS = [
	{ label: 'Last 7 days', value: 7 },
	{ label: 'Last 30 days', value: 30 },
	{ label: 'Last 90 days', value: 90 },
	{ label: 'Last year', value: 365 },
]

const STATUSES = [
	{ label: 'Still owed', value: 'unpaid' },
	{ label: 'Settled', value: 'paid' },
	{ label: 'All', value: 'all' },
]

const COLUMNS = [
	{ label: 'Shop', key: 'supplier', type: 'text' },
	{ label: 'Bought', key: 'items', type: 'text' },
	{ label: 'Date', key: 'posting_date', type: 'text' },
	{ label: 'Invoice', key: 'name', type: 'text' },
	{ label: 'Status', key: 'status', type: 'text' },
	{ label: 'Total', key: 'grand_total', type: 'currency' },
	{ label: 'Still owed', key: 'outstanding', type: 'currency' },
]

const rows = computed(() => data.value.rows || [])

const stats = computed(() => {
	const t = data.value.totals || {}
	return [
		{ label: 'Purchases', value: t.count, type: 'number' },
		{ label: 'Shops used', value: t.shops, type: 'number' },
		{ label: 'Spent', value: t.spend, type: 'currency' },
		{
			label: 'Still owed',
			value: t.owed,
			type: 'currency',
			tone: t.owed > 0 ? 'warn' : 'good',
		},
	]
})

/**
 * A neighbour purchase is a real Purchase Invoice, so sharing one sends the
 * invoice — which is what settling up with the shop next door needs.
 */
const { shareOpen, sharePayload, shareList, actionsFor } = useRowActions({
	columns: COLUMNS,
	title: (row) => `${row.supplier} · ${row.name}`,
	documentFor: (row) => ({ doctype: 'Purchase Invoice', name: row.name }),
	extra: (row) => [{ label: 'Send stock back', icon: LucideUndo, onClick: () => openReturn(row) }],
})

/* ---------- sending stock back ---------- */

/**
 * Trade next door runs both ways.
 *
 * A purchase made to complete a sale that then fell through has to go back, and
 * the payable with it. Started from the purchase rather than from a blank form
 * for the same reason a customer return is: it is the only way to know what may
 * be sent back, and how much of it is left.
 */
const returnOpen = ref(false)
const returning = ref(null)
const returnQty = ref({})
const returnBusy = ref(false)
const returnError = ref(null)

async function openReturn(row) {
	returnOpen.value = true
	returning.value = null
	returnQty.value = {}
	returnError.value = null
	try {
		returning.value = await getReturnablePurchase({ invoice: row.name })
	} catch (e) {
		returnError.value = e.message || 'Could not load that purchase'
	}
}

const returnLines = computed(() => returning.value?.items || [])

const returnTotal = computed(() =>
	returnLines.value.reduce(
		(sum, l) => sum + (Number(returnQty.value[l.item_code]) || 0) * l.rate,
		0,
	),
)

function setReturnQty(line, value) {
	const n = Math.max(0, Math.min(line.qty, Number(value) || 0))
	returnQty.value = { ...returnQty.value, [line.item_code]: n }
}

async function submitReturn() {
	if (returnTotal.value <= 0) return
	returnBusy.value = true
	returnError.value = null
	try {
		const res = await returnToNeighbour({
			invoice: returning.value.name,
			lines: returnLines.value
				.filter((l) => (Number(returnQty.value[l.item_code]) || 0) > 0)
				.map((l) => ({ item_code: l.item_code, qty: Number(returnQty.value[l.item_code]) })),
		})
		returnOpen.value = false
		notify(`${fmtMoney(res.total)} sent back to ${res.supplier} · ${res.name}`, 'good')
		load()
	} catch (e) {
		returnError.value = e.message || 'Could not send it back'
	} finally {
		returnBusy.value = false
	}
}

const toast = ref(null)
let toastTimer = null
function notify(message, tone = 'good') {
	toast.value = { message, tone }
	clearTimeout(toastTimer)
	toastTimer = setTimeout(() => (toast.value = null), 2600)
}

onMounted(load)
watch([days, status], load)

async function load() {
	loading.value = true
	try {
		data.value = await listNeighbourPurchases({
			days: days.value,
			status: status.value === 'all' ? null : status.value,
		})
	} catch (e) {
		console.error('[neighbours]', e)
		data.value = { rows: [], totals: {}, suppliers: [], reason: e.message }
	} finally {
		loading.value = false
	}
}
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col overflow-hidden">
		<PageHeader
			title="Neighbour purchases"
			subtitle="Stock bought from the shops next door to complete a sale"
		>
			<template #actions>
				<div class="w-[150px]">
					<FormControl type="select" v-model="status" :options="STATUSES" />
				</div>
				<div class="w-[160px]">
					<FormControl type="select" v-model="days" :options="PERIODS" />
				</div>
				<Button
					variant="subtle"
					:icon-left="LucideSend"
					:disabled="!rows.length"
					label="Share list"
					@click="shareList(rows, 'Owed to neighbouring shops')"
				/>
				<Button variant="subtle" :icon-left="LucideRefreshCw" :loading="loading" @click="load" />
			</template>
		</PageHeader>

		<!-- "Nothing bought yet" and "this was never set up" look identical on
		     screen and need different actions, so the server says which it is. -->
		<p
			v-if="data.reason"
			class="shrink-0 bg-surface-amber-1 px-4 py-2 text-p-sm text-ink-amber-3"
		>
			{{ data.reason }} Add the shops you buy from as Suppliers in the neighbour group.
		</p>

		<StatTiles :stats="stats" />

		<DataTable
			:columns="COLUMNS"
			:rows="rows"
			row-key="name"
			:loading="loading"
			:actions="actionsFor"
			empty-text="Nothing bought from a neighbour in this period."
		>
			<template #cell-status="{ row }">
				<Badge
					:theme="row.outstanding > 0 ? 'orange' : 'green'"
					variant="subtle"
					:label="row.outstanding > 0 ? 'Owed' : 'Settled'"
				/>
			</template>
		</DataTable>

		<ShareSheet v-model="shareOpen" :payload="sharePayload" />

		<!-- Sending stock back next door. Quantities start at zero for the same
		     reason as a customer return: most of these are one line, and a
		     pre-filled basket is one a hurried tap sends back whole. -->
		<BottomSheet v-model="returnOpen" title="Send stock back" tall>
			<div class="flex flex-col gap-3 px-4 pb-5 pt-1">
				<p v-if="returnError" class="rounded-lg bg-surface-red-2 px-3 py-2 text-p-sm text-ink-red-3">
					{{ returnError }}
				</p>

				<p v-if="!returning && !returnError" class="text-p-sm text-ink-gray-5">Loading…</p>

				<template v-else-if="returning">
					<div>
						<div class="text-p-lg font-semibold text-ink-gray-9">{{ returning.supplier }}</div>
						<div class="text-p-sm text-ink-gray-5">
							{{ returning.name }} · {{ returning.posting_date }} ·
							{{ fmtMoney(returning.grand_total) }}
						</div>
					</div>

					<p v-if="!returnLines.length" class="rounded-lg bg-surface-gray-2 px-3 py-2 text-p-sm text-ink-gray-6">
						Everything on this purchase has already gone back.
					</p>

					<div
						v-for="line in returnLines"
						:key="line.item_code"
						class="rounded-xl border border-outline-gray-2 p-3"
					>
						<div class="flex items-baseline justify-between gap-2">
							<span class="min-w-0 truncate text-p-base font-medium text-ink-gray-9">
								{{ line.item_name }}
							</span>
							<span class="tabular shrink-0 text-p-sm text-ink-gray-5">
								{{ fmtMoney(line.rate) }}
							</span>
						</div>
						<div class="mt-0.5 text-p-xs text-ink-gray-5">{{ line.qty }} can go back</div>
						<div class="mt-2 flex items-center gap-2">
							<input
								:value="returnQty[line.item_code] ?? 0"
								type="number"
								min="0"
								:max="line.qty"
								inputmode="numeric"
								class="tabular h-11 w-24 rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-lg font-semibold text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
								@input="setReturnQty(line, $event.target.value)"
								@focus="$event.target.select()"
							/>
							<button
								class="min-h-touch rounded-lg border border-outline-gray-2 px-3 text-p-sm font-medium text-ink-gray-7 hover:bg-surface-gray-2"
								@click="setReturnQty(line, line.qty)"
							>
								All {{ line.qty }}
							</button>
							<span class="tabular ml-auto text-p-base font-semibold text-ink-gray-9">
								{{ fmtMoney((Number(returnQty[line.item_code]) || 0) * line.rate) }}
							</span>
						</div>
					</div>

					<div
						v-if="returnLines.length"
						class="flex items-center justify-between rounded-xl px-4 py-3"
						:class="returnTotal > 0 ? 'bg-surface-amber-2' : 'bg-surface-gray-2'"
					>
						<span
							class="text-p-base font-medium"
							:class="returnTotal > 0 ? 'text-ink-amber-3' : 'text-ink-gray-6'"
						>
							Comes off what you owe
						</span>
						<span
							class="tabular text-2xl font-semibold"
							:class="returnTotal > 0 ? 'text-ink-amber-3' : 'text-ink-gray-7'"
						>
							{{ fmtMoney(returnTotal) }}
						</span>
					</div>

					<button
						v-if="returnLines.length"
						class="min-h-touch w-full rounded-xl bg-surface-gray-7 py-3.5 text-p-lg font-semibold text-ink-white transition-all active:scale-[0.98] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
						:disabled="returnTotal <= 0 || returnBusy"
						@click="submitReturn"
					>
						{{ returnBusy ? 'Sending back…' : `Send back ${fmtMoney(returnTotal)}` }}
					</button>
				</template>
			</div>
		</BottomSheet>

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
	</div>
</template>
