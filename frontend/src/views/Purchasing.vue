<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Button, Dialog } from 'frappe-ui'
import { fmtMoney, fmtQty } from '@/utils/format'
import {
	getDayPurchases,
	getPurchase,
	createPurchase,
	updatePurchase,
	confirmPurchase,
	reopenPurchase,
	deletePurchase,
	searchPurchaseSuppliers,
	searchPurchaseItems,
	searchPurchaseWarehouses,
	getItemStock,
} from '@/data/api'
import { useSessionStore } from '@/stores/session'
import PageHeader from '@/components/PageHeader.vue'
import StatTiles from '@/components/StatTiles.vue'
import PillTabs from '@/components/PillTabs.vue'
import LinkField from '@/components/LinkField.vue'
import DateField from '@/components/DateField.vue'
import BottomSheet from '@/components/BottomSheet.vue'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucidePlus from '~icons/lucide/plus'
import LucideSearch from '~icons/lucide/search'
import LucideChevronLeft from '~icons/lucide/chevron-left'
import LucideChevronRight from '~icons/lucide/chevron-right'
import LucideCalendarDays from '~icons/lucide/calendar-days'
import LucideCheck from '~icons/lucide/check'
import LucideEye from '~icons/lucide/eye'
import LucidePencil from '~icons/lucide/pencil'
import LucideTrash2 from '~icons/lucide/trash-2'
import LucideRotateCcw from '~icons/lucide/rotate-ccw'
import LucideX from '~icons/lucide/x'

/**
 * Buying stock in, in two hands.
 *
 * This screen used to be a read-only overview: three tabs of ERPNext documents
 * over a rolling thirty days, with no way to raise anything. Buying actually
 * happened through the generic document hub, which meant knowing that a
 * purchase *is* a Purchase Invoice and that submitting it is irreversible. The
 * shop said, plainly, that the process was too complex — so this is the process
 * they described instead:
 *
 * 1. The **manager posts the purchase**. It saves as a draft, correctable as
 *    many times as it takes. Nothing is received and nothing is owed yet.
 * 2. The **store keeper counter-checks it against what turned up**, adjusts the
 *    quantities, and confirms. Confirming is what submits it — the stock lands
 *    and the payable is booked by the person who saw the cartons.
 *
 * The rules live on the server (`cosmestics.api.buying`); this only draws the
 * buttons the session may actually press.
 *
 * The day is the view, for the same reason it is on Deliveries: "what came in
 * this morning" was buried under a month of history.
 */

const STAGE_TABS = [
	{ label: 'All', value: '' },
	{ label: 'To confirm', value: 'pending' },
	{ label: 'Confirmed', value: 'confirmed' },
]

const session = useSessionStore()

/** See `Deliveries.localDay` — UTC would flip the day mid-afternoon in Nairobi. */
function localDay(date = new Date()) {
	const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
	return shifted.toISOString().slice(0, 10)
}

function addDays(iso, delta) {
	const d = new Date(`${iso}T12:00:00`)
	d.setDate(d.getDate() + delta)
	return localDay(d)
}

const data = ref(null)
const loading = ref(false)
const search = ref('')
const stage = ref('')
const today = ref(localDay())
const onDate = ref(localDay())

const dayLabel = computed(() => {
	if (onDate.value === today.value) return 'Today'
	if (onDate.value === addDays(today.value, -1)) return 'Yesterday'
	return new Date(`${onDate.value}T12:00:00`).toLocaleDateString(undefined, {
		weekday: 'short',
		day: 'numeric',
		month: 'short',
	})
})

const can = computed(() => data.value?.can || {})

const rows = computed(() => {
	const all = data.value?.rows || []
	if (stage.value === 'pending') return all.filter((r) => r.docstatus === 0)
	if (stage.value === 'confirmed') return all.filter((r) => r.docstatus === 1)
	return all
})

const stats = computed(() => {
	const t = data.value?.totals || {}
	return [
		{ label: 'Purchases today', value: t.count || 0, type: 'number', icon: 'truck' },
		{ label: 'Purchase cost', value: t.cost || 0, type: 'currency', icon: 'money' },
		{
			label: 'Owed to suppliers',
			value: t.owed || 0,
			type: 'currency',
			icon: 'wallet',
			tone: t.owed > 0 ? 'warn' : 'good',
			// Said out loud, because every other tile on this row is about the day
			// and this one is not — what a shop owes does not reset at midnight.
			hint: 'All unpaid purchases',
		},
		{
			label: 'Pending confirmation',
			value: t.pending || 0,
			type: 'number',
			icon: 'hourglass',
			tone: t.pending ? 'warn' : 'default',
		},
		{ label: 'Confirmed', value: t.confirmed || 0, type: 'number', icon: 'clipboard' },
	]
})

