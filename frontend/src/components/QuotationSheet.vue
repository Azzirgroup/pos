<script setup>
import { ref, computed, watch } from 'vue'
import { fmtMoney, fmtMoneyShort } from '@/utils/format'
import { printUrl } from '@/utils/silentPrint'
import {
	listQuotations,
	getQuotation,
	getQuotationPrintUrl,
	sendQuotationWhatsapp,
	closeQuotation,
	mergeQuotations,
} from '@/data/api'
import BottomSheet from './BottomSheet.vue'
import LucideFileText from '~icons/lucide/file-text'
import LucideSearch from '~icons/lucide/search'
import LucidePrinter from '~icons/lucide/printer'
import LucideSend from '~icons/lucide/send'
import LucideCart from '~icons/lucide/shopping-cart'
import LucideUserRound from '~icons/lucide/user-round'
import LucideMerge from '~icons/lucide/git-merge'

/**
 * Quotations, from the till.
 *
 * Two jobs in one sheet because they are the two halves of the same thing: a
 * customer asks for a price and leaves, then comes back with it. Saving the
 * cart and loading one back are a tab apart rather than a screen apart.
 *
 * Open quotes lead, and expiry is computed rather than trusted — ERPNext only
 * flips a quotation to Expired when its scheduler runs, so one that lapsed this
 * morning still reads Open until then, and a cashier would honour it.
 */
const props = defineProps({
	modelValue: { type: Boolean, default: false },
	/** Cart lines, so the sheet can say what it is about to quote. */
	lines: { type: Array, default: () => [] },
	total: { type: Number, default: 0 },
	customer: { type: Object, default: null },
	busy: { type: Boolean, default: false },
	/** Set when the cart came off a saved quote — saving updates that one. */
	editingQuotation: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'save', 'load', 'sent'])

const TABS = [
	{ label: "Today's Quotes", value: 'list' },
	{ label: 'Quote this cart', value: 'save' },
]
const tab = ref('list')

const rows = ref([])
const totals = ref({})
const loading = ref(false)
const search = ref('')
/**
 * Today's quotes only, on by default.
 *
 * A cashier is being asked about a price given this morning; a quote from last
 * week is a back-office question. Filtering server-side rather than in the
 * browser so the count on the tab is the count of what is actually listed.
 */
const todayOnly = ref(true)

const validDays = ref('14')
const notes = ref('')

watch(
	() => props.modelValue,
	(open) => {
		if (!open) return
		// Lands on saving when there is something to save and nothing else to do
		// with the sheet — a cashier with a full cart opened this to quote it.
		tab.value = props.lines.length ? 'save' : 'list'
		validDays.value = '14'
		notes.value = ''
		load()
	},
)

let timer = null
watch([search, todayOnly], () => {
	clearTimeout(timer)
	timer = setTimeout(load, 250)
})

async function load() {
	loading.value = true
	try {
		const res = await listQuotations({
			search: search.value || null,
			status: null,
			todayOnly: todayOnly.value ? 1 : 0,
		})
		rows.value = res.rows || []
		totals.value = res.totals || {}
	} catch (e) {
		console.error('[quotations]', e)
		rows.value = []
	} finally {
		loading.value = false
	}
}

const canSave = computed(() => props.lines.length > 0 && !props.busy)

function save(asNew = false) {
	if (!canSave.value) return
	emit('save', {
		validDays: Number(validDays.value) || 14,
		notes: notes.value || null,
		// Editing a loaded quote updates it in place unless this is set — see
		// `quotations.update` for why raising a second document is the bug.
		asNew,
	})
}

/**
 * Loading fetches the full quote — the list carries totals, not lines.
 *
 * The sheet resolves it rather than the view, so the view is handed cart lines
 * and never has to know that a list row and a loadable quote are different
 * shapes.
 */
const loadingOne = ref('')

/**
 * Printing and sending a saved quote.
 *
 * Both go through the document itself rather than the list row: a customer
 * given a quote should get the shop's letterhead and the real prices, and a
 * screenshot of a summary is not something anyone can hold the shop to.
 */
const busyOne = ref('')
const sendTo = ref('')
const sendingFor = ref('')

async function printQuote(row) {
	busyOne.value = row.name
	try {
		// Straight to the printer — no tab, no preview. See `utils/silentPrint`.
		const { url } = await getQuotationPrintUrl({ name: row.name })
		printUrl(url, () => emit('sent', 'Could not reach the printer'))
	} catch (e) {
		console.error('[quotations] print failed', e)
	} finally {
		busyOne.value = ''
	}
}

