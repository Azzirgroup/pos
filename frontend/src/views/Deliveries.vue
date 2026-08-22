<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Button, Dialog } from 'frappe-ui'
import { fmtMoney } from '@/utils/format'
import {
	listDeliveries,
	setDeliveryStatus,
	getDeliveryPrintUrl,
	getDelivery,
	updateDelivery,
	deleteDelivery,
	createDelivery,
	createRider,
	searchRiders,
} from '@/data/api'
import { printUrl } from '@/utils/silentPrint'
import PageHeader from '@/components/PageHeader.vue'
import StatTiles from '@/components/StatTiles.vue'
import PillTabs from '@/components/PillTabs.vue'
import LinkField from '@/components/LinkField.vue'
import DateField from '@/components/DateField.vue'
import BottomSheet from '@/components/BottomSheet.vue'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucidePrinter from '~icons/lucide/printer'
import LucideTruck from '~icons/lucide/truck'
import LucidePlus from '~icons/lucide/plus'
import LucideSearch from '~icons/lucide/search'
import LucidePhone from '~icons/lucide/phone'
import LucideMapPin from '~icons/lucide/map-pin'
import LucideEye from '~icons/lucide/eye'
import LucidePencil from '~icons/lucide/pencil'
import LucideTrash2 from '~icons/lucide/trash-2'
import LucideChevronLeft from '~icons/lucide/chevron-left'
import LucideChevronRight from '~icons/lucide/chevron-right'
import LucideCalendarDays from '~icons/lucide/calendar-days'

/**
 * What is going out, and where it has got to.
 *
 * A worklist rather than a report. The day's deliveries are read at a counter
 * by somebody deciding what to do next — hand this one to a rider, ring that
 * customer back — so the two things every row leads with are the address and
 * the button that moves it along.
 *
 * Statuses are the shop's own four: Pending until it leaves, Dispatched once
 * the rider has it, then Delivered or Failed. Dispatching is the one that
 * matters — it stamps the time and messages the customer and the manager, both
 * on the server (see `CosmesticsDelivery.on_update`), so a status changed here
 * and one changed in the desk behave identically.
 */
const STATUS_TABS = [
	{ label: 'All', value: '' },
	{ label: 'Pending', value: 'Pending' },
	{ label: 'Dispatched', value: 'Dispatched' },
	{ label: 'Delivered', value: 'Delivered' },
	{ label: 'Failed', value: 'Failed' },
]

/** What each status may become next, in the order a rider actually moves. */
const NEXT_STATUS = {
	Pending: ['Dispatched', 'Failed'],
	Dispatched: ['Delivered', 'Failed'],
	Delivered: [],
	// A failed drop is re-attempted, not re-created: the address and the
	// instructions are already right, and retyping them is how they drift.
	Failed: ['Pending', 'Dispatched'],
}

const STATUS_TONES = {
	Pending: 'bg-surface-amber-2 text-ink-amber-3',
	Dispatched: 'bg-surface-blue-2 text-ink-blue-3',
	Delivered: 'bg-surface-green-2 text-ink-green-3',
	Failed: 'bg-surface-red-2 text-ink-red-3',
}

/** Every status, for the edit sheet — which may set any of them. */
const ALL_STATUSES = ['Pending', 'Dispatched', 'Delivered', 'Failed']

/**
 * Today, in the shop's own timezone.
 *
 * `toISOString()` alone is UTC, which in Nairobi means the screen flips to
 * "tomorrow" at three in the afternoon. The offset is subtracted first so the
 * date this sends matches the date on the wall.
 */
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
const busy = ref('')
const status = ref('')
const search = ref('')

/**
 * The screen opens on **today**, and the calendar pages back.
 *
 * It used to open on a rolling fortnight with an empty date box beside it, and
 * the complaint was exactly what that produces: a counter asking "what is going
 * out today" had to read past two weeks of history to find out, and the date
 * input — a bare `<input type="date">` squeezed into a filter row — was the
 * only way to narrow it. Now the day *is* the view: arrows either side, the
 * date in the middle, and a Today button that is only offered when you are not
 * on it.
 *
 * The fortnight is still there, behind "Recent", for the Monday-morning
 * question the old default was really serving: what went out on Friday and was
 * never marked delivered.
 */
const today = ref(localDay())
const onDate = ref(localDay())
const showRecent = ref(false)

const dayLabel = computed(() => {
	if (showRecent.value) return 'Last 14 days'
	if (onDate.value === today.value) return 'Today'
	if (onDate.value === addDays(today.value, -1)) return 'Yesterday'
	return new Date(`${onDate.value}T12:00:00`).toLocaleDateString(undefined, {
		weekday: 'short',
		day: 'numeric',
		month: 'short',
	})
})

const rows = computed(() => data.value?.rows || [])