onMounted(() => {
	session.load()
	load()
})

let timer = null
watch(onDate, load)
watch(search, () => {
	clearTimeout(timer)
	timer = setTimeout(load, 300)
})

async function load() {
	// A till is left open all day, and sometimes overnight. Without this the
	// "Today" label and the button that jumps back to it keep pointing at
	// yesterday until somebody reloads.
	today.value = localDay()
	loading.value = true
	try {
		data.value = await getDayPurchases({ onDate: onDate.value, search: search.value || null })
	} catch (e) {
		notify(e.message || 'Could not load the purchases', 'bad')
		data.value = null
	} finally {
		loading.value = false
	}
}

function stepDay(delta) {
	onDate.value = addDays(onDate.value, delta)
}

/* ---------- the form, shared by posting and correcting ---------- */

/**
 * One sheet for three jobs — post, correct, counter-check — because they are
 * the same document seen by different people. What changes between them is what
 * is editable and what the button at the foot says, and both come from `mode`.
 *
 * `count` is the store keeper's view: the lines are fixed and only the
 * quantities move. That is the arrangement the shop described — the store says
 * what turned up, not what it should have cost — and the server enforces it
 * regardless of what this sheet renders.
 */
const formOpen = ref(false)
const mode = ref('post') // 'post' | 'edit' | 'count'
const saving = ref(false)
const draft = ref(blank())
const editingName = ref(null)

function blank() {
	return {
		supplier: '',
		supplierLabel: '',
		postingDate: localDay(),
		billNo: '',
		remarks: '',
		// Where the goods came from and where they land. Only the destination
		// matters to ERPNext; the source is for stock moved in from another
		// branch, and is blank for the ordinary supplier purchase.
		fromWarehouse: '',
		toWarehouse: '',
		items: [],
	}
}

const readOnlyLines = computed(() => mode.value === 'count')

const formTitle = computed(
	() =>
		({
			post: 'New purchase',
			edit: `Edit ${editingName.value || 'purchase'}`,
			count: `Confirm ${editingName.value || 'purchase'}`,
		})[mode.value],
)

const total = computed(() =>
	filledLines.value.reduce((sum, line) => sum + Number(line.qty || 0) * Number(line.rate || 0), 0),
)

const blocker = computed(() => {
	const d = draft.value
	if (mode.value !== 'count' && !d.supplier) return 'Choose the supplier'
	if (!filledLines.value.length) return 'Add at least one item'
	if (!filledLines.value.some((l) => Number(l.qty) > 0)) return 'Nothing has a quantity'
	return null
})

function openNew() {
	mode.value = 'post'
	editingName.value = null
	draft.value = blank()
	draft.value.postingDate = onDate.value
	// One empty line waiting, so the first thing on screen is somewhere to type
	// rather than a button that produces somewhere to type.
	draft.value.items = [blankLine()]
	formOpen.value = true
}

async function openFor(row, next) {
	try {
		const doc = await getPurchase({ name: row.name })
		mode.value = next
		editingName.value = doc.name
		draft.value = {
			supplier: doc.supplier,
			supplierLabel: doc.supplier_name,
			postingDate: doc.posting_date,
			billNo: doc.bill_no || '',
			remarks: doc.remarks || '',
			fromWarehouse: doc.from_warehouse || '',
			toWarehouse: doc.warehouse || '',
			items: doc.items.map((l) => ({ ...l, _id: ++nextLineId })),
		}
		formOpen.value = true
	} catch (e) {
		notify(e.message || 'Could not open that purchase', 'bad')
	}
}

const supplierFetcher = (term) => searchPurchaseSuppliers(term)
const itemFetcher = (term) => searchPurchaseItems(term)
const warehouseFetcher = (term) => searchPurchaseWarehouses(term)

/**
 * Lines are added blank and filled in, one at a time.
 *
 * This used to be a search box above the list: pick a product there and a
 * finished row appeared below, with the item fixed and unchangeable. It worked,
 * but it is not how the item-request form behaves, and these two are filled in
 * by the same people on the same day — in one, the item lives on the line and
 * you press "Add line" to get another; in the other it lived somewhere else
 * entirely and the line had no item field at all. Picking the wrong product
 * meant deleting the row and starting it again.
 *
 * So: a line carries its own item field, and "Add line" gives you an empty one.
 * A blank line costs nothing — `_clean_lines` on the server drops any row with
 * no item code, and `filledLines` below keeps them out of the total.
 */

/** Client-side row identity, so `v-for` keys survive a splice from the middle.
 *  Keying on `item_code` cannot work now that a new line has none yet, and
 *  keying on the index makes Vue reuse the wrong input when a row is removed. */
