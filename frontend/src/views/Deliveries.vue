<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Button, Dialog } from 'frappe-ui'
import { fmtMoney } from '@/utils/format'
import {
	listDeliveries,
	setDeliveryStatus,
	getDeliveryPrintUrl,
	createDelivery,
	createRider,
	searchRiders,
} from '@/data/api'
import { printUrl } from '@/utils/silentPrint'
import PageHeader from '@/components/PageHeader.vue'
import StatTiles from '@/components/StatTiles.vue'
import PillTabs from '@/components/PillTabs.vue'
import LinkField from '@/components/LinkField.vue'
import BottomSheet from '@/components/BottomSheet.vue'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucidePrinter from '~icons/lucide/printer'
import LucideTruck from '~icons/lucide/truck'
import LucidePlus from '~icons/lucide/plus'
import LucideSearch from '~icons/lucide/search'
import LucidePhone from '~icons/lucide/phone'
import LucideMapPin from '~icons/lucide/map-pin'

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

const data = ref(null)
const loading = ref(false)
const busy = ref('')
const status = ref('')
const search = ref('')
const onDate = ref('')

const rows = computed(() => data.value?.rows || [])

const stats = computed(() => {
	const t = data.value?.totals || {}
	return [
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
watch([status, onDate], load)
watch(search, () => {
	clearTimeout(timer)
	timer = setTimeout(load, 300)
})

async function load() {
	loading.value = true
	try {
		data.value = await listDeliveries({
			status: status.value || null,
			search: search.value || null,
			onDate: onDate.value || null,
			// A fortnight when nothing is filtered. A delivery that went out on
			// Friday and was never marked delivered is exactly the one somebody
			// is chasing on Monday, and a list that resets at midnight loses it.
			days: 14,
		})
	} catch (e) {
		notify(e.message || 'Could not load the deliveries', 'bad')
		data.value = null
	} finally {
		loading.value = false
	}
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
			<input
				v-model="onDate"
				type="date"
				aria-label="Deliveries on one day"
				class="h-9 rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
			/>
			<button
				v-if="onDate"
				class="h-9 rounded-lg border border-outline-gray-2 px-3 text-p-sm font-medium text-ink-gray-7 hover:bg-surface-gray-2"
				@click="onDate = ''"
			>
				Clear
			</button>
		</div>

		<div class="min-h-0 flex-1 overflow-auto px-4 py-4">
			<p v-if="loading && !rows.length" class="py-10 text-center text-p-sm text-ink-gray-5">
				Loading…
			</p>
			<p v-else-if="!rows.length" class="py-10 text-center text-p-sm text-ink-gray-5">
				Nothing to deliver here. Tick "Deliver this order" when taking payment, or add one above.
			</p>

			<div v-else class="flex flex-col gap-2">
				<div
					v-for="row in rows"
					:key="row.name"
					class="flex flex-col gap-2 rounded-xl border border-outline-gray-2 bg-surface-white p-3"
				>
					<div class="flex min-w-0 items-start gap-3">
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
						<button
							class="ml-auto flex items-center gap-1.5 rounded-md border border-outline-gray-2 px-2.5 py-1.5 text-p-xs font-semibold text-ink-gray-7 transition-colors hover:bg-surface-gray-2"
							@click="printLabel(row)"
						>
							<LucidePrinter class="h-3.5 w-3.5" />
							Label
						</button>
					</div>
				</div>
			</div>
		</div>

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
