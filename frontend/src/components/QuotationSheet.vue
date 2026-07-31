<script setup>
import { ref, computed, watch } from 'vue'
import { fmtMoney, fmtMoneyShort } from '@/utils/format'
import {
	listQuotations,
	getQuotation,
	getQuotationPrintUrl,
	sendQuotationWhatsapp,
} from '@/data/api'
import BottomSheet from './BottomSheet.vue'
import LucideFileText from '~icons/lucide/file-text'
import LucideSearch from '~icons/lucide/search'
import LucidePrinter from '~icons/lucide/printer'
import LucideSend from '~icons/lucide/send'

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
})

const emit = defineEmits(['update:modelValue', 'save', 'load', 'sent'])

const TABS = [
	{ label: 'Saved quotes', value: 'list' },
	{ label: 'Quote this cart', value: 'save' },
]
const tab = ref('list')

const rows = ref([])
const totals = ref({})
const loading = ref(false)
const search = ref('')
const onlyOpen = ref(true)

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
watch([search, onlyOpen], () => {
	clearTimeout(timer)
	timer = setTimeout(load, 250)
})

async function load() {
	loading.value = true
	try {
		const res = await listQuotations({
			search: search.value || null,
			status: onlyOpen.value ? 'open' : null,
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

function save() {
	if (!canSave.value) return
	emit('save', {
		validDays: Number(validDays.value) || 14,
		notes: notes.value || null,
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
		const { url } = await getQuotationPrintUrl({ name: row.name })
		window.open(url, '_blank', 'noopener')
	} catch (e) {
		console.error('[quotations] print failed', e)
	} finally {
		busyOne.value = ''
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
					<div class="text-p-lg font-semibold text-ink-gray-9">Quotations</div>
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

					<button
						class="min-h-touch w-full rounded-xl bg-surface-gray-7 py-3.5 text-p-lg font-semibold text-ink-white transition-all active:scale-[0.98] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
						:disabled="!canSave"
						@click="save"
					>
						{{ busy ? 'Saving…' : `Quote ${fmtMoney(total)}` }}
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
					<input v-model="onlyOpen" type="checkbox" class="h-4 w-4 rounded" />
					Only quotes still open
				</label>

				<p v-if="loading" class="px-1 text-p-sm text-ink-gray-5">Loading…</p>

				<p v-else-if="!rows.length" class="px-1 text-p-sm text-ink-gray-5">
					No quotations match. Quote a cart from the other tab and it will show up here.
				</p>

				<div v-else class="flex flex-col gap-2">
					<button
						v-for="q in rows"
						:key="q.name"
						class="flex items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors"
						:class="
							q.expired
								? 'border-outline-gray-2 bg-surface-gray-1 hover:bg-surface-gray-2'
								: 'border-outline-gray-2 bg-surface-white hover:bg-surface-gray-2'
						"
						:disabled="loadingOne === q.name"
						@click="loadQuote(q)"
					>
						<div class="min-w-0 flex-1">
							<div class="truncate text-p-base font-medium text-ink-gray-9">
								{{ q.customer }}
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

					<!-- Beside the row, not inside it: loading a quote into the cart
					     and sending it to a customer are different intentions, and a
					     mis-tap between them replaces the cart. -->
					<div class="-mt-1 mb-1 flex items-center gap-2 pl-1">
						<button
							class="flex items-center gap-1 rounded-md px-2 py-1 text-p-xs font-medium text-ink-gray-6 hover:bg-surface-gray-2 hover:text-ink-gray-8"
							:disabled="busyOne === q.name"
							@click="printQuote(q)"
						>
							<LucidePrinter class="h-3.5 w-3.5" />
							Print
						</button>
						<button
							class="flex items-center gap-1 rounded-md px-2 py-1 text-p-xs font-medium text-ink-gray-6 hover:bg-surface-gray-2 hover:text-ink-gray-8"
							:disabled="busyOne === q.name"
							@click="sendQuote(q)"
						>
							<LucideSend class="h-3.5 w-3.5" />
							{{ busyOne === q.name ? 'Sending…' : 'WhatsApp' }}
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
			</template>
		</div>
	</BottomSheet>
</template>