const stats = computed(() => {
	const t = data.value?.totals || {}
	return [
		// Asked for by name: how many deliveries have been posted today. Counted
		// on the server from the rows on screen, so it means the same thing when
		// the view has been paged back to last Tuesday.
		{
			label: "Today's deliveries",
			value: t.today || 0,
			type: 'number',
			icon: 'truck',
			hint: 'Posted today',
		},
		{
			label: 'Pending',
			value: t.Pending || 0,
			type: 'number',
			icon: 'hourglass',
			tone: t.Pending ? 'warn' : 'default',
		},
		{ label: 'On the way', value: t.Dispatched || 0, type: 'number', icon: 'truck' },
		{ label: 'Delivered', value: t.Delivered || 0, type: 'number', icon: 'package' },
		{ label: 'Order value', value: t.value || 0, type: 'currency', icon: 'wallet' },
	]
})

onMounted(load)

let timer = null
watch([status, onDate, showRecent], load)
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
		data.value = await listDeliveries({
			status: status.value || null,
			search: search.value || null,
			// One day, unless "Recent" is on — then the fortnight the screen used
			// to default to, which is the window that catches a Friday drop
			// nobody closed off.
			onDate: showRecent.value ? null : onDate.value,
			days: 14,
		})
	} catch (e) {
		notify(e.message || 'Could not load the deliveries', 'bad')
		data.value = null
	} finally {
		loading.value = false
	}
}

function stepDay(delta) {
	showRecent.value = false
	onDate.value = addDays(onDate.value, delta)
}

function goToday() {
	showRecent.value = false
	onDate.value = today.value
}

async function move(row, next) {
	busy.value = row.name
	try {
		const res = await setDeliveryStatus({ name: row.name, status: next })
		await load()
		notify(
			next === 'Dispatched'
				? `${res.name} dispatched — ${row.customer_name || 'the customer'} has been told`
				: res.message,
			next === 'Failed' ? 'bad' : 'good',
		)
	} catch (e) {
		notify(e.message || `Could not mark that ${next}`, 'bad')
	} finally {
		busy.value = ''
	}
}

/**
 * The slip for the carton.
 *
 * Straight to the printer rather than into a preview tab — the shop asked for
 * this to replace writing the address on the box by hand, and a step between
 * the button and the paper is a step that gets skipped.
 */
async function printLabel(row) {
	try {
		const { url } = await getDeliveryPrintUrl({ name: row.name })
		printUrl(url, () => notify('Could not reach the printer', 'bad'))
	} catch (e) {
		notify(e.message || 'Could not open the label', 'bad')
	}
}

/* ---------- opening, correcting and removing one ---------- */

/**
 * The row opens.
 *
 * Every field this screen records was already being collected and none of it
 * could be read back — the row showed an address and a status, and the map pin,
 * the instructions, the invoice and the vehicle were only ever visible to
 * whoever typed them. A worklist you cannot open is a worklist you have to
 * remember.
 *
 * Read fresh rather than reusing the row in hand: on a shared till the list can
 * be minutes old, and a sheet that opens on a stale status is how two people
 * dispatch the same parcel.
 */
const detail = ref(null)
const detailOpen = ref(false)
const detailLoading = ref(false)

async function openRow(row) {
	detail.value = row
	detailOpen.value = true
	detailLoading.value = true
	try {
		detail.value = await getDelivery({ name: row.name })
	} catch (e) {
		notify(e.message || 'Could not open that delivery', 'bad')
	} finally {
		detailLoading.value = false
	}
}

/**
 * Correcting a drop that is already recorded.
 *
 * Including its **status**, which the row buttons deliberately cannot do: those
 * offer the one or two moves a rider actually makes next, in order, because
 * that is what a counter needs at a glance. Reversing a delivery marked
 * delivered by mistake back to Pending is the other thing — rarer, deliberate,
 * and it belongs in a form rather than on a button somebody can fat-finger.
 *
 * The customer's *name* is here as well as on the new-delivery form. A drop
 * typed in for a phone order had nowhere to put it and read "Walk-in" on the
 * worklist with a number beside it, which tells a rider nothing about who they
 * are looking for.
 */
const editOpen = ref(false)
const editing = ref(null)
const editDraft = ref(null)
const editSaving = ref(false)

function openEdit(row) {
	editing.value = row.name
	editDraft.value = {
		status: row.status,
		customer_name: row.customer_name || '',
		contact_phone: row.contact_phone || '',
		address: row.address || '',
		landmark: row.landmark || '',
		map_location: row.map_location || '',
		delivery_instructions: row.delivery_instructions || '',
		rider_name: row.rider_name || '',
		rider_phone: row.rider_phone || '',
		courier: row.courier || '',
		vehicle: row.vehicle || '',
		delivery_date: row.delivery_date || '',
	}
	editOpen.value = true
}

const editBlocker = computed(() => {
	const d = editDraft.value
	if (!d) return null
	if (!d.address.trim()) return 'Add the delivery address'
	if (!d.contact_phone.trim()) return 'Add a contact number'
	return null
})

