<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { fmtMoney, fmtMoneyShort, round2 } from '@/utils/format'
import BottomSheet from './BottomSheet.vue'
import LucideCheck from '~icons/lucide/check'
import LucideUserPlus from '~icons/lucide/user-plus'
import LucideAlertTriangle from '~icons/lucide/alert-triangle'
import LucideX from '~icons/lucide/x'
import LucideSplit from '~icons/lucide/split'
import LucideTruck from '~icons/lucide/truck'
import LucideChevronLeft from '~icons/lucide/chevron-left'
import PaymentLogo from './PaymentLogo.vue'

const props = defineProps({
	modelValue: { type: Boolean, default: false },
	total: { type: Number, default: 0 },
	/** Selected customer, or null for walk-in. Required for a credit sale. */
	customer: { type: Object, default: null },
	/**
	 * M-Pesa channels the shop is set up for, from the server. Defaulted so the
	 * sheet still works if the call has not landed — a till that cannot take
	 * payment because a lookup is slow is worse than one offering a channel that
	 * books against the generic M-Pesa mode.
	 */
	mpesaChannels: {
		type: Array,
		default: () => [
			{ key: 'mpesa_send', label: 'Send Money' },
			{ key: 'mpesa_paybill', label: 'Paybill' },
			{ key: 'mpesa_withdraw', label: 'Withdraw' },
		],
	},
	/**
	 * Every tender this till accepts, from the server — cash, each M-Pesa
	 * channel, card, and any other Mode of Payment on the POS Profile.
	 */
	methods: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:modelValue', 'complete', 'pick-customer'])

/**
 * Every tender as its own button.
 *
 * M-Pesa used to be one button that expanded into three, on the reasoning that
 * a cashier knows it is M-Pesa before they know which kind. In practice that
 * cost a second tap on the most common non-cash payment in the shop, and the
 * channel — the thing that decides which account the money lands in, and
 * therefore whether the shift reconciles — was one level down where it was easy
 * to leave on whatever it defaulted to. Flat, the choice is made once and it is
 * visible.
 *
 * Falls back to the built-in four only until the server's list arrives: a till
 * that cannot take payment because a lookup is slow is worse than one showing a
 * button it might not have.
 */
const FALLBACK = [
	{ key: 'cash', label: 'Cash', icon: 'banknote', kind: 'cash' },
	{ key: 'mpesa_send', label: 'Send Money', icon: 'smartphone', kind: 'mobile' },
	{ key: 'mpesa_paybill', label: 'Paybill', icon: 'building', kind: 'mobile' },
	{ key: 'mpesa_withdraw', label: 'Withdraw', icon: 'hand-coins', kind: 'mobile' },
	{ key: 'card', label: 'Card', icon: 'credit-card', kind: 'card' },
]

/** Credit is not a Mode of Payment — it is the absence of one — so it is
 *  appended here rather than expected from the server. */
const CREDIT = { key: 'credit', label: 'Credit', icon: 'notebook', kind: 'credit' }

const tenders = computed(() => [
	...(props.methods.length ? props.methods : FALLBACK),
	CREDIT,
])


/**
 * A colour per kind of tender, so they are told apart by more than a word.
 *
 * The badge names the brand; this tints the button behind it, so the selected
 * tender is obvious at arm's length without the badge having to change.
 *
 * Green for money that settles immediately, blue for a machine, amber for money
 * that has not arrived yet. The label still says what it says, so nothing here
 * is carried by colour alone.
 */
const TENDER_TONES = {
	// `-2` is the deepest outline the theme defines for green, blue and amber —
	// only gray and red go further. Naming a `-3` compiles to nothing and the
	// border silently falls back to the default, which is the sort of thing that
	// looks fine in a diff and wrong on screen.
	cash: {
		on: 'border-outline-green-2 bg-surface-green-2 text-ink-green-3',
		icon: 'text-ink-green-3',
	},
	mobile: {
		on: 'border-outline-green-2 bg-surface-green-2 text-ink-green-3',
		icon: 'text-ink-green-3',
	},
	card: {
		on: 'border-outline-blue-2 bg-surface-blue-2 text-ink-blue-3',
		icon: 'text-ink-blue-3',
	},
	credit: {
		on: 'border-outline-amber-2 bg-surface-amber-2 text-ink-amber-3',
		icon: 'text-ink-amber-3',
	},
	other: {
		on: 'border-outline-gray-4 bg-surface-gray-3 text-ink-gray-9',
		icon: 'text-ink-gray-7',
	},
}

function tenderTone(tender) {
	return TENDER_TONES[tender.kind] || TENDER_TONES.other
}

const method = ref('cash')
const tendered = ref('')
const reference = ref('')
const tenderedInput = ref(null)

/** The tender on screen, and therefore what the server books against. */
const activeTender = computed(
	() => tenders.value.find((t) => t.key === method.value) || tenders.value[0] || null,
)

/** Each channel is its own button now, so the key is simply the selection. */
const tenderKey = computed(() => method.value)

/** Cash is the only tender that takes more than is owed and gives change back. */
const isCash = computed(() => activeTender.value?.kind === 'cash')

/** Everything that settles through a machine or a phone carries a reference. */
const needsReference = computed(() =>
	['mobile', 'card', 'other'].includes(activeTender.value?.kind),
)

const referenceLabel = computed(() =>
	activeTender.value?.kind === 'card'
		? 'Card reference'
		: `${activeTender.value?.label || 'Payment'} code`,
)

const tenderedNum = computed(() => Number(tendered.value) || 0)
const change = computed(() => round2(Math.max(0, tenderedNum.value - props.total)))
const shortfall = computed(() => round2(Math.max(0, props.total - tenderedNum.value)))

const isCredit = computed(() => method.value === 'credit')

/* ---------- delivery ---------- */

/**
 * Whether this sale leaves the shop on a van, and the details of the drop.
 *
 * Captured here rather than assembled afterwards from the Deliveries screen:
 * the cashier is standing with the customer who is telling them the address. An
 * hour later it is remembered wrong or not at all — which is the whole reason
 * trips were being reconstructed by hand.
 *
 * Only the driver and the destination are asked for at the counter. The vehicle
 * and the driver's number belong to the run, not the drop, and the server keeps
 * whatever the first stop supplied — see `deliveries.add_stop`.
 */
const isDelivery = ref(false)
const delivery = ref({ driverName: '', destination: '', driverPhone: '', vehicle: '', contactPhone: '' })

/* ---------- split tender & part payment ---------- */

const splitMode = ref(false)
/** Applied amounts per method; cash may exceed its share, giving change. */
const parts = ref([])

/** Everything the split accounts for, credit included — this is what must
 *  add up to the bill before the sale can complete. */
const partsTotal = computed(() =>
	parts.value.reduce((sum, p) => sum + (Number(p.amount) || 0), 0),
)

/** Only the money actually collected. A credit row is a promise, not a tender. */
const partsCollected = computed(() =>
	parts.value
		.filter((p) => p.method !== 'credit')
		.reduce((sum, p) => sum + (Number(p.amount) || 0), 0),
)
/** Positive = still owed, negative = over-tendered (change). */
const remaining = computed(() => props.total - partsTotal.value)

/**
 * What the customer still owes after everything entered so far.
 *
 * Computed for every method, not only for a split. Taking 400 of a 1000 bill in
 * cash is the same transaction whether or not a second tender is involved, and
 * requiring the cashier to find the split screen to express it meant the plain
 * case — one method, not enough money — could not be recorded at all.
 *
 * M-Pesa and card settle exactly by construction: the amount is whatever the
 * machine took, so a shortfall on them is entered as a split instead.
 */
const owing = computed(() => {
	if (isCredit.value) return props.total
	if (splitMode.value) return round2(Math.max(0, remaining.value))
	if (method.value === 'cash') return shortfall.value
	return 0
})

/** A part-payment leaves a debt behind; a credit sale is one by definition. */
const isPartial = computed(() => !isCredit.value && owing.value > 0.005)

function startSplit() {
	splitMode.value = true
	// Seed with the current method for the full amount; the cashier reduces it
	// and adds a second row, which is how a split actually gets entered.
	parts.value = [
		{ method: isCredit.value ? 'cash' : tenderKey.value, amount: '', reference: '' },
	]
}

/**
 * Split rows offer the same tenders as the main row, channels included — plus
 * credit.
 *
 * "Half now, half on account" is an ordinary thing to ask for at a counter, and
 * until now it could only be expressed by *underpaying* the split and knowing
 * that the remainder silently became a debt. Naming it as a row makes the
 * intent explicit and the arithmetic visible.
 *
 * A credit row is not a payment: it is deliberately left out of the payload, so
 * the server sees a part-paid invoice and leaves the balance on the customer's
 * account. See `complete()`.
 */
const splitOptions = computed(() => [
	{ key: 'cash', label: 'Cash' },
	...props.mpesaChannels,
	{ key: 'card', label: 'Card' },
	{ key: 'credit', label: 'On account (credit)' },
])

/** Amount parked on the customer's account rather than taken now. */
const creditPart = computed(() =>
	parts.value
		.filter((p) => p.method === 'credit')
		.reduce((sum, p) => sum + (Number(p.amount) || 0), 0),
)

function addPart() {
	const used = new Set(parts.value.map((p) => p.method))
	const next = splitOptions.value.find((o) => !used.has(o.key))?.key || 'cash'
	parts.value.push({ method: next, amount: '', reference: '' })
}

function removePart(i) {
	parts.value.splice(i, 1)
	if (!parts.value.length) splitMode.value = false
}

/** Fill this row with whatever is still owed — the common second-row action. */
function fillRemaining(i) {
	const others = parts.value.reduce(
		(sum, p, j) => sum + (j === i ? 0 : Number(p.amount) || 0),
		0,
	)
	parts.value[i].amount = String(Math.max(0, +(props.total - others).toFixed(2)))
}

/**
 * One rule, applied everywhere: money has to have been entered, and anything
 * left owing has to have somebody's name on it.
 *
 * Cash no longer demands the full amount. It used to, which made a part-payment
 * impossible on the most common tender in the shop — the button simply stayed
 * grey with no explanation, and the only way through was a split screen the
 * cashier had no reason to open.
 */
const canComplete = computed(() => {
	if (props.total <= 0) return false
	// A trip with no driver is a record nobody can act on.
	if (isDelivery.value && !delivery.value.driverName.trim()) return false
	if (isCredit.value) return Boolean(props.customer)

	if (splitMode.value) {
		if (partsTotal.value <= 0) return false
		// Anything left on account needs somebody to owe it — a credit row and an
		// underpaid split are the same debt, expressed two ways.
		if (creditPart.value > 0) return Boolean(props.customer)
		return isPartial.value ? Boolean(props.customer) : true
	}

	if (isCash.value) {
		if (tenderedNum.value <= 0) return false
		return isPartial.value ? Boolean(props.customer) : true
	}

	return true
})

/**
 * Quick-cash chips. Rather than fixed denominations, these are derived from the
 * amount due — the notes a customer would plausibly hand over for THIS total.
 * Saves the cashier doing mental arithmetic during a queue.
 */
const quickAmounts = computed(() => {
	const t = props.total
	if (t <= 0) return []
	const set = new Set([Math.ceil(t)])
	for (const step of [100, 500, 1000]) {
		const up = Math.ceil(t / step) * step
		if (up > t) set.add(up)
	}
	for (const note of [500, 1000, 2000, 5000]) {
		if (note > t) set.add(note)
	}
	return [...set].sort((a, b) => a - b).slice(0, 5)
})

// Reset every time the sheet opens — a stale tendered amount from the previous
// customer is a genuine cash-drawer error waiting to happen.
watch(
	() => props.modelValue,
	async (open) => {
		if (!open) return
		method.value = tenders.value[0]?.key || 'cash'
		tendered.value = ''
		reference.value = ''
		splitMode.value = false
		parts.value = []
		isDelivery.value = false
		delivery.value = { driverName: '', destination: '', driverPhone: '', vehicle: '', contactPhone: '' }
		await nextTick()
		tenderedInput.value?.focus()
	},
)

function complete() {
	if (!canComplete.value) return

	if (splitMode.value) {
		emit('complete', {
			method: 'split',
			// Credit rows are omitted on purpose: the server treats anything the
			// payment rows do not cover as owed, which is exactly what "on
			// account" means. Sending it as a tender would book money that was
			// never handed over.
			parts: parts.value
				.filter((p) => p.method !== 'credit' && Number(p.amount) > 0)
				.map((p) => ({
					method: p.method,
					amount: Number(p.amount),
					reference: p.reference || null,
				})),
			delivery: isDelivery.value ? { ...delivery.value } : null,
			tendered: partsCollected.value,
			change: remaining.value < 0 ? -remaining.value : 0,
			outstanding: creditPart.value || (isPartial.value ? remaining.value : 0),
		})
		return
	}

	emit('complete', {
		// The M-Pesa channel, not the bare method — that is what decides the
		// Mode of Payment and therefore which account the money lands in.
		method: tenderKey.value,
		delivery: isDelivery.value ? { ...delivery.value } : null,
		// A credit sale collects nothing now.
		tendered: isCredit.value ? 0 : isCash.value ? tenderedNum.value : props.total,
		change: isCash.value ? change.value : 0,
		// Reported so the confirmation can name the balance. The server derives
		// the real outstanding from the invoice either way — this is what the
		// cashier was told, not what is booked.
		outstanding: isPartial.value ? owing.value : 0,
		reference: reference.value,
	})
}

/**
 * One step back rather than straight out.
 *
 * Split is a mode entered from this sheet, so leaving it should return here —
 * closing the whole sheet would discard a tender the cashier has already keyed
 * in, which is the one thing a back button must never do.
 */
function goBack() {
	if (splitMode.value) {
		splitMode.value = false
		parts.value = []
		return
	}
	emit('update:modelValue', false)
}
</script>

<template>
	<BottomSheet
		:model-value="modelValue"
		tall
		@update:model-value="emit('update:modelValue', $event)"
	>
		<div class="flex flex-col gap-2.5 px-4 pb-4 pt-1">
			<!-- Back sits beside the amount rather than above it: the amount due is
			     still the thing being looked at, and a header row of its own would
			     push it below the fold on a phone. -->
			<div class="flex items-center gap-2">
				<button
					class="grid h-10 w-10 shrink-0 place-items-center rounded-lg text-ink-gray-6 transition-colors hover:bg-surface-gray-2"
					:aria-label="splitMode ? 'Back to payment methods' : 'Back to cart'"
					@click="goBack"
				>
					<LucideChevronLeft class="h-5 w-5" />
				</button>
				<div class="min-w-0 flex-1 text-center">
					<div class="text-p-sm text-ink-gray-5">
						{{ splitMode ? 'Split payment · amount due' : 'Amount due' }}
					</div>
					<div class="tabular text-3xl font-semibold leading-tight tracking-tight text-ink-gray-9">
						{{ fmtMoney(total) }}
					</div>
				</div>
				<!-- Balances the back button so the amount stays optically centred. -->
				<div class="h-10 w-10 shrink-0" aria-hidden="true" />
			</div>

			<!-- Split tender / part payment -->
			<div v-if="splitMode" class="flex flex-col gap-2">
				<div v-for="(p, i) in parts" :key="i" class="rounded-xl border border-outline-gray-2 p-3">
					<div class="flex items-center gap-2">
						<select
							v-model="p.method"
							class="h-11 min-w-0 flex-1 rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-2 text-p-base text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
						>
							<option v-for="o in splitOptions" :key="o.key" :value="o.key">
								{{ o.label }}
							</option>
						</select>
						<input
							v-model="p.amount"
							type="number"
							inputmode="decimal"
							placeholder="0"
							class="tabular h-11 w-28 rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-2 text-right text-p-lg font-semibold text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
							@focus="$event.target.select()"
						/>
						<button
							class="grid h-11 w-11 shrink-0 place-items-center rounded-lg text-ink-gray-5 transition-colors hover:bg-surface-gray-2"
							aria-label="Remove"
							@click="removePart(i)"
						>
							<LucideX class="h-4 w-4" />
						</button>
					</div>
					<button
						v-if="remaining > 0.005"
						class="mt-2 text-p-sm font-medium text-ink-blue-3"
						@click="fillRemaining(i)"
					>
						Fill remaining {{ fmtMoney(remaining) }}
					</button>
				</div>

				<div class="flex items-center gap-2">
					<button
						class="min-h-touch flex-1 rounded-xl border border-outline-gray-2 py-2.5 text-p-base font-medium text-ink-gray-7 transition-colors hover:bg-surface-gray-2"
						@click="addPart"
					>
						+ Add method
					</button>
					<button
						class="min-h-touch rounded-xl px-4 py-2.5 text-p-base font-medium text-ink-gray-6 transition-colors hover:bg-surface-gray-2"
						@click="splitMode = false"
					>
						Cancel split
					</button>
				</div>

				<!-- The balance is the number the cashier is deciding on. -->
				<div
					class="flex items-center justify-between rounded-xl px-4 py-2.5"
					:class="
						Math.abs(remaining) < 0.005
							? 'bg-surface-green-2'
							: remaining > 0
								? 'bg-surface-amber-2'
								: 'bg-surface-blue-2'
					"
				>
					<span
						class="text-p-base font-medium"
						:class="
							Math.abs(remaining) < 0.005
								? 'text-ink-green-3'
								: remaining > 0
									? 'text-ink-amber-3'
									: 'text-ink-blue-3'
						"
					>
						{{
							Math.abs(remaining) < 0.005
								? 'Fully paid'
								: remaining > 0
									? 'Balance owed'
									: 'Change due'
						}}
					</span>
					<span
						class="tabular text-2xl font-semibold"
						:class="
							Math.abs(remaining) < 0.005
								? 'text-ink-green-3'
								: remaining > 0
									? 'text-ink-amber-3'
									: 'text-ink-blue-3'
						"
					>
						{{ fmtMoney(Math.abs(remaining)) }}
					</span>
				</div>

				<!-- A part-paid sale creates a debt, so it needs a named customer. -->
				<button
					v-if="isPartial"
					class="flex min-h-touch items-center gap-3 rounded-xl border p-2.5 text-left transition-colors"
					:class="
						customer
							? 'border-outline-gray-2 bg-surface-white hover:bg-surface-gray-2'
							: 'border-outline-amber-2 bg-surface-amber-2'
					"
					@click="emit('pick-customer')"
				>
					<LucideUserPlus
						class="h-5 w-5 shrink-0"
						:class="customer ? 'text-ink-gray-5' : 'text-ink-amber-3'"
					/>
					<div class="min-w-0 flex-1">
						<div
							class="truncate text-p-base font-medium"
							:class="customer ? 'text-ink-gray-9' : 'text-ink-amber-3'"
						>
							{{ customer ? customer.customer_name || customer.name : 'Choose a customer' }}
						</div>
						<div class="text-p-sm text-ink-gray-6">
							{{
								customer
									? `Will owe ${fmtMoney(remaining)}`
									: 'Required — someone must owe the balance'
							}}
						</div>
					</div>
				</button>
			</div>

			<!-- Split entry point. Kept out of the method row: splitting is the
			     exception, and it must not crowd the four one-tap methods. -->
			<button
				v-if="!splitMode && !isCredit"
				class="flex min-h-touch items-center justify-center gap-2 rounded-xl border border-outline-gray-2 py-2 text-p-base font-medium text-ink-gray-7 transition-colors hover:bg-surface-gray-2"
				@click="startSplit"
			>
				<LucideSplit class="h-4 w-4" />
				Split or part-pay
			</button>

			<!-- Every tender, one tap. Three across so six or seven fit without
			     the labels shrinking to initials. -->
			<div v-if="!splitMode" class="grid grid-cols-3 gap-2">
				<button
					v-for="m in tenders"
					:key="m.key"
					class="flex min-h-touch flex-col items-center gap-1 rounded-xl border px-1 py-2 transition-colors"
					:class="
						method === m.key
							? tenderTone(m).on
							: 'border-outline-gray-2 bg-surface-white text-ink-gray-6 hover:bg-surface-gray-2'
					"
					@click="method = m.key"
				>
					<!-- The brand badge, matched on the Mode of Payment's own name, so
					     a shop that adds Airtel Money gets an Airtel badge without a
					     code change. The label stays underneath: a logo says which
					     network, the words say which channel — Paybill and Send Money
					     share a badge and are not the same tender. -->
					<PaymentLogo :name="m.mode_of_payment || m.label" :kind="m.kind" />
					<span class="w-full truncate text-center text-p-xs font-medium">{{ m.label }}</span>
				</button>
			</div>

			<!-- Credit: the customer IS the transaction, so it leads. -->
			<div v-if="!splitMode && isCredit" class="flex flex-col gap-2">
				<button
					class="flex min-h-touch items-center gap-3 rounded-xl border p-2.5 text-left transition-colors"
					:class="
						customer
							? 'border-outline-gray-2 bg-surface-white hover:bg-surface-gray-2'
							: 'border-outline-amber-2 bg-surface-amber-2'
					"
					@click="emit('pick-customer')"
				>
					<LucideUserPlus
						class="h-5 w-5 shrink-0"
						:class="customer ? 'text-ink-gray-5' : 'text-ink-amber-3'"
					/>
					<div class="min-w-0 flex-1">
						<div
							class="truncate text-p-base font-medium"
							:class="customer ? 'text-ink-gray-9' : 'text-ink-amber-3'"
						>
							{{ customer ? customer.customer_name || customer.name : 'Choose a customer' }}
						</div>
						<div class="text-p-sm text-ink-gray-6">
							{{ customer ? 'Tap to change' : 'Required — someone must owe this' }}
						</div>
					</div>
				</button>

				<!-- Existing debt shown before adding more to it. -->
				<div
					v-if="customer && customer.outstanding > 0"
					class="flex items-start gap-2.5 rounded-xl bg-surface-amber-2 px-4 py-2.5"
				>
					<LucideAlertTriangle class="mt-0.5 h-4 w-4 shrink-0 text-ink-amber-3" />
					<div class="text-p-sm">
						<div class="font-medium text-ink-amber-3">
							Already owes {{ fmtMoney(customer.outstanding) }}
						</div>
						<div class="tabular mt-0.5 text-ink-gray-7">
							This sale takes them to {{ fmtMoney(customer.outstanding + total) }}
						</div>
					</div>
				</div>

				<div class="rounded-xl bg-surface-gray-2 px-4 py-2.5 text-p-sm text-ink-gray-6">
					Nothing is collected now. The invoice stays unpaid on the customer's account
					and is not counted in the drawer at close.
				</div>
			</div>

			<!-- Cash -->
			<div v-else-if="method === 'cash'" class="flex flex-col gap-2">
				<div>
					<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">
						Cash received
					</label>
					<input
						ref="tenderedInput"
						v-model="tendered"
						type="number"
						inputmode="decimal"
						placeholder="0.00"
						class="tabular h-12 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-4 text-2xl font-semibold text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none focus:ring-2 focus:ring-outline-gray-3"
						@focus="$event.target.select()"
						@keyup.enter="complete"
					/>
				</div>

				<div class="flex flex-wrap gap-2">
					<button
						v-for="amt in quickAmounts"
						:key="amt"
						class="tabular min-h-touch flex-1 rounded-lg border border-outline-gray-2 bg-surface-white px-3 text-p-base font-medium text-ink-gray-7 transition-colors hover:bg-surface-gray-2 active:bg-surface-gray-3"
						@click="tendered = String(amt)"
					>
						{{ fmtMoneyShort(amt) }}
					</button>
				</div>

				<!-- A cash sale that does not cover the bill is a part-payment, and
				     the balance has to sit against somebody. Appears the moment the
				     amount entered falls short, in the same place the split panel
				     puts it, so the two paths ask the same question the same way. -->
				<button
					v-if="isPartial"
					class="flex min-h-touch items-center gap-3 rounded-xl border p-2.5 text-left transition-colors"
					:class="
						customer
							? 'border-outline-gray-2 bg-surface-white hover:bg-surface-gray-2'
							: 'border-outline-amber-2 bg-surface-amber-2'
					"
					@click="emit('pick-customer')"
				>
					<LucideUserPlus
						class="h-5 w-5 shrink-0"
						:class="customer ? 'text-ink-gray-5' : 'text-ink-amber-3'"
					/>
					<div class="min-w-0 flex-1">
						<div
							class="truncate text-p-base font-medium"
							:class="customer ? 'text-ink-gray-9' : 'text-ink-amber-3'"
						>
							{{ customer ? customer.customer_name || customer.name : 'Choose a customer' }}
						</div>
						<div class="text-p-sm text-ink-gray-6">
							{{
								customer
									? `Will owe ${fmtMoney(owing)}`
									: 'Required — someone must owe the balance'
							}}
						</div>
					</div>
				</button>

				<!-- Change is the highest-stakes number on this screen, so it gets
				     colour and size the moment it becomes real. -->
				<div
					class="flex items-center justify-between rounded-xl px-4 py-2.5 transition-colors"
					:class="
						change > 0
							? 'bg-surface-green-2'
							: shortfall > 0
								? 'bg-surface-amber-2'
								: 'bg-surface-gray-2'
					"
				>
					<span
						class="text-p-base font-medium"
						:class="
							change > 0
								? 'text-ink-green-3'
								: shortfall > 0
									? 'text-ink-amber-3'
									: 'text-ink-gray-6'
						"
					>
						{{ shortfall > 0 ? 'Still owing' : 'Change due' }}
					</span>
					<span
						class="tabular text-2xl font-semibold"
						:class="
							change > 0
								? 'text-ink-green-3'
								: shortfall > 0
									? 'text-ink-amber-3'
									: 'text-ink-gray-7'
						"
					>
						{{ fmtMoney(shortfall > 0 ? shortfall : change) }}
					</span>
				</div>
			</div>

			<!-- Reference, for anything that settles through a phone or a machine.
			     Named after the tender actually chosen, so a Paybill payment asks
			     for a Paybill code rather than a generic one. -->
			<div v-else-if="needsReference">
				<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">
					{{ referenceLabel }}
					<span class="font-normal text-ink-gray-4">(optional)</span>
				</label>
				<input
					v-model="reference"
					type="text"
					autocapitalize="characters"
					:placeholder="activeTender?.kind === 'card' ? 'Last 4 digits' : 'e.g. SLK7XR2QM4'"
					class="h-12 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-4 text-p-lg uppercase text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none focus:ring-2 focus:ring-outline-gray-3"
					@keyup.enter="complete"
				/>
			</div>

			<!-- Going out on a van. Collapsed by default — most sales are carried
			     out of the shop, and a form nobody needs is a form in the way. -->
			<div class="mb-2 rounded-xl border border-outline-gray-2">
				<label class="flex min-h-touch cursor-pointer items-center gap-3 px-3 py-2.5">
					<input v-model="isDelivery" type="checkbox" class="h-4 w-4 accent-gray-800" />
					<LucideTruck class="h-5 w-5 shrink-0 text-ink-gray-5" />
					<span class="text-p-base font-medium text-ink-gray-9">Deliver this order</span>
				</label>

				<div v-if="isDelivery" class="flex flex-col gap-2 border-t border-outline-gray-1 p-3">
					<input
						v-model="delivery.driverName"
						type="text"
						placeholder="Driver name (required)"
						class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
					/>
					<input
						v-model="delivery.destination"
						type="text"
						placeholder="Destination — estate, street, landmark"
						class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
					/>
					<div class="grid grid-cols-2 gap-2">
						<input
							v-model="delivery.vehicle"
							type="text"
							placeholder="Vehicle"
							class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
						/>
						<input
							v-model="delivery.contactPhone"
							type="tel"
							inputmode="tel"
							placeholder="Customer phone"
							class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
						/>
					</div>
					<p class="text-p-xs text-ink-gray-5">
						Joins this driver's run for today if they already have one.
					</p>
				</div>
			</div>

			<button
				class="flex min-h-touch w-full items-center justify-center gap-2 rounded-xl bg-surface-gray-7 py-3 text-p-lg font-semibold text-ink-white transition-all active:scale-[0.98] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
				:disabled="!canComplete"
				@click="complete"
			>
				<LucideCheck class="h-5 w-5" />
				{{
					isCredit
						? 'Record credit sale'
						: isPartial
							? `Take part-payment · ${fmtMoney(owing)} owed`
							: 'Complete sale'
				}}
			</button>
		</div>
	</BottomSheet>
</template>