let nextLineId = 0

function blankLine() {
	return { _id: ++nextLineId, item_code: '', item_name: '', uom: '', qty: 1, rate: 0 }
}

function addLine() {
	draft.value.items.push(blankLine())
}

/**
 * Fill the rest of the line from the product that was chosen.
 *
 * Duplicates are refused rather than merged. ERPNext would accept two rows of
 * the same item, but the store keeper's count is applied by item code
 * (`_apply_counted_quantities`), so two rows of one product would both take the
 * counted quantity and the purchase would silently double. Saying so is better
 * than a total that is quietly wrong.
 */
function onItemPicked(line, option) {
	if (!option) return
	const code = option.item_code || option.value

	if (draft.value.items.some((l) => l !== line && l.item_code === code)) {
		notify(`${option.item_name || code} is already on this purchase — change its quantity instead`, 'bad')
		line.item_code = ''
		return
	}

	line.item_code = code
	line.item_name = option.item_name || option.label || code
	line.uom = option.uom || ''
	// Only as a starting point, and only into a blank: the last price paid is a
	// good guess and never the answer, and a rate already typed is what the
	// supplier actually charged this time.
	if (!Number(line.rate)) line.rate = Number(option.rate || 0)
}

/** Rows that name a product. The rest are lines somebody has not filled in yet. */
const filledLines = computed(() => draft.value.items.filter((l) => l.item_code))

function removeLine(index) {
	draft.value.items.splice(index, 1)
}

/* ---------- what the shelf already holds ---------- */

/**
 * The stock balance beside each line, exactly as the item-request form shows
 * it.
 *
 * The same question is being asked in both places from opposite ends: a request
 * argues that something is needed, a purchase says it has been bought, and
 * whoever is filling either one cannot see the shelf. On this form it answers
 * "have we over-ordered?" before the money is committed, and it gives the store
 * keeper counting cartons a figure to check the delivery against.
 *
 * Against the receiving warehouse where one is named, so the number means the
 * shelf these goods are actually landing on.
 */
const stock = ref({})
const stockLoading = ref(false)

let stockTimer = null
watch(
	() => [
		formOpen.value ? 1 : 0,
		draft.value.items.map((l) => l.item_code).join('|'),
		draft.value.toWarehouse,
	],
	([open, codes]) => {
		clearTimeout(stockTimer)
		if (!open || !codes) {
			stock.value = {}
			return
		}
		// Debounced: adding several lines in a row fires this on each one, and
		// only the settled list is worth asking about.
		stockTimer = setTimeout(loadStock, 300)
	},
)

async function loadStock() {
	const codes = [...new Set(draft.value.items.map((l) => l.item_code).filter(Boolean))]
	if (!codes.length) {
		stock.value = {}
		return
	}
	stockLoading.value = true
	try {
		stock.value = await getItemStock({
			itemCodes: codes,
			warehouse: draft.value.toWarehouse || null,
		})
	} catch (e) {
		// Silent. A balance is context; losing it must not read as the form
		// itself having failed, and the purchase posts perfectly well without it.
		console.warn('[purchasing] stock lookup failed', e)
		stock.value = {}
	} finally {
		stockLoading.value = false
	}
}

/** The figure for one line, and where it is a figure *for*. */
function stockFor(line) {
	const row = line.item_code ? stock.value[line.item_code] : null
	if (!row) return null
	const named = draft.value.toWarehouse && row.here !== null && row.here !== undefined
	return {
		available: named ? row.here : row.total,
		named,
		uom: row.uom,
	}
}

function stockLabel(line) {
	const s = stockFor(line)
	if (!s) return ''
	const unit = s.uom ? ` ${s.uom}` : ''
	return `${fmtQty(s.available)}${unit} ${s.named ? 'there' : 'in stock'}`
}

function stockTone(line) {
	const s = stockFor(line)
	if (!s) return ''
	// Quieter than the request form's, and deliberately so: on a purchase a low
	// balance is the *reason* for the document, not a warning about it. Only
	// "none at all" is worth a colour.
	return s.available <= 0
		? 'bg-surface-amber-2 text-ink-amber-3'
		: 'bg-surface-gray-3 text-ink-gray-7'
}