async function saveEdit() {
	if (editBlocker.value || !editing.value) return
	editSaving.value = true
	try {
		const res = await updateDelivery({ name: editing.value, values: { ...editDraft.value } })
		editOpen.value = false
		// The detail sheet is usually open underneath — this is reached from it —
		// so it is refreshed rather than left showing what was just corrected.
		if (detailOpen.value && detail.value?.name === res.name) detail.value = res
		await load()
		notify(res.message, 'good')
	} catch (e) {
		notify(e.message || 'Could not save that change', 'bad')
	} finally {
		editSaving.value = false
	}
}

/**
 * Removing one.
 *
 * Confirmed in a sheet rather than a browser `confirm()`, and the sheet names
 * the delivery: this list is read on a tablet at a counter, where the row under
 * your thumb and the row you meant are one pixel apart.
 *
 * A drop that has already gone out is refused by the server — see
 * `deliveries.delete_delivery` — so the button is not offered for those either.
 */
const removing = ref(null)
const removeBusy = ref(false)

const canRemove = (row) => row.status === 'Pending' || row.status === 'Failed'

async function confirmRemove() {
	if (!removing.value) return
	removeBusy.value = true
	try {
		const res = await deleteDelivery({ name: removing.value.name })
		if (detail.value?.name === removing.value.name) detailOpen.value = false
		removing.value = null
		await load()
		notify(res.message, 'good')
	} catch (e) {
		notify(e.message || 'Could not delete that delivery', 'bad')
	} finally {
		removeBusy.value = false
	}
}

/* ---------- raising one by hand ---------- */

/**
 * A delivery with no sale behind it.
 *
 * Most are created from the pay sheet as the sale is rung up, which is the
 * right moment. This is for the rest: a customer who phones an order in, or a
 * drop somebody forgot to tick at the counter and is now standing in the shop
 * about to leave with it.
 */
const newOpen = ref(false)
const saving = ref(false)
const draft = ref(blank())

function blank() {
	return {
		customerName: '',
		rider: '',
		riderName: '',
		riderPhone: '',
		courier: '',
		contactPhone: '',
		address: '',
		landmark: '',
		mapLocation: '',
		instructions: '',
		invoice: '',
	}
}

const riderFetcher = (term) => searchRiders(term)

/**
 * Creating a rider from inside the field, ERPNext's own two-step shape.
 *
 * A link field there offers "Create a new …" and opens a quick entry with the
 * record's own fields, rather than inventing one from whatever was typed. Both
 * halves matter and this screen only had the first:
 *
 * - Typing a name and taking the offer creates a rider with **only** a name.
 *   That is the right amount of friction when the shop is busy — but a rider
 *   with no number is a delivery nobody can chase, and the number is in the
 *   cashier's hand at exactly that moment.
 * - So the offer opens the form instead, pre-filled with what was typed. The
 *   phone, the courier and the vehicle are asked for once, here, rather than
 *   left to be filled in later from a Records screen nobody goes back to.
 *
 * `LinkField` awaits whatever `on-create` returns and selects it, so this
 * hands back a promise that settles when the dialog does — resolved with the
 * new rider, or with null if it was dismissed, which leaves the field as it
 * was.
 */
const riderOpen = ref(false)
const riderSaving = ref(false)
const riderDraft = ref(blankRider())
/** Resolver for the promise `createRiderFor` handed to `LinkField`. */
let riderResolve = null

function blankRider() {
	return { riderName: '', phone: '', courier: '', vehicle: '' }
}

function createRiderFor(typed) {
	riderDraft.value = {
		...blankRider(),
		riderName: typed || '',
		// Carried across rather than asked for twice: a cashier who has already
		// typed the number into the delivery meant that number.
		phone: draft.value.riderPhone || '',
		courier: draft.value.courier || '',
	}
	riderOpen.value = true
	return new Promise((resolve) => {
		riderResolve = resolve
	})
}

/** Add the rider straight from the Records-style form, without a New button. */
function openNewRider() {
	createRiderFor(draft.value.riderName || '')
}

const riderBlocker = computed(() =>
	riderDraft.value.riderName.trim() ? null : 'Name the rider',
)

async function saveRider() {
	if (riderBlocker.value) return
	riderSaving.value = true
	try {
		const row = await createRider({
			riderName: riderDraft.value.riderName.trim(),
			phone: riderDraft.value.phone || null,
			courier: riderDraft.value.courier || null,
			vehicle: riderDraft.value.vehicle || null,
		})
		// Selected into the delivery, which is the whole reason the form was
		// opened from the field rather than from a Records screen.
		draft.value.rider = row.value
		onRiderPicked(row)
		riderOpen.value = false
		settleRider(row)
		notify(`${row.rider_name} added`, 'good')
	} catch (e) {
		notify(e.message || 'Could not add that rider', 'bad')
	} finally {
		riderSaving.value = false
	}
}