/**
 * Stop chasing a quote the customer is not coming back for.
 *
 * Recorded as Lost, which is ERPNext's word for it — see `quotations.close`.
 * Confirmed first: this is the one row action that changes the document rather
 * than just producing a copy of it, and it sits next to two that do not.
 */
const closingOne = ref('')

/**
 * Quotes ticked for merging.
 *
 * A Set on the sheet rather than a flag on each row: the rows are replaced
 * wholesale every time the list reloads, and a selection living on them would
 * quietly reset itself mid-task.
 */
const picked = ref(new Set())
const merging = ref(false)

function togglePick(name) {
	const next = new Set(picked.value)
	next.has(name) ? next.delete(name) : next.add(name)
	picked.value = next
}

const pickedRows = computed(() => rows.value.filter((r) => picked.value.has(r.name)))

/**
 * The customers involved in the selection.
 *
 * Quotes for different people can be merged — a household or a business often
 * collects several under different names — but the merged document carries
 * exactly one. Which is a decision only the shop can make, so it is asked for:
 * picking the first would put a stranger's name on somebody's bill.
 */
const mergeCustomers = computed(() => {
	const seen = new Map()
	for (const r of pickedRows.value) {
		const id = r.customer_id || r.customer
		if (id && !seen.has(id)) seen.set(id, r.customer || id)
	}
	return [...seen].map(([id, label]) => ({ id, label }))
})
const mixedCustomers = computed(() => mergeCustomers.value.length > 1)

/** Which name the merged quote carries. Only asked when there is a choice. */
const mergeCustomer = ref('')
watch(mergeCustomers, (list) => {
	// Reset whenever the selection changes the candidates, so a name chosen for
	// a previous selection cannot be carried onto this one.
	if (!list.some((c) => c.id === mergeCustomer.value)) {
		mergeCustomer.value = list.length === 1 ? list[0].id : ''
	}
})

const canMerge = computed(
	() => picked.value.size >= 2 && (!mixedCustomers.value || !!mergeCustomer.value),
)

async function mergePicked() {
	if (!canMerge.value) return
	const names = pickedRows.value.map((r) => r.name)
	if (!window.confirm(`Merge ${names.length} quotes into one? The originals will be closed.`)) return
	merging.value = true
	try {
		const res = await mergeQuotations({
			names,
			customer: mixedCustomers.value ? mergeCustomer.value : null,
		})
		emit('sent', `Merged into ${res.name}`)
		picked.value = new Set()
		await load()
	} catch (e) {
		emit('sent', e.message || 'Could not merge the quotations')
	} finally {
		merging.value = false
	}
}

/** Statuses ERPNext will still accept a close on — see `quotations.CLOSEABLE`. */
const CLOSEABLE = ['Draft', 'Open', 'Replied', 'Expired']
const canClose = (row) => CLOSEABLE.includes(row.status)

async function closeQuote(row) {
	if (!window.confirm(`Close ${row.name}? It will be recorded as Lost.`)) return
	closingOne.value = row.name
	try {
		const res = await closeQuotation({ name: row.name })
		emit('sent', res.message)
		await load()
	} catch (e) {
		emit('sent', e.message || 'Could not close the quotation')
	} finally {
		closingOne.value = ''
	}
}

async function sendQuote(row) {
	if (!sendTo.value.trim()) {
		// Asking inline rather than in another dialog: the number is one field,
		// and a sheet on top of a sheet on a phone is a wall.
		sendingFor.value = row.name
		return
	}
	busyOne.value = row.name
	try {
		const res = await sendQuotationWhatsapp({ name: row.name, to: sendTo.value.trim() })
		emit('sent', res)
		sendingFor.value = ''
		sendTo.value = ''
	} catch (e) {
		console.error('[quotations] send failed', e)
	} finally {
		busyOne.value = ''
	}
}

async function loadQuote(row) {
	loadingOne.value = row.name
	try {
		const quote = await getQuotation({ name: row.name })
		emit('load', quote)
	} catch (e) {
		console.error('[quotations] load failed', e)
	} finally {
		loadingOne.value = ''
	}
}
</script>