async function save() {
	if (blocker.value) return
	saving.value = true
	try {
		const payload = filledLines.value.map((l) => ({
			item_code: l.item_code,
			qty: Number(l.qty || 0),
			rate: Number(l.rate || 0),
		}))

		let res
		if (mode.value === 'post') {
			res = await createPurchase({
				supplier: draft.value.supplier,
				items: payload,
				postingDate: draft.value.postingDate,
				billNo: draft.value.billNo,
				remarks: draft.value.remarks,
				fromWarehouse: draft.value.fromWarehouse,
				toWarehouse: draft.value.toWarehouse,
			})
		} else if (mode.value === 'edit') {
			res = await updatePurchase({
				name: editingName.value,
				values: {
					supplier: draft.value.supplier,
					posting_date: draft.value.postingDate,
					bill_no: draft.value.billNo,
					remarks: draft.value.remarks,
					set_from_warehouse: draft.value.fromWarehouse || null,
					set_warehouse: draft.value.toWarehouse || null,
					items: payload,
				},
			})
		} else {
			res = await confirmPurchase({ name: editingName.value, items: payload })
		}

		formOpen.value = false
		await load()
		notify(res.message, 'good')
	} catch (e) {
		notify(e.message || 'Could not save that purchase', 'bad')
	} finally {
		saving.value = false
	}
}

/* ---------- reading one back, and undoing ---------- */

const detail = ref(null)
const detailOpen = ref(false)

async function openRow(row) {
	try {
		detail.value = await getPurchase({ name: row.name })
		detailOpen.value = true
	} catch (e) {
		notify(e.message || 'Could not open that purchase', 'bad')
	}
}

const busy = ref('')

/**
 * Pull today's confirmed purchase back for correction.
 *
 * The shop asked to be able to fix what was received "for that day". ERPNext
 * will not edit a submitted document, so the server cancels it and hands back
 * an amended draft — the original stays in the ledger cancelled, which is the
 * honest record. The name changes, which is why the toast says the new one.
 */
async function reopen(row) {
	busy.value = row.name
	try {
		const res = await reopenPurchase({ name: row.name })
		detailOpen.value = false
		await load()
		notify(res.message, 'good')
		openFor({ name: res.name }, 'edit')
	} catch (e) {
		notify(e.message || 'Could not reopen that purchase', 'bad')
	} finally {
		busy.value = ''
	}
}

const removing = ref(null)
const removeBusy = ref(false)

async function confirmRemove() {
	if (!removing.value) return
	removeBusy.value = true
	try {
		const res = await deletePurchase({ name: removing.value.name })
		if (detail.value?.name === removing.value.name) detailOpen.value = false
		removing.value = null
		await load()
		notify(res.message, 'good')
	} catch (e) {
		notify(e.message || 'Could not delete that purchase', 'bad')
	} finally {
		removeBusy.value = false
	}
}