/** Hand the waiting `LinkField` its answer, exactly once. */
function settleRider(row) {
	const resolve = riderResolve
	riderResolve = null
	// Dismissing resolves with null rather than rejecting: cancelling a quick
	// entry is an ordinary thing to do, not an error to report.
	if (resolve) resolve(row || null)
}

// Covers the dismissals that do not go through `saveRider` — the backdrop, the
// close button, Escape. Without it the field would sit waiting on a promise
// that never settles, and its "Creating…" spinner would never stop.
watch(riderOpen, (open) => {
	if (!open) settleRider(null)
})

function onRiderPicked(row) {
	if (!row) return
	draft.value.riderName = row.rider_name || row.value || ''
	draft.value.riderPhone = draft.value.riderPhone || row.phone || ''
	draft.value.courier = draft.value.courier || row.courier || ''
}

/** The same four fields the pay sheet insists on, for the same reason. */
const blocker = computed(() => {
	const d = draft.value
	if (!d.rider && !d.riderName.trim()) return 'Choose the rider'
	if (!d.courier.trim()) return 'Say which courier'
	if (!d.contactPhone.trim()) return 'Add a contact number'
	if (!d.address.trim()) return 'Add the delivery address'
	return null
})

async function save() {
	if (blocker.value) return
	saving.value = true
	try {
		const res = await createDelivery({ ...draft.value })
		newOpen.value = false
		draft.value = blank()
		await load()
		notify(res.message, 'good')
	} catch (e) {
		notify(e.message || 'Could not record that delivery', 'bad')
	} finally {
		saving.value = false
	}
}

function where(row) {
	return [row.address, row.landmark].filter(Boolean).join(' · ')
}