<template>
	<BottomSheet
		:model-value="modelValue"
		tall
		@update:model-value="emit('update:modelValue', $event)"
	>
		<div class="flex flex-col gap-3 px-4 pb-5 pt-1">
			<div class="flex items-center gap-3">
				<div class="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-surface-blue-2">
					<LucideFileText class="h-5 w-5 text-ink-blue-3" />
				</div>
				<div class="min-w-0 flex-1">
					<div class="text-p-lg font-semibold text-ink-gray-9">Shift Quotes Only</div>
					<div class="text-p-sm text-ink-gray-5">
						A price given now, honoured when they come back
					</div>
				</div>
			</div>

			<div class="flex gap-1 rounded-lg bg-surface-gray-2 p-1">
				<button
					v-for="t in TABS"
					:key="t.value"
					class="min-h-touch flex-1 rounded-md px-2 py-2 text-p-sm font-medium transition-colors"
					:class="
						tab === t.value
							? 'bg-surface-white text-ink-gray-9 shadow-sm'
							: 'text-ink-gray-6 hover:text-ink-gray-8'
					"
					@click="tab = t.value"
				>
					{{ t.label }}
					<span v-if="t.value === 'list' && totals.open" class="tabular ml-1 text-ink-gray-5">
						{{ totals.open }}
					</span>
				</button>
			</div>

			<!-- ---------- Save the cart ---------- -->
			<template v-if="tab === 'save'">
				<div v-if="!lines.length" class="rounded-xl bg-surface-gray-2 px-4 py-3 text-p-sm text-ink-gray-6">
					The cart is empty. Add what the customer is asking about, then quote it.
				</div>

				<template v-else>
					<div class="rounded-xl border border-outline-gray-2 p-3">
						<div class="flex items-baseline justify-between">
							<span class="text-p-sm font-medium text-ink-gray-7">
								{{ lines.length }} {{ lines.length === 1 ? 'line' : 'lines' }}
							</span>
							<span class="tabular text-p-lg font-semibold text-ink-gray-9">
								{{ fmtMoney(total) }}
							</span>
						</div>
						<div class="mt-1 text-p-xs text-ink-gray-5">
							{{ customer ? customer.customer_name || customer.name : 'Walk-in' }}
						</div>
					</div>

					<div>
						<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">
							Valid for
						</label>
						<div class="flex flex-wrap gap-2">
							<button
								v-for="d in ['7', '14', '30']"
								:key="d"
								class="min-h-touch flex-1 rounded-xl border px-3 py-2.5 text-p-base font-medium transition-colors"
								:class="
									validDays === d
										? 'border-outline-gray-4 bg-surface-gray-3 text-ink-gray-9'
										: 'border-outline-gray-2 bg-surface-white text-ink-gray-6'
								"
								@click="validDays = d"
							>
								{{ d }} days
							</button>
						</div>
						<p class="mt-1.5 text-p-xs text-ink-gray-5">
							The quoted prices are honoured as quoted when this is loaded back, so
							keep it short if you reprice often.
						</p>
					</div>

					<div>
						<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">
							Note <span class="font-normal text-ink-gray-4">(optional)</span>
						</label>
						<input
							v-model="notes"
							type="text"
							placeholder="Anything the customer should see"
							class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
						/>
					</div>

					<!-- Says which document this will land on. A cart loaded from a
					     quote updates that quote; without saying so, the only way to
					     find out was to save and count how many you had. -->
					<p
						v-if="editingQuotation"
						class="rounded-lg bg-surface-amber-1 px-3 py-2 text-p-sm text-ink-amber-3"
					>
						Editing <b>{{ editingQuotation }}</b> — saving updates it, keeping the same number.
					</p>

					<button
						class="min-h-touch w-full rounded-xl bg-surface-gray-7 py-3.5 text-p-lg font-semibold text-ink-white transition-all active:scale-[0.98] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
						:disabled="!canSave"
						@click="save(false)"
					>
						<template v-if="busy">Saving…</template>
						<template v-else-if="editingQuotation">
							Update {{ editingQuotation }} · {{ fmtMoney(total) }}
						</template>
						<template v-else>Quote {{ fmtMoney(total) }}</template>
					</button>

					<!-- The other intention: the customer wants a second quote rather
					     than a changed one. Rare, so it is the quieter control. -->
					<button
						v-if="editingQuotation"
						class="min-h-touch w-full rounded-xl border border-outline-gray-2 py-2.5 text-p-base font-medium text-ink-gray-7 transition-colors hover:bg-surface-gray-2 disabled:opacity-50"
						:disabled="!canSave"
						@click="save(true)"
					>
						Save as a separate quote instead
					</button>
				</template>
			</template>

			<!-- ---------- Load a saved quote ---------- -->
			<template v-else>
				<div class="relative">
					<LucideSearch
						class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-gray-4"
					/>
					<input
						v-model="search"
						type="text"
						placeholder="Search by number or customer…"
						class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 pl-9 pr-3 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
					/>
				</div>

				<label class="flex items-center gap-2 text-p-sm text-ink-gray-7">
					<input v-model="todayOnly" type="checkbox" class="h-4 w-4 rounded" />
					Only today's quotes
				</label>

				<p v-if="loading" class="px-1 text-p-sm text-ink-gray-5">Loading…</p>

				<p v-else-if="!rows.length" class="px-1 text-p-sm text-ink-gray-5">
					No quotations match. Quote a cart from the other tab and it will show up here.
				</p>

				<div v-if="!loading && rows.length" class="flex flex-col gap-2">
				<!-- Appears only once merging is possible. A bar that is always there
				     with nothing to do is a bar people stop reading. -->
				<div
					v-if="picked.size"
					class="sticky top-0 z-10 -mx-1 mb-1 flex flex-wrap items-center gap-x-2 gap-y-2 rounded-lg bg-surface-gray-2 px-3 py-2"
				>
					<span class="text-p-sm font-medium text-ink-gray-8">
						{{ picked.size }} selected
					</span>
					<!-- Only when there is genuinely a choice to make. Given a whole
					     row of its own once it appears: squeezed between the count and
					     the buttons it clipped the very name it is asking you to read,
					     which is the one thing this control exists to show. -->
					<label
						v-if="mixedCustomers"
						class="order-last flex w-full min-w-0 items-center gap-1.5"
					>
						<span class="shrink-0 text-p-xs text-ink-gray-6">Merge as</span>
						<select
							v-model="mergeCustomer"
							class="h-8 min-w-0 flex-1 rounded-md border border-outline-gray-2 bg-surface-white px-2 text-p-sm text-ink-gray-9 focus:border-outline-gray-4 focus:outline-none"
						>
							<option value="">Choose customer…</option>
							<option v-for="c in mergeCustomers" :key="c.id" :value="c.id">
								{{ c.label }}
							</option>
						</select>
					</label>
					<div class="ml-auto flex items-center gap-2">
						<button
							class="rounded-md px-2 py-1 text-p-xs text-ink-gray-6 hover:bg-surface-gray-3"
							@click="picked = new Set()"
						>
							Clear
						</button>
						<button
							class="flex items-center gap-1.5 rounded-md bg-surface-gray-7 px-2.5 py-1.5 text-p-xs font-semibold text-ink-white transition-colors hover:bg-surface-gray-6 disabled:opacity-40"
							:disabled="!canMerge || merging"
							@click="mergePicked"
						>
							<LucideMerge class="h-3.5 w-3.5" />
							{{ merging ? 'Merging…' : `Merge ${picked.size}` }}
						</button>
					</div>
				</div>

					<!-- One element per quote, wrapping both the row and its actions.
					     The `v-for` used to sit on the row button alone, which left the
					     Print/WhatsApp strip below it outside the loop referring to a
					     `q` that does not exist there — the tab threw on render as soon
					     as there was a single saved quote to list. -->
					<!-- The whole quote is one card: the row and the three things you
					     can do to it. They used to be a bordered row with a loose strip
					     of buttons floating underneath, so the buttons read as belonging
					     to the gap rather than to the quote above them. -->
					<div
						v-for="q in rows"
						:key="q.name"
						class="flex flex-col rounded-xl border px-3 py-2.5 transition-colors"
						:class="
							picked.has(q.name)
								? 'border-outline-gray-4 bg-surface-gray-2'
								: q.expired
									? 'border-outline-gray-2 bg-surface-gray-1'
									: 'border-outline-gray-2 bg-surface-white'
						"
					>
					<div class="flex items-center gap-2">
					<!-- Outside the row button, not inside it: a checkbox nested in a
					     button is invalid markup and the click lands on whichever the
					     browser feels like. -->
					<input
						v-if="canClose(q)"
						:checked="picked.has(q.name)"
						type="checkbox"
						class="h-4 w-4 shrink-0 accent-gray-800"
						:aria-label="`Select ${q.name} to merge`"
						@change="togglePick(q.name)"
					/>
					<button
						class="flex flex-1 items-center gap-3 rounded-lg px-1 py-0.5 text-left transition-colors hover:bg-surface-gray-2"
						:disabled="loadingOne === q.name"
						@click="loadQuote(q)"
					>
						<div class="min-w-0 flex-1">
							<div class="flex min-w-0 items-center gap-2">
								<span class="truncate text-p-base font-medium text-ink-gray-9">
									{{ q.customer }}
								</span>
								<!-- Who gave the price. A customer ringing back asks for the
								     person, not the number — and on a shared till the shop
								     needs to see whose quote it is becoming a sale. -->
								<span
									v-if="q.salesperson"
									class="flex shrink-0 items-center gap-1 rounded-full bg-[#EDE9FE] px-2 py-0.5 text-p-xs font-medium text-[#6D28D9]"
								>
									<LucideUserRound class="h-3 w-3" />
									{{ q.salesperson }}
								</span>
							</div>
							<div class="truncate text-p-xs text-ink-gray-5">
								{{ q.name }} · {{ q.date }}
								<!-- Stated rather than left to the status field, which lags
								     behind reality until the scheduler catches up. -->
								<span v-if="q.expired" class="font-medium text-ink-amber-3">
									· expired {{ q.valid_till }}
								</span>
								<span v-else-if="q.valid_till"> · until {{ q.valid_till }}</span>
							</div>
						</div>
						<div class="shrink-0 text-right">
							<div class="tabular text-p-base font-semibold text-ink-gray-9">
								{{ fmtMoneyShort(q.grand_total) }}
							</div>
							<div class="text-p-xs text-ink-gray-5">
								{{ loadingOne === q.name ? 'Loading…' : 'Load' }}
							</div>
						</div>
					</button>
					</div>

					<!-- Beside the row, not inside it: loading a quote into the cart
					     and sending it to a customer are different intentions, and a
					     mis-tap between them replaces the cart. -->
					<div class="mt-2 flex flex-wrap items-center gap-2 border-t border-outline-gray-1 pt-2">
						<!-- Filled rather than ghost buttons. These were two grey words
						     under a row that is itself tappable, so the eye read them as
						     labels and the actual action — Load — was the only thing that
						     looked pressable. Colour also tells them apart at a glance:
						     paper is black, WhatsApp is its own green. -->
						<button
							class="flex items-center gap-1.5 rounded-md bg-surface-gray-7 px-2.5 py-1.5 text-p-xs font-semibold text-ink-white transition-colors hover:bg-surface-gray-6 disabled:opacity-50"
							:disabled="busyOne === q.name"
							@click="printQuote(q)"
						>
							<LucidePrinter class="h-3.5 w-3.5" />
							Print
						</button>
						<button
							class="flex items-center gap-1.5 rounded-md bg-[#25D366] px-2.5 py-1.5 text-p-xs font-semibold text-white transition-colors hover:bg-[#1eb457] disabled:opacity-50"
							:disabled="busyOne === q.name"
							@click="sendQuote(q)"
						>
							<LucideSend class="h-3.5 w-3.5" />
							{{ busyOne === q.name ? 'Sending…' : 'WhatsApp' }}
						</button>
						<!-- Only while it is still a live quote. ERPNext refuses to lose
						     one that has become an order, so offering the button there
						     would promise something that cannot happen. -->
						<button
							v-if="canClose(q)"
							class="flex items-center gap-1.5 rounded-md bg-[#7C3AED] px-2.5 py-1.5 text-p-xs font-semibold text-white transition-colors hover:bg-[#6D28D9] disabled:opacity-50"
							:disabled="loadingOne === q.name"
							@click="loadQuote(q)"
						>
							<LucideCart class="h-3.5 w-3.5" />
							{{ loadingOne === q.name ? 'Loading…' : 'Convert to Sale' }}
						</button>
						<input
							v-if="sendingFor === q.name"
							v-model="sendTo"
							type="tel"
							inputmode="tel"
							placeholder="2547… then tap WhatsApp"
							class="h-8 min-w-0 flex-1 rounded-md border border-outline-gray-2 bg-surface-gray-2 px-2 text-p-xs text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
						/>
					</div>
					</div>
				</div>
			</template>
		</div>
	</BottomSheet>
</template>