const toast = ref(null)
let toastTimer = null
function notify(message, tone = 'good') {
	toast.value = { message, tone }
	clearTimeout(toastTimer)
	toastTimer = setTimeout(() => (toast.value = null), 3600)
}
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col overflow-hidden">
		<PageHeader title="Purchasing" subtitle="What came in, and what still has to be checked">
			<template #actions>
				<Button
					v-if="can.post"
					variant="solid"
					theme="gray"
					:icon-left="LucidePlus"
					label="New purchase"
					@click="openNew"
				/>
				<Button variant="subtle" :icon-left="LucideRefreshCw" :loading="loading" @click="load" />
			</template>
		</PageHeader>

		<StatTiles :stats="stats" dense />

		<div class="flex shrink-0 flex-wrap items-center gap-2 border-b border-outline-gray-2 px-4 pb-3">
			<PillTabs v-model="stage" :buttons="STAGE_TABS" inset />

			<div class="relative ml-auto w-full sm:w-[240px]">
				<LucideSearch
					class="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-gray-4"
				/>
				<input
					v-model="search"
					type="text"
					placeholder="Supplier, invoice, bill no…"
					class="h-9 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 pl-8 pr-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
				/>
			</div>

			<!-- The day, as a pager. Same control as Deliveries, for the same
			     reason: the screen opens on today, and paging back a day at a time
			     is how somebody actually reads a purchase log. -->
			<div
				class="flex h-9 shrink-0 items-center rounded-lg border border-outline-gray-2 bg-surface-gray-2"
			>
				<button
					class="grid h-full w-8 place-items-center rounded-l-lg text-ink-gray-6 transition-colors hover:bg-surface-gray-3 hover:text-ink-gray-8"
					aria-label="Day before"
					@click="stepDay(-1)"
				>
					<LucideChevronLeft class="h-4 w-4" />
				</button>
				<label
					class="relative flex h-full cursor-pointer items-center gap-1.5 px-2 text-p-sm font-medium text-ink-gray-8"
					:title="onDate"
				>
					<LucideCalendarDays class="h-4 w-4 shrink-0 text-ink-gray-5" />
					<span class="whitespace-nowrap">{{ dayLabel }}</span>
					<input
						v-model="onDate"
						type="date"
						aria-label="Pick a day"
						class="absolute inset-0 h-full w-full cursor-pointer opacity-0"
					/>
				</label>
				<button
					class="grid h-full w-8 place-items-center text-ink-gray-6 transition-colors hover:bg-surface-gray-3 hover:text-ink-gray-8 disabled:opacity-30"
					aria-label="Day after"
					:disabled="onDate >= today"
					@click="stepDay(1)"
				>
					<LucideChevronRight class="h-4 w-4" />
				</button>
				<button
					v-if="onDate !== today"
					class="h-full border-l border-outline-gray-2 px-2.5 text-p-xs font-semibold text-ink-gray-7 transition-colors hover:bg-surface-gray-3"
					@click="onDate = today"
				>
					Today
				</button>
			</div>
		</div>

		<div class="min-h-0 flex-1 overflow-auto px-4 py-4">
			<p v-if="loading && !rows.length" class="py-10 text-center text-p-sm text-ink-gray-5">
				Loading…
			</p>
			<p v-else-if="!rows.length" class="py-10 text-center text-p-sm text-ink-gray-5">
				No purchases {{ dayLabel === 'Today' ? 'today' : `on ${dayLabel}` }}.
			</p>

			<div v-else class="flex flex-col gap-2">
				<div
					v-for="row in rows"
					:key="row.name"
					class="flex flex-col gap-2 rounded-xl border bg-surface-white p-3"
					:class="
						row.docstatus === 0 ? 'border-outline-amber-2' : 'border-outline-gray-2'
					"
				>
					<div
						class="-m-1 flex min-w-0 cursor-pointer flex-col gap-1 rounded-lg p-1 transition-colors hover:bg-surface-gray-1"
						role="button"
						tabindex="0"
						@click="openRow(row)"
						@keyup.enter="openRow(row)"
					>
						<div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
							<span class="max-w-full truncate text-p-base font-medium text-ink-gray-9">
								{{ row.supplier_name }}
							</span>
							<span
								class="shrink-0 rounded-full px-2 py-0.5 text-p-xs font-medium"
								:class="
									row.docstatus === 0
										? 'bg-surface-amber-2 text-ink-amber-3'
										: 'bg-surface-green-2 text-ink-green-3'
								"
							>
								{{ row.stage }}
							</span>
							<span
								v-if="row.neighbour"
								class="shrink-0 rounded-full bg-surface-blue-2 px-2 py-0.5 text-p-xs font-medium text-ink-blue-3"
							>
								Neighbour
							</span>
							<span class="tabular ml-auto shrink-0 text-p-base font-medium text-ink-gray-9">
								{{ fmtMoney(row.grand_total) }}
							</span>
						</div>
						<div class="truncate text-p-xs text-ink-gray-5">
							{{ row.name }}
							<template v-if="row.bill_no"> · bill {{ row.bill_no }}</template>
							· {{ row.item_count }} line{{ row.item_count === 1 ? '' : 's' }}
							<template v-if="row.outstanding > 0">
								· {{ fmtMoney(row.outstanding) }} owed
							</template>
						</div>
						<p v-if="row.items" class="truncate text-p-xs text-ink-gray-6">{{ row.items }}</p>
					</div>

					<div class="flex flex-wrap items-center gap-2 border-t border-outline-gray-1 pt-2">
						<!-- The one button this whole screen exists for. Only drawn for a
						     store keeper, and only while the purchase is still a draft. -->
						<button
							v-if="row.docstatus === 0 && can.confirm"
							class="flex items-center gap-1.5 rounded-md bg-surface-gray-7 px-2.5 py-1.5 text-p-xs font-semibold text-ink-white transition-colors hover:bg-surface-gray-6 disabled:opacity-50"
							:disabled="busy === row.name"
							@click="openFor(row, 'count')"
						>
							<LucideCheck class="h-3.5 w-3.5" />
							Check &amp; confirm
						</button>
						<!-- Said rather than left blank, so a store keeper who cannot post
						     and a manager who cannot confirm both know why. -->
						<span
							v-else-if="row.docstatus === 0"
							class="text-p-xs text-ink-gray-5"
						>
							Waiting for the store to confirm what arrived
						</span>

						<div class="ml-auto flex items-center gap-1.5">
							<button
								class="flex items-center gap-1.5 rounded-md border border-outline-gray-2 px-2.5 py-1.5 text-p-xs font-semibold text-ink-gray-7 transition-colors hover:bg-surface-gray-2"
								@click="openRow(row)"
							>
								<LucideEye class="h-3.5 w-3.5" />
								<span class="hidden sm:inline">View</span>
							</button>
							<button
								v-if="row.docstatus === 0 && can.post"
								class="flex items-center gap-1.5 rounded-md border border-outline-gray-2 px-2.5 py-1.5 text-p-xs font-semibold text-ink-gray-7 transition-colors hover:bg-surface-gray-2"
								@click="openFor(row, 'edit')"
							>
								<LucidePencil class="h-3.5 w-3.5" />
								<span class="hidden sm:inline">Edit</span>
							</button>
							<!-- Today's confirmed purchases only — see `buying._reopenable`
							     for the boundary and why it is where it is. -->
							<button
								v-if="row.docstatus === 1 && can.post && row.posting_date === today && row.outstanding >= row.grand_total"
								class="flex items-center gap-1.5 rounded-md border border-outline-gray-2 px-2.5 py-1.5 text-p-xs font-semibold text-ink-gray-7 transition-colors hover:bg-surface-gray-2 disabled:opacity-50"
								:disabled="busy === row.name"
								@click="reopen(row)"
							>
								<LucideRotateCcw class="h-3.5 w-3.5" />
								<span class="hidden sm:inline">Reopen</span>
							</button>
							<button
								v-if="row.docstatus === 0 && can.post"
								class="flex items-center gap-1.5 rounded-md border border-outline-gray-2 px-2.5 py-1.5 text-p-xs font-semibold text-ink-gray-7 transition-colors hover:border-outline-red-2 hover:bg-surface-red-1 hover:text-ink-red-3"
								@click="removing = row"
							>
								<LucideTrash2 class="h-3.5 w-3.5" />
								<span class="hidden sm:inline">Delete</span>
							</button>
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Post, correct, counter-check. One sheet — see the comment on `mode`. -->
		<BottomSheet v-model="formOpen" :title="formTitle" tall wide>
			<div class="flex flex-col gap-2.5 px-4 pb-5">
				<p
					v-if="mode === 'count'"
					class="rounded-lg bg-surface-amber-1 px-3 py-2 text-p-sm font-medium text-ink-amber-3"
				>
					Count what actually arrived and correct the quantities. Confirming receives the
					stock and books what is owed — it cannot be undone from here.
				</p>

				<div v-if="mode === 'count'" class="text-p-sm text-ink-gray-7">
					<span class="font-medium text-ink-gray-9">{{ draft.supplierLabel }}</span>
					<span v-if="draft.billNo" class="text-ink-gray-5"> · bill {{ draft.billNo }}</span>
				</div>
				<LinkField
					v-else
					v-model="draft.supplier"
					:fetcher="supplierFetcher"
					label="Supplier"
					required
				/>

				<div v-if="mode !== 'count'" class="grid gap-2 sm:grid-cols-2">
					<!-- The whole control opens the calendar, not just the glyph at
					     the end of it — see `DateField`. -->
					<DateField v-model="draft.postingDate" label="Date" />
					<div>
						<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">
							Supplier bill no.
						</label>
						<input
							v-model="draft.billNo"
							type="text"
							placeholder="Their reference"
							class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
						/>
					</div>
					<!-- Where the goods came from, and where they land. Only the
					     destination matters to the stock ledger, and it defaults to
					     the till's own warehouse — so a form that leaves both alone
					     behaves exactly as it did before these existed. From is for
					     stock moved in from another branch, and is blank for the
					     ordinary supplier purchase. -->
					<LinkField
						v-model="draft.fromWarehouse"
						:fetcher="warehouseFetcher"
						label="From warehouse"
					/>
					<LinkField
						v-model="draft.toWarehouse"
						:fetcher="warehouseFetcher"
						label="To warehouse"
					/>
				</div>

				<!-- The store keeper counts against a shelf, so it is named even on
				     the screen that cannot change it. -->
				<p v-else-if="draft.toWarehouse" class="text-p-xs text-ink-gray-5">
					Receiving into {{ draft.toWarehouse }}
					<template v-if="draft.fromWarehouse"> · from {{ draft.fromWarehouse }}</template>
				</p>

				<!-- One bordered card per line, fields labelled and laid out in a
				     row that wraps, with the stock balance underneath — the same
				     shape the item-request form uses. The two were a flat table and
				     a card list, and staff move between them all day: a line is a
				     line, and it should look like one in both places. -->
				<div class="flex flex-col gap-2">
					<p
						v-if="!draft.items.length"
						class="rounded-lg border border-outline-gray-2 px-3 py-6 text-center text-p-sm text-ink-gray-5"
					>
						Nothing on this purchase yet.
					</p>

					<div
						v-for="(line, i) in draft.items"
						:key="line._id"
						class="flex flex-col gap-1.5 rounded-lg border border-outline-gray-2 p-2.5"
					>
						<div class="flex flex-wrap items-end gap-2">
							<!-- The item lives on the line, as it does on the item-request
							     form. The store keeper counting a delivery cannot change it —
							     they say how much arrived, not what was bought — so for them
							     it stays the plain label it always was. -->
							<div class="min-w-[200px] flex-1">
								<LinkField
									v-if="!readOnlyLines"
									v-model="line.item_code"
									:fetcher="itemFetcher"
									label="Item"
									@picked="(option) => onItemPicked(line, option)"
								/>
								<template v-else>
									<label class="mb-1.5 block text-p-sm text-ink-gray-6">Item</label>
									<div
										class="flex h-8 items-center rounded border border-outline-gray-3 bg-surface-gray-1 px-2"
									>
										<span class="truncate text-p-sm text-ink-gray-8">{{ line.item_name }}</span>
									</div>
								</template>
							</div>
							<div class="w-[120px]">
								<label class="mb-1.5 block text-p-sm text-ink-gray-6">Qty</label>
								<input
									v-model.number="line.qty"
									type="number"
									min="0"
									step="any"
									inputmode="decimal"
									class="h-8 w-full rounded border border-outline-gray-3 bg-surface-white px-2 text-right text-p-sm text-ink-gray-8 focus:border-outline-gray-5 focus:outline-none focus:ring-1 focus:ring-outline-gray-3"
								/>
							</div>
							<div class="w-[120px]">
								<label class="mb-1.5 block text-p-sm text-ink-gray-6">Rate</label>
								<input
									v-model.number="line.rate"
									type="number"
									min="0"
									step="any"
									inputmode="decimal"
									:disabled="readOnlyLines"
									class="h-8 w-full rounded border border-outline-gray-3 bg-surface-white px-2 text-right text-p-sm text-ink-gray-8 focus:border-outline-gray-5 focus:outline-none focus:ring-1 focus:ring-outline-gray-3 disabled:bg-surface-gray-2 disabled:text-ink-gray-5"
								/>
							</div>
							<div class="w-[120px]">
								<label class="mb-1.5 block text-p-sm text-ink-gray-6">Amount</label>
								<div
									class="tabular flex h-8 items-center justify-end rounded border border-outline-gray-3 bg-surface-gray-1 px-2 text-p-sm font-medium text-ink-gray-8"
								>
									{{ fmtMoney(Number(line.qty || 0) * Number(line.rate || 0)) }}
								</div>
							</div>
							<button
								v-if="!readOnlyLines"
								class="grid h-8 w-8 shrink-0 place-items-center rounded-md text-ink-gray-5 transition-colors hover:bg-surface-gray-2 hover:text-ink-red-3"
								:aria-label="`Remove ${line.item_name}`"
								@click="removeLine(i)"
							>
								<LucideX class="h-4 w-4" />
							</button>
						</div>

						<div v-if="line.item_code" class="flex flex-wrap items-center gap-2">
							<span class="truncate text-p-xs text-ink-gray-5">
								{{ line.item_code }}<template v-if="line.uom"> · {{ line.uom }}</template>
							</span>
							<span
								v-if="stockFor(line)"
								class="tabular rounded-full px-2 py-0.5 text-p-xs font-medium"
								:class="stockTone(line)"
							>
								{{ stockLabel(line) }}
							</span>
							<span v-else-if="stockLoading" class="text-p-xs text-ink-gray-5">
								Checking stock…
							</span>
							<span v-if="draft.toWarehouse" class="truncate text-p-xs text-ink-gray-5">
								at {{ draft.toWarehouse }}
							</span>
						</div>
					</div>

					<!-- One line at a time, the way the item-request form does it. -->
					<Button
						v-if="!readOnlyLines"
						variant="subtle"
						:icon-left="LucidePlus"
						label="Add line"
						class="self-start"
						@click="addLine"
					/>
				</div>

				<div class="flex items-center justify-between px-1">
					<span class="text-p-sm text-ink-gray-6">Total</span>
					<span class="tabular text-p-lg font-semibold text-ink-gray-9">
						{{ fmtMoney(total) }}
					</span>
				</div>

				<input
					v-model="draft.remarks"
					type="text"
					placeholder="Note — anything worth remembering about this delivery"
					class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
				/>

				<button
					class="mt-1 flex min-h-touch w-full items-center justify-center gap-2 rounded-xl py-3 text-p-base font-semibold text-ink-white transition-all active:scale-[0.98] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
					:class="mode === 'count' ? 'bg-surface-green-3' : 'bg-surface-gray-7'"
					:disabled="!!blocker || saving"
					@click="save"
				>
					<LucideCheck v-if="mode === 'count'" class="h-4 w-4" />
					<template v-if="blocker">{{ blocker }}</template>
					<template v-else-if="saving">Saving…</template>
					<template v-else-if="mode === 'post'">Post for confirmation</template>
					<template v-else-if="mode === 'edit'">Save changes</template>
					<template v-else>Confirm receipt · {{ fmtMoney(total) }}</template>
				</button>
			</div>
		</BottomSheet>

		<BottomSheet v-model="detailOpen" :title="detail?.name || 'Purchase'" tall wide>
			<div v-if="detail" class="flex flex-col gap-3 px-4 pb-5">
				<div class="flex flex-wrap items-center gap-2">
					<span
						class="rounded-full px-2.5 py-1 text-p-xs font-semibold"
						:class="
							detail.docstatus === 0
								? 'bg-surface-amber-2 text-ink-amber-3'
								: 'bg-surface-green-2 text-ink-green-3'
						"
					>
						{{ detail.stage }}
					</span>
					<span class="text-p-sm text-ink-gray-6">{{ detail.posting_date }}</span>
					<span class="tabular ml-auto text-p-lg font-semibold text-ink-gray-9">
						{{ fmtMoney(detail.grand_total) }}
					</span>
				</div>

				<dl class="grid grid-cols-2 gap-x-4 gap-y-2.5">
					<div>
						<dt class="text-p-xs text-ink-gray-5">Supplier</dt>
						<dd class="text-p-sm text-ink-gray-9">{{ detail.supplier_name }}</dd>
					</div>
					<div>
						<dt class="text-p-xs text-ink-gray-5">Still owed</dt>
						<dd class="tabular text-p-sm text-ink-gray-9">{{ fmtMoney(detail.outstanding) }}</dd>
					</div>
					<div>
						<dt class="text-p-xs text-ink-gray-5">Supplier bill no.</dt>
						<dd class="text-p-sm text-ink-gray-9">{{ detail.bill_no || '—' }}</dd>
					</div>
					<div>
						<dt class="text-p-xs text-ink-gray-5">Posted by</dt>
						<dd class="truncate text-p-sm text-ink-gray-9">{{ detail.posted_by }}</dd>
					</div>
				</dl>

				<div class="rounded-lg border border-outline-gray-2">
					<div
						v-for="line in detail.items"
						:key="line.item_code"
						class="flex items-center gap-2 border-b border-outline-gray-1 px-3 py-2 text-p-sm last:border-b-0"
					>
						<span class="min-w-0 flex-1 truncate text-ink-gray-9">{{ line.item_name }}</span>
						<span class="tabular w-16 shrink-0 text-right text-ink-gray-6">
							{{ line.qty }}{{ line.uom ? ` ${line.uom}` : '' }}
						</span>
						<span class="tabular w-24 shrink-0 text-right text-ink-gray-6">
							{{ fmtMoney(line.rate) }}
						</span>
						<span class="tabular w-28 shrink-0 text-right font-medium text-ink-gray-9">
							{{ fmtMoney(line.amount) }}
						</span>
					</div>
				</div>

				<p v-if="detail.remarks" class="text-p-sm text-ink-gray-6">{{ detail.remarks }}</p>

				<div class="flex flex-wrap gap-2 border-t border-outline-gray-2 pt-3">
					<Button
						v-if="detail.can?.confirm"
						theme="green"
						variant="solid"
						:icon-left="LucideCheck"
						label="Check &amp; confirm"
						@click="(detailOpen = false), openFor(detail, 'count')"
					/>
					<Button
						v-if="detail.can?.edit"
						variant="subtle"
						:icon-left="LucidePencil"
						label="Edit"
						@click="(detailOpen = false), openFor(detail, 'edit')"
					/>
					<Button
						v-if="detail.can?.reopen"
						variant="subtle"
						:icon-left="LucideRotateCcw"
						label="Reopen"
						@click="reopen(detail)"
					/>
					<Button
						v-if="detail.can?.delete"
						theme="red"
						variant="subtle"
						:icon-left="LucideTrash2"
						label="Delete"
						@click="removing = detail"
					/>
				</div>
			</div>
		</BottomSheet>

		<Dialog
			:model-value="!!removing"
			:options="{ title: 'Delete this purchase?', size: 'sm' }"
			@update:model-value="(open) => !open && (removing = null)"
		>
			<template #body-content>
				<p class="text-p-base text-ink-gray-7">
					{{ removing?.name }} from
					{{ removing?.supplier_name || removing?.supplier }} has not been confirmed, so no
					stock was received and nothing is owed for it. Deleting it leaves no trace.
				</p>
			</template>
			<template #actions>
				<div class="flex gap-2">
					<Button
						theme="red"
						variant="solid"
						class="flex-1"
						:loading="removeBusy"
						label="Delete"
						@click="confirmRemove"
					/>
					<Button variant="subtle" label="Keep it" @click="removing = null" />
				</div>
			</template>
		</Dialog>

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