const toast = ref(null)
let toastTimer = null
function notify(message, tone = 'good') {
	toast.value = { message, tone }
	clearTimeout(toastTimer)
	toastTimer = setTimeout(() => (toast.value = null), 3200)
}
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col overflow-hidden">
		<PageHeader title="Delivery" subtitle="What is going out, and where it has got to">
			<template #actions>
				<Button
					variant="subtle"
					:icon-left="LucidePlus"
					label="New delivery"
					@click="newOpen = true"
				/>
				<Button variant="subtle" :icon-left="LucideRefreshCw" :loading="loading" @click="load" />
			</template>
		</PageHeader>

		<StatTiles :stats="stats" dense />

		<div class="flex shrink-0 flex-wrap items-center gap-2 border-b border-outline-gray-2 px-4 pb-3">
			<PillTabs v-model="status" :buttons="STATUS_TABS" inset />
			<div class="relative ml-auto w-full sm:w-[260px]">
				<LucideSearch
					class="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-gray-4"
				/>
				<input
					v-model="search"
					type="text"
					placeholder="Customer, rider, invoice, address…"
					class="h-9 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 pl-8 pr-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
				/>
			</div>
			<!-- The day, as a pager rather than a date box.
			     Arrows for "the day before this one", which is how somebody
			     actually moves through a delivery log, and the date itself as the
			     calendar for the jump that is further than a tap or two. The
			     native picker is still underneath — it is what every phone and
			     tablet already knows how to open — but it is no longer the only
			     way to change the day, which is what made it feel broken. -->
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
					<!-- Covers the label so a tap anywhere on it opens the picker.
					     Transparent rather than hidden: a `display: none` input has
					     no `showPicker` to open on any browser. -->
					<input
						v-model="onDate"
						type="date"
						aria-label="Pick a delivery day"
						class="absolute inset-0 h-full w-full cursor-pointer opacity-0"
						@change="showRecent = false"
					/>
				</label>
				<button
					class="grid h-full w-8 place-items-center text-ink-gray-6 transition-colors hover:bg-surface-gray-3 hover:text-ink-gray-8 disabled:opacity-30"
					aria-label="Day after"
					:disabled="!showRecent && onDate >= today"
					@click="stepDay(1)"
				>
					<LucideChevronRight class="h-4 w-4" />
				</button>
				<!-- Only offered when it would do something. -->
				<button
					v-if="showRecent || onDate !== today"
					class="h-full border-l border-outline-gray-2 px-2.5 text-p-xs font-semibold text-ink-gray-7 transition-colors hover:bg-surface-gray-3"
					@click="goToday"
				>
					Today
				</button>
			</div>
			<!-- The old default, kept as a choice: Monday morning wants the drop
			     that went out on Friday and was never closed off. -->
			<button
				class="h-9 shrink-0 rounded-lg border px-3 text-p-sm font-medium transition-colors"
				:class="
					showRecent
						? 'border-outline-gray-4 bg-surface-gray-7 text-ink-white'
						: 'border-outline-gray-2 text-ink-gray-7 hover:bg-surface-gray-2'
				"
				@click="showRecent = !showRecent"
			>
				Recent
			</button>
		</div>

		<div class="min-h-0 flex-1 overflow-auto px-4 py-4">
			<p v-if="loading && !rows.length" class="py-10 text-center text-p-sm text-ink-gray-5">
				Loading…
			</p>
			<p v-else-if="!rows.length" class="py-10 text-center text-p-sm text-ink-gray-5">
				<template v-if="showRecent">Nothing in the last fortnight.</template>
				<template v-else>
					Nothing going out {{ dayLabel === 'Today' ? 'today' : `on ${dayLabel}` }}. Tick
					"Deliver this order" when taking payment, or add one above.
				</template>
			</p>

			<div v-else class="flex flex-col gap-2">
				<div
					v-for="row in rows"
					:key="row.name"
					class="flex flex-col gap-2 rounded-xl border border-outline-gray-2 bg-surface-white p-3"
				>
					<!-- The whole head of the card opens it. The action buttons at the
					     foot are outside this, so tapping "Mark dispatched" does not
					     also open a sheet over the thing it just did. -->
					<div
						class="-m-1 flex min-w-0 cursor-pointer items-start gap-3 rounded-lg p-1 transition-colors hover:bg-surface-gray-1"
						role="button"
						tabindex="0"
						@click="openRow(row)"
						@keyup.enter="openRow(row)"
					>
						<span
							class="grid h-9 w-9 shrink-0 place-items-center rounded-lg"
							:class="STATUS_TONES[row.status]"
						>
							<LucideTruck class="h-4 w-4" />
						</span>
						<div class="min-w-0 flex-1">
							<div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
								<span class="max-w-full truncate text-p-base font-medium text-ink-gray-9">
									{{ row.customer_name || row.customer || 'Walk-in' }}
								</span>
								<span
									class="shrink-0 rounded-full px-2 py-0.5 text-p-xs font-medium"
									:class="STATUS_TONES[row.status]"
								>
									{{ row.status }}
								</span>
								<span v-if="row.amount" class="tabular shrink-0 text-p-sm text-ink-gray-6">
									{{ fmtMoney(row.amount) }}
								</span>
							</div>
							<div class="truncate text-p-xs text-ink-gray-5">
								{{ row.name }} · {{ row.delivery_date }}
								<template v-if="row.sales_invoice"> · {{ row.sales_invoice }}</template>
								<!-- The one number this screen exists to record. Shown on the
								     row rather than behind a tap: "when did that go out" is
								     asked about a list, not about one delivery. -->
								<template v-if="row.dispatched_at">
									· out {{ row.dispatched_at.slice(11, 16) }}
								</template>
							</div>
						</div>
					</div>

					<div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-p-xs text-ink-gray-6">
						<span class="flex min-w-0 items-center gap-1.5">
							<LucideMapPin class="h-3.5 w-3.5 shrink-0 text-ink-gray-4" />
							<span class="truncate">{{ where(row) || '—' }}</span>
						</span>
						<span v-if="row.contact_phone" class="flex items-center gap-1.5">
							<LucidePhone class="h-3.5 w-3.5 shrink-0 text-ink-gray-4" />
							<a :href="`tel:${row.contact_phone}`" class="underline underline-offset-2">
								{{ row.contact_phone }}
							</a>
						</span>
						<span class="truncate">
							{{ row.rider_name || '—' }}
							<template v-if="row.courier"> · {{ row.courier }}</template>
						</span>
					</div>

					<p
						v-if="row.delivery_instructions"
						class="rounded-lg bg-surface-amber-1 px-2.5 py-1.5 text-p-xs font-medium text-ink-amber-3"
					>
						{{ row.delivery_instructions }}
					</p>

					<div class="flex flex-wrap items-center gap-2 border-t border-outline-gray-1 pt-2">
						<button
							v-for="next in NEXT_STATUS[row.status] || []"
							:key="next"
							class="rounded-md px-2.5 py-1.5 text-p-xs font-semibold transition-colors disabled:opacity-50"
							:class="
								next === 'Failed'
									? 'border border-outline-gray-2 bg-surface-white text-ink-gray-7 hover:border-outline-red-2 hover:bg-surface-red-1 hover:text-ink-red-3'
									: 'bg-surface-gray-7 text-ink-white hover:bg-surface-gray-6'
							"
							:disabled="busy === row.name"
							@click="move(row, next)"
						>
							{{ busy === row.name ? 'Working…' : `Mark ${next.toLowerCase()}` }}
						</button>
						<!-- View, edit, delete — asked for by name, and grouped away from
						     the status buttons on the left. Those two sets do different
						     kinds of thing: one moves the delivery along, the other
						     manages the record of it. -->
						<div class="ml-auto flex items-center gap-1.5">
							<button
								class="flex items-center gap-1.5 rounded-md border border-outline-gray-2 px-2.5 py-1.5 text-p-xs font-semibold text-ink-gray-7 transition-colors hover:bg-surface-gray-2"
								title="View the full delivery"
								@click="openRow(row)"
							>
								<LucideEye class="h-3.5 w-3.5" />
								<span class="hidden sm:inline">View</span>
							</button>
							<button
								class="flex items-center gap-1.5 rounded-md border border-outline-gray-2 px-2.5 py-1.5 text-p-xs font-semibold text-ink-gray-7 transition-colors hover:bg-surface-gray-2"
								title="Correct this delivery"
								@click="openEdit(row)"
							>
								<LucidePencil class="h-3.5 w-3.5" />
								<span class="hidden sm:inline">Edit</span>
							</button>
							<button
								class="flex items-center gap-1.5 rounded-md border border-outline-gray-2 px-2.5 py-1.5 text-p-xs font-semibold text-ink-gray-7 transition-colors hover:bg-surface-gray-2"
								title="Print the label"
								@click="printLabel(row)"
							>
								<LucidePrinter class="h-3.5 w-3.5" />
								<span class="hidden sm:inline">Label</span>
							</button>
							<!-- Not offered once it has gone out: the server refuses those
							     — see `deliveries.delete_delivery` — and a button that
							     always errors is worse than no button. -->
							<button
								v-if="canRemove(row)"
								class="flex items-center gap-1.5 rounded-md border border-outline-gray-2 px-2.5 py-1.5 text-p-xs font-semibold text-ink-gray-7 transition-colors hover:border-outline-red-2 hover:bg-surface-red-1 hover:text-ink-red-3"
								title="Delete this delivery"
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

		<!-- The delivery, opened. Everything the row could not fit, and the two
		     buttons somebody who has just read it wants next. -->
		<BottomSheet v-model="detailOpen" :title="detail?.name || 'Delivery'" tall>
			<div v-if="detail" class="flex flex-col gap-3 px-4 pb-5">
				<div class="flex flex-wrap items-center gap-2">
					<span
						class="rounded-full px-2.5 py-1 text-p-xs font-semibold"
						:class="STATUS_TONES[detail.status]"
					>
						{{ detail.status }}
					</span>
					<span class="text-p-sm text-ink-gray-6">{{ detail.delivery_date }}</span>
					<span v-if="detailLoading" class="text-p-xs text-ink-gray-4">Refreshing…</span>
					<span v-if="detail.amount" class="tabular ml-auto text-p-base font-medium text-ink-gray-9">
						{{ fmtMoney(detail.amount) }}
					</span>
				</div>

				<dl class="grid grid-cols-1 gap-x-4 gap-y-2.5 sm:grid-cols-2">
					<div>
						<dt class="text-p-xs text-ink-gray-5">Customer</dt>
						<dd class="text-p-sm text-ink-gray-9">
							{{ detail.customer_name || detail.customer || 'Walk-in' }}
						</dd>
					</div>
					<div>
						<dt class="text-p-xs text-ink-gray-5">Contact</dt>
						<dd class="text-p-sm text-ink-gray-9">
							<a
								v-if="detail.contact_phone"
								:href="`tel:${detail.contact_phone}`"
								class="underline underline-offset-2"
							>
								{{ detail.contact_phone }}
							</a>
							<template v-else>—</template>
						</dd>
					</div>
					<div class="sm:col-span-2">
						<dt class="text-p-xs text-ink-gray-5">Address</dt>
						<dd class="whitespace-pre-line text-p-sm text-ink-gray-9">
							{{ detail.address || '—' }}
						</dd>
					</div>
					<div>
						<dt class="text-p-xs text-ink-gray-5">Building or landmark</dt>
						<dd class="text-p-sm text-ink-gray-9">{{ detail.landmark || '—' }}</dd>
					</div>
					<div>
						<dt class="text-p-xs text-ink-gray-5">Pinned location</dt>
						<dd class="truncate text-p-sm text-ink-gray-9">
							<a
								v-if="detail.map_location"
								:href="detail.map_location"
								target="_blank"
								rel="noopener"
								class="underline underline-offset-2"
							>
								Open the map
							</a>
							<template v-else>—</template>
						</dd>
					</div>
					<div>
						<dt class="text-p-xs text-ink-gray-5">Rider</dt>
						<dd class="text-p-sm text-ink-gray-9">
							{{ detail.rider_name || '—' }}
							<span v-if="detail.rider_phone" class="text-ink-gray-6">
								· {{ detail.rider_phone }}
							</span>
						</dd>
					</div>
					<div>
						<dt class="text-p-xs text-ink-gray-5">Courier</dt>
						<dd class="text-p-sm text-ink-gray-9">
							{{ detail.courier || '—' }}
							<span v-if="detail.vehicle" class="text-ink-gray-6">· {{ detail.vehicle }}</span>
						</dd>
					</div>
					<div v-if="detail.sales_invoice">
						<dt class="text-p-xs text-ink-gray-5">Invoice</dt>
						<dd class="text-p-sm text-ink-gray-9">{{ detail.sales_invoice }}</dd>
					</div>
					<!-- The two timestamps the shop asks about after the fact: when did
					     it leave, and when did it land. -->
					<div v-if="detail.dispatched_at">
						<dt class="text-p-xs text-ink-gray-5">Dispatched</dt>
						<dd class="text-p-sm text-ink-gray-9">{{ detail.dispatched_at.slice(0, 16) }}</dd>
					</div>
					<div v-if="detail.delivered_at">
						<dt class="text-p-xs text-ink-gray-5">Delivered</dt>
						<dd class="text-p-sm text-ink-gray-9">{{ detail.delivered_at.slice(0, 16) }}</dd>
					</div>
				</dl>

				<p
					v-if="detail.delivery_instructions"
					class="rounded-lg bg-surface-amber-1 px-3 py-2 text-p-sm font-medium text-ink-amber-3"
				>
					{{ detail.delivery_instructions }}
				</p>

				<div class="flex flex-wrap gap-2 border-t border-outline-gray-2 pt-3">
					<Button
						variant="subtle"
						:icon-left="LucidePencil"
						label="Edit"
						@click="openEdit(detail)"
					/>
					<Button
						variant="subtle"
						:icon-left="LucidePrinter"
						label="Label"
						@click="printLabel(detail)"
					/>
					<Button
						v-if="canRemove(detail)"
						theme="red"
						variant="subtle"
						:icon-left="LucideTrash2"
						label="Delete"
						@click="removing = detail"
					/>
				</div>
			</div>
		</BottomSheet>

		<!-- Correcting one. The status is a plain select rather than the ordered
		     buttons on the row: this is where a delivery marked delivered by
		     mistake gets put back to pending, which the row deliberately will not
		     offer. -->
		<BottomSheet v-model="editOpen" title="Edit delivery" tall>
			<div v-if="editDraft" class="flex flex-col gap-2.5 px-4 pb-5">
				<div class="grid grid-cols-2 gap-2">
					<div>
						<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">Status</label>
						<select
							v-model="editDraft.status"
							class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
						>
							<option v-for="s in ALL_STATUSES" :key="s" :value="s">{{ s }}</option>
						</select>
					</div>
					<!-- The whole control opens the calendar, not the glyph at the
					     end of it — see `DateField`. -->
					<DateField v-model="editDraft.delivery_date" label="Delivery date" />
				</div>
				<input
					v-model="editDraft.customer_name"
					type="text"
					placeholder="Customer name"
					class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
				/>
				<input
					v-model="editDraft.contact_phone"
					type="tel"
					placeholder="Contact number *"
					class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
				/>
				<textarea
					v-model="editDraft.address"
					rows="2"
					placeholder="Address *"
					class="w-full resize-y rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 py-2 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
				/>
				<div class="grid grid-cols-2 gap-2">
					<input
						v-model="editDraft.landmark"
						type="text"
						placeholder="Building or landmark"
						class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
					/>
					<input
						v-model="editDraft.map_location"
						type="text"
						placeholder="Pinned location (link)"
						class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
					/>
				</div>
				<div class="grid grid-cols-2 gap-2">
					<input
						v-model="editDraft.rider_name"
						type="text"
						placeholder="Rider"
						class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
					/>
					<input
						v-model="editDraft.rider_phone"
						type="tel"
						placeholder="Rider phone"
						class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
					/>
				</div>
				<div class="grid grid-cols-2 gap-2">
					<input
						v-model="editDraft.courier"
						type="text"
						placeholder="Courier"
						class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
					/>
					<input
						v-model="editDraft.vehicle"
						type="text"
						placeholder="Vehicle"
						class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
					/>
				</div>
				<input
					v-model="editDraft.delivery_instructions"
					type="text"
					placeholder="Delivery note"
					class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
				/>

				<button
					class="mt-1 flex min-h-touch w-full items-center justify-center gap-2 rounded-xl bg-surface-gray-7 py-3 text-p-base font-semibold text-ink-white transition-all active:scale-[0.98] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
					:disabled="!!editBlocker || editSaving"
					@click="saveEdit"
				>
					{{ editBlocker || (editSaving ? 'Saving…' : 'Save changes') }}
				</button>
			</div>
		</BottomSheet>

		<!-- Named rather than a bare "Are you sure": on a tablet at a counter the
		     row under your thumb and the row you meant are one pixel apart. -->
		<Dialog
			:model-value="!!removing"
			:options="{ title: 'Delete this delivery?', size: 'sm' }"
			@update:model-value="(open) => !open && (removing = null)"
		>
			<template #body-content>
				<p class="text-p-base text-ink-gray-7">
					{{ removing?.name }} for
					{{ removing?.customer_name || removing?.customer || 'a walk-in customer' }} will be
					removed. Nothing has been posted against it, so there is nothing to reverse — but it
					cannot be brought back.
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

		<BottomSheet v-model="newOpen" title="New delivery" tall>
			<div class="flex flex-col gap-2.5 px-4 pb-5">
				<!-- Search first, create second — the ERPNext link-field shape. Typing
				     offers "Create …" inside the list; the button beside the label is
				     for the cashier who already knows this rider is new and would
				     otherwise have to type a name just to be offered the option. -->
				<div class="flex items-end gap-2">
					<LinkField
						v-model="draft.rider"
						:fetcher="riderFetcher"
						:on-create="createRiderFor"
						label="Rider"
						required
						class="min-w-0 flex-1"
						@picked="onRiderPicked"
					/>
					<button
						class="flex h-8 shrink-0 items-center gap-1.5 rounded border border-outline-gray-3 px-2.5 text-p-sm font-medium text-ink-gray-7 transition-colors hover:bg-surface-gray-2"
						@click="openNewRider"
					>
						<LucidePlus class="h-3.5 w-3.5" />
						New rider
					</button>
				</div>
				<div class="grid grid-cols-2 gap-2">
					<input
						v-model="draft.riderPhone"
						type="tel"
						placeholder="Rider phone"
						class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
					/>
					<input
						v-model="draft.courier"
						type="text"
						placeholder="Courier *"
						class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
					/>
				</div>
				<!-- Who it is for. The form only asked for a number, so a phone
				     order typed in by hand showed as "Walk-in" on the worklist and a
				     rider had a number to ring and no name to ask for. -->
				<input
					v-model="draft.customerName"
					type="text"
					placeholder="Customer name"
					class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
				/>
				<input
					v-model="draft.contactPhone"
					type="tel"
					placeholder="Contact number *"
					class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
				/>
				<textarea
					v-model="draft.address"
					rows="2"
					placeholder="Address * — estate, street, house or shop number"
					class="w-full resize-y rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 py-2 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
				/>
				<div class="grid grid-cols-2 gap-2">
					<input
						v-model="draft.landmark"
						type="text"
						placeholder="Building or landmark"
						class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
					/>
					<input
						v-model="draft.mapLocation"
						type="text"
						placeholder="Pinned location (link)"
						class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
					/>
				</div>
				<input
					v-model="draft.instructions"
					type="text"
					placeholder="Delivery note — fragile, time sensitive, call first…"
					class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
				/>
				<input
					v-model="draft.invoice"
					type="text"
					placeholder="Sales invoice (optional)"
					class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
				/>

				<button
					class="mt-1 flex min-h-touch w-full items-center justify-center gap-2 rounded-xl bg-surface-gray-7 py-3 text-p-base font-semibold text-ink-white transition-all active:scale-[0.98] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
					:disabled="!!blocker || saving"
					@click="save"
				>
					<LucideTruck class="h-4 w-4" />
					{{ blocker || (saving ? 'Recording…' : 'Record delivery') }}
				</button>
			</div>
		</BottomSheet>

		<!-- Quick entry for a rider, opened from the link field above. A Dialog
		     rather than a second BottomSheet: it sits over the delivery being
		     filled in, and the point is that the delivery is still there
		     underneath when this closes. -->
		<Dialog v-model="riderOpen" :options="{ title: 'New rider', size: 'sm' }">
			<template #body-content>
				<div class="flex flex-col gap-2.5">
					<div>
						<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">Rider name *</label>
						<input
							v-model="riderDraft.riderName"
							type="text"
							placeholder="Who is riding"
							class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
							@keyup.enter="saveRider"
						/>
					</div>
					<div>
						<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">Phone</label>
						<input
							v-model="riderDraft.phone"
							type="tel"
							inputmode="tel"
							placeholder="The number the shop rings"
							class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
							@keyup.enter="saveRider"
						/>
					</div>
					<div class="grid grid-cols-2 gap-2">
						<div>
							<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">Courier</label>
							<input
								v-model="riderDraft.courier"
								type="text"
								placeholder="Company, or the shop"
								class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
							/>
						</div>
						<div>
							<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">Vehicle</label>
							<input
								v-model="riderDraft.vehicle"
								type="text"
								placeholder="Plate or bike"
								class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
							/>
						</div>
					</div>
					<!-- Says what happens next, because this form was opened from a
					     field that is waiting on it. -->
					<p class="text-p-xs text-ink-gray-5">
						Saved to Records and chosen for this delivery. Only the name is required —
						the rest can be filled in later.
					</p>
				</div>
			</template>
			<template #actions>
				<div class="flex gap-2">
					<Button
						theme="gray"
						variant="solid"
						class="flex-1"
						:loading="riderSaving"
						:disabled="!!riderBlocker"
						:label="riderBlocker || 'Add rider'"
						@click="saveRider"
					/>
					<Button variant="subtle" label="Cancel" @click="riderOpen = false" />
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
