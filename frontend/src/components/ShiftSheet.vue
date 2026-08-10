<script setup>
import { ref, computed, watch } from 'vue'
import { fmtMoney, fmtMoneyShort } from '@/utils/format'
import BottomSheet from './BottomSheet.vue'
import { listCashiers } from '@/data/api'
import LucideSunrise from '~icons/lucide/sunrise'
import LucideSunset from '~icons/lucide/sunset'
import LucideCheck from '~icons/lucide/check'
import LucideChevronDown from '~icons/lucide/chevron-down'
import LucideBanknote from '~icons/lucide/banknote'
import LucideStore from '~icons/lucide/store'
import LucideX from '~icons/lucide/x'
import LucidePlus from '~icons/lucide/plus'

/**
 * Opening a shift, and everything that has to be settled before closing one.
 *
 * The three tabs exist because three different things move money at a till and
 * only one of them is a sale. Splitting them across separate screens would mean
 * three places that each know part of what the drawer should hold, and a
 * cashier reconciling against whichever one they happened to open.
 */
const props = defineProps({
	modelValue: { type: Boolean, default: false },
	/** 'open' or 'close'. */
	mode: { type: String, default: 'open' },
	profiles: { type: Array, default: () => [] },
	/** Payment modes to collect an opening float for. */
	paymentModes: { type: Array, default: () => ['Cash'] },
	summary: { type: Object, default: null },
	busy: { type: Boolean, default: false },
	/** Expense accounts, modes and neighbours for the money-out form. */
	options: { type: Object, default: null },
	movementBusy: { type: Boolean, default: false },
	/** Which tab to land on. The Expenses entry in the till opens 'money'. */
	initialTab: { type: String, default: 'count' },
	/** Sales still owed for — {rows, totals}. Loaded by the till, not here. */
	creditSales: { type: Object, default: null },
	creditBusy: { type: Boolean, default: false },
})

const emit = defineEmits([
	'update:modelValue',
	'open-shift',
	'close-shift',
	'record-movement',
	'void-movement',
	'pay-credit',
])

const profile = ref(null)
const floats = ref({})
const counted = ref({})
/**
 * mode_of_payment → [{ person, amount }] — who a shortfall is against.
 *
 * A list, because a counter is rarely one person: two cashiers on a till and
 * 500 missing is two names, not a choice between them. An empty `amount` means
 * "share what is left evenly", which is the usual answer when nobody knows
 * whose it was.
 */
const shortPeople = ref({})

/**
 * Who else is on the counter this shift — a Set of user ids.
 *
 * Named people rather than "whoever the profile permits", because those are two
 * different facts: a cashier allowed on a till is not a cashier working it, and
 * only the second one should be able to settle money against this drawer. The
 * person opening the shift is never in here — they are on it by opening it.
 */
const pickedCashiers = ref(new Set())

/** Whether the dropdown is showing. Stays open across ticks — picking two
 *  people is two taps, and a menu that closed after the first would make the
 *  second one a rediscovery. */
const cashierMenu = ref(false)

function toggleCashier(user) {
	// The row is disabled too, but the server refuses these outright — so not
	// relying on the markup alone to keep an unpickable name out of the payload.
	if (!cashierOptions.value.find((c) => c.user === user)?.eligible) return
	// Reassigned rather than mutated: Vue does not track Set mutations.
	const next = new Set(pickedCashiers.value)
	next.has(user) ? next.delete(user) : next.add(user)
	pickedCashiers.value = next
}

function onCashierBlur(event) {
	// Only when focus actually left the control. `focusout` also fires moving
	// between the rows inside it, and closing then would make the second tick
	// impossible.
	if (!event.currentTarget.contains(event.relatedTarget)) cashierMenu.value = false
}

/**
 * The co-cashiers this till permits, fetched here rather than by the parent.
 *
 * A departure from `summary` and `options` above, which the parents load and
 * pass in — and deliberate. Those are read by the parent too; this list is used
 * nowhere but the markup below. Requiring each parent to fetch it meant two
 * screens open this sheet and only one of them wired it up, so opening a shift
 * from the Shifts page silently offered no cashiers at all. A prop nobody else
 * reads is a prop somebody will forget.
 */
const cashierOptions = ref([])
const cashiersBusy = ref(false)

async function loadCashiers(posProfile) {
	if (!posProfile) {
		cashierOptions.value = []
		pickedCashiers.value = new Set()
		return
	}
	cashiersBusy.value = true
	try {
		cashierOptions.value = await listCashiers({ posProfile })
		/**
		 * Everyone the till permits starts ticked.
		 *
		 * The profile's Applicable for Users *is* the shop saying who works this
		 * counter, so requiring that to be re-stated every morning asks a question
		 * whose answer is already recorded. Starting empty also failed in the one
		 * direction that costs money: a cashier left off cannot have their sales
		 * settled, and nobody discovers it until the drawer will not close.
		 *
		 * Unticking is the exception — somebody off today — and an exception is
		 * the right thing to make people do work for.
		 *
		 * Only eligible ones: a Website User cannot sell, and somebody already on
		 * another open shift would be refused on save.
		 */
		pickedCashiers.value = new Set(
			cashierOptions.value.filter((c) => c.eligible).map((c) => c.user),
		)
	} catch (e) {
		// Not being offered co-cashiers is a smaller problem than a red toast in
		// front of somebody trying to start their day. The shift still opens.
		console.warn('[shift] cashier list failed', e)
		cashierOptions.value = []
		pickedCashiers.value = new Set()
	} finally {
		cashiersBusy.value = false
	}
}

/** What the closed dropdown reads. Names while they fit, a count past that —
 *  "3 selected" is useless when you are checking whether you forgot someone,
 *  and a truncated list of eight is unreadable. */
const cashierSummary = computed(() => {
	const picked = cashierOptions.value.filter((c) => pickedCashiers.value.has(c.user))
	if (!picked.length) return 'Nobody else'
	if (picked.length <= 2) return picked.map((c) => c.label).join(', ')
	return `${picked.length} cashiers`
})

/**
 * One tab per kind of money, which is the only division a cashier can hold in
 * their head. "Money out" used to carry expenses *and* neighbour purchases
 * behind a toggle, so the Expenses tab was never only expenses and the
 * Neighbours tab could not record the payment it was reporting on.
 */
const TABS = [
	{ label: 'Count', value: 'count' },
	{ label: 'Credit', value: 'credit' },
]

/**
 * Expenses and neighbour payments are no longer tabs here — they are their own
 * pages, reached from the till strip. Both are done several times a day
 * mid-shift, and this sheet's main action is "Close shift": recording bus fare
 * should never be one mis-tap from ending a cashier's day.
 *
 * Credit stays because settling a credit sale is money arriving that the
 * closing count has to know about, and the person doing it is already counting.
 * The 'money' and 'neighbours' branches below are unreachable now and come out
 * with the next pass over this file.
 */
const tab = ref('count')

watch(
	() => props.modelValue,
	(isOpen) => {
		if (!isOpen) return
		tab.value = props.initialTab || 'count'
		profile.value = props.profiles[0]?.name || null
		floats.value = Object.fromEntries(modesForProfile().map((m) => [m, '']))
		shortPeople.value = {}
		pickedCashiers.value = new Set()
		resetExpense()
		if (props.mode === 'open') loadCashiers(profile.value)
	},
)

// Re-seeded whenever the summary lands, not only when the sheet opens: recording
// an expense reloads it, and the expected amounts have moved underneath a count
// the cashier has not touched yet.
watch(
	() => props.summary,
	(s) => {
		if (!s) return
		// Pre-fill the count with what is expected. A quiet till then closes in
		// one tap, and anything the cashier edits is a real discrepancy.
		counted.value = Object.fromEntries(
			(s.rows || []).map((r) => [r.mode_of_payment, String(r.expected_amount)]),
		)
	},
	{ immediate: true },
)

/**
 * The tenders the chosen till accepts, falling back to whatever the parent
 * passed. Switching till mid-form has to re-seed the floats: two counters can
 * take different tenders, and leaving the previous till's list on screen
 * collects a float against a mode this one cannot settle.
 */
function modesForProfile() {
	const chosen = props.profiles.find((p) => p.name === profile.value)
	return chosen?.modes?.length ? chosen.modes : props.paymentModes
}

watch(profile, (name) => {
	floats.value = Object.fromEntries(modesForProfile().map((m) => [m, floats.value[m] ?? '']))
	// Two counters can permit different staff, so the roster has to be re-asked
	// for — and anyone already ticked was ticked for the other till.
	pickedCashiers.value = new Set()
	loadCashiers(name)
})

const openingModes = computed(() => modesForProfile())

/** Everyone the shift being closed is settling for, opener included. */
const shiftCashiers = computed(() => props.summary?.shift?.cashiers || [])

const rows = computed(() => props.summary?.rows || [])
const movements = computed(() => props.summary?.movements || null)
const neighbour = computed(() => props.summary?.neighbour || null)

function differenceFor(row) {
	return (Number(counted.value[row.mode_of_payment]) || 0) - row.expected_amount
}

const totalDifference = computed(() => rows.value.reduce((sum, r) => sum + differenceFor(r), 0))

/** Only shortfalls get a name — an overage is not somebody's debt. */
const shortRows = computed(() => rows.value.filter((r) => differenceFor(r) < 0))

function claimsFor(mode) {
	return shortPeople.value[mode] || []
}

function addClaim(mode) {
	shortPeople.value = {
		...shortPeople.value,
		[mode]: [...claimsFor(mode), { person: '', amount: '', account: null }],
	}
}

function removeClaim(mode, index) {
	const next = claimsFor(mode).filter((_, i) => i !== index)
	shortPeople.value = { ...shortPeople.value, [mode]: next }
}

function setClaim(mode, index, patch) {
	const next = claimsFor(mode).map((c, i) => (i === index ? { ...c, ...patch } : c))
	shortPeople.value = { ...shortPeople.value, [mode]: next }
}

/**
 * What is left of a shortfall after the amounts somebody has typed.
 *
 * Shown live and always, because it is the number the cashier is deciding
 * about: anything still unclaimed is written off to the company rather than
 * charged to a person, and that should be a choice rather than a surprise.
 * Names with no amount will share this evenly, so it reads as "and the rest
 * between them".
 */
function unclaimedFor(mode) {
	const shortfall = Math.abs(differenceFor(rows.value.find((r) => r.mode_of_payment === mode) || {}))
	const stated = claimsFor(mode)
		.filter((c) => String(c.amount).trim() !== '')
		.reduce((sum, c) => sum + (Number(c.amount) || 0), 0)
	return Math.round((shortfall - stated) * 100) / 100
}

function sharingFor(mode) {
	return claimsFor(mode).filter((c) => c.person.trim() && String(c.amount).trim() === '').length
}

/** Over-attribution is refused by the server; say so before they submit. */
const shortProblem = computed(() => {
	for (const r of shortRows.value) {
		if (unclaimedFor(r.mode_of_payment) < -0.005) {
			return `More is attributed on ${r.mode_of_payment} than is actually missing`
		}
	}
	return null
})

/* ---------- money out ---------- */

/**
 * What the money-out form is recording, decided by the tab rather than by a
 * toggle inside it. The two live on different tabs now, so a toggle would be a
 * second way to say the same thing — and the one that disagreed with the tab
 * heading would win silently.
 */
const expenseKind = ref('Expense')
const expenseAmount = ref('')
const expenseMode = ref(null)
const expenseAccount = ref(null)
const expenseReason = ref('')
const expensePerson = ref('')
const expenseParty = ref(null)

function resetExpense() {
	expenseKind.value = 'Expense'
	expenseAmount.value = ''
	expenseMode.value = props.options?.modes?.[0] || props.paymentModes[0] || null
	expenseAccount.value = props.options?.default_expense_account || null
	expenseReason.value = ''
	expensePerson.value = ''
	expenseParty.value = props.options?.neighbours?.[0] || null
}

watch(
	() => props.options,
	() => {
		if (!expenseMode.value) expenseMode.value = props.options?.modes?.[0] || null
		if (!expenseAccount.value) expenseAccount.value = props.options?.default_expense_account || null
		if (!expenseParty.value) expenseParty.value = props.options?.neighbours?.[0] || null
	},
)

watch(tab, (t) => {
	if (t === 'money') expenseKind.value = 'Expense'
	if (t === 'neighbours') expenseKind.value = 'Neighbour Purchase'
})

const expenseAmountNum = computed(() => Number(expenseAmount.value) || 0)

/* ---------- movements, split by what they are ---------- */

const NEIGHBOUR_KINDS = ['Neighbour Purchase', 'Neighbour Refund']

const movementRows = computed(() => movements.value?.rows || [])
const expenseMovements = computed(() =>
	movementRows.value.filter((m) => m.movement_type === 'Expense'),
)
const neighbourMovements = computed(() =>
	movementRows.value.filter((m) => NEIGHBOUR_KINDS.includes(m.movement_type)),
)
const creditMovements = computed(() =>
	movementRows.value.filter((m) => m.movement_type === 'Credit Payment'),
)

const expenseTotal = computed(() => movements.value?.expense_total || 0)

/* ---------- credit sales ---------- */

const payAmount = ref({})
const payingFor = ref(null)

function payFull(row) {
	payAmount.value = { ...payAmount.value, [row.name]: row.outstanding }
	submitPayment(row)
}

function submitPayment(row) {
	const raw = payAmount.value[row.name]
	const amount = raw === '' || raw === undefined ? row.outstanding : Number(raw)
	if (!(amount > 0)) return
	payingFor.value = row.name
	emit('pay-credit', { invoice: row.name, amount })
}

watch(
	() => props.creditSales,
	() => {
		payingFor.value = null
		payAmount.value = {}
	},
)

const canRecord = computed(
	() =>
		expenseAmountNum.value > 0 &&
		!!expenseMode.value &&
		(expenseKind.value !== 'Neighbour Purchase' || !!expenseParty.value),
)

function submitMovement() {
	if (!canRecord.value) return
	emit('record-movement', {
		movementType: expenseKind.value,
		amount: expenseAmountNum.value,
		modeOfPayment: expenseMode.value,
		expenseAccount: expenseKind.value === 'Expense' ? expenseAccount.value : null,
		party: expenseKind.value === 'Neighbour Purchase' ? expenseParty.value : null,
		reason: expenseReason.value || null,
		person: expensePerson.value || null,
	})
	expenseAmount.value = ''
	expenseReason.value = ''
	expensePerson.value = ''
}

/* ---------- submit ---------- */

function submitOpen() {
	if (!profile.value) return
	emit('open-shift', {
		posProfile: profile.value,
		balances: openingModes.value.map((m) => ({
			mode_of_payment: m,
			opening_amount: Number(floats.value[m]) || 0,
		})),
		cashiers: [...pickedCashiers.value],
	})
}

function submitClose() {
	emit('close-shift', {
		counted: rows.value.map((r) => ({
			mode_of_payment: r.mode_of_payment,
			closing_amount: Number(counted.value[r.mode_of_payment]) || 0,
		})),
		// Every named claim on every mode that is short. The server drops names
		// against a mode that balanced by the time it closes — so a name left
		// behind by an edited count never becomes a debt — and records whatever
		// nobody claimed as an unattributed short rather than losing it.
		shorts: shortRows.value.flatMap((r) =>
			claimsFor(r.mode_of_payment)
				.filter((c) => c.person.trim())
				.map((c) => ({
					mode_of_payment: r.mode_of_payment,
					person: c.person.trim(),
					amount: String(c.amount).trim() === '' ? null : Number(c.amount),
					// Their own account, when the shop keeps one per person. Left
					// null, it goes to the till's Till Short Account.
					account: c.account || null,
				})),
		),
	})
}

const MOVEMENT_ICONS = {
	Expense: LucideBanknote,
	'Neighbour Purchase': LucideStore,
	'Neighbour Refund': LucideStore,
}

/**
 * Movements that put money back in rather than take it out — cash handed over
 * when goods went back next door. Shown with a sign and a colour because the
 * list is otherwise all one direction, and a refund reading as another payout
 * is the sort of thing a cashier only notices when the count disagrees.
 */
const CASH_IN_TYPES = ['Neighbour Refund', 'Credit Payment']

</script>

<template>
	<BottomSheet
		:model-value="modelValue"
		tall
		@update:model-value="emit('update:modelValue', $event)"
	>
		<!-- ---------- Open ---------- -->
		<div v-if="mode === 'open'" class="flex flex-col gap-2.5 px-4 pb-4 pt-1">
			<div class="flex items-center gap-3">
				<div class="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-surface-amber-2">
					<LucideSunrise class="h-5 w-5 text-ink-amber-3" />
				</div>
				<div>
					<div class="text-p-lg font-semibold text-ink-gray-9">Start shift</div>
					<div class="text-p-sm text-ink-gray-5">Count the drawer before you sell</div>
				</div>
			</div>

			<div v-if="profiles.length > 1">
				<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">Till</label>
				<div class="flex flex-col gap-2">
					<button
						v-for="p in profiles"
						:key="p.name"
						class="min-h-touch rounded-lg border px-3 py-2 text-left text-p-base transition-colors"
						:class="
							profile === p.name
								? 'border-outline-gray-4 bg-surface-gray-3 font-medium text-ink-gray-9'
								: 'border-outline-gray-2 bg-surface-white text-ink-gray-7 hover:bg-surface-gray-2'
						"
						@click="profile = p.name"
					>
						{{ p.name }}
					</button>
				</div>
			</div>

			<!-- Who else is on the counter. Offered on the way in rather than
			     settled at closing time: a cashier who is not on the shift cannot
			     have their sales counted into this drawer, and discovering that
			     while trying to close it is discovering it far too late.

			     A dropdown rather than a row of chips: a shop with a dozen staff
			     turns chips into a wall of names above the float, which is the
			     part of this form somebody actually came to fill in. -->
			<div v-if="profile">
				<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">
					Others on this till
					<span class="font-normal text-ink-gray-5">— optional</span>
				</label>

				<div v-if="cashiersBusy" class="text-p-sm text-ink-gray-5">Loading…</div>

				<!-- Says so rather than disappearing. A section that hides itself when
				     the till permits nobody else is indistinguishable from a feature
				     that is broken, and the fix — add staff to the POS Profile — is
				     not something anybody guesses. -->
				<p
					v-else-if="!cashierOptions.length"
					class="rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 py-2.5 text-p-sm text-ink-gray-5"
				>
					Only you are set up on this till. Add staff under <b>Applicable for Users</b>
					on POS Profile <b>{{ profile }}</b> to share a shift with them.
				</p>

				<div v-else class="relative" @focusout="onCashierBlur">
					<button
						type="button"
						class="flex h-12 w-full items-center justify-between gap-2 rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 text-left text-p-base text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
						@click="cashierMenu = !cashierMenu"
					>
						<span class="truncate" :class="{ 'text-ink-gray-5': !pickedCashiers.size }">
							{{ cashierSummary }}
						</span>
						<LucideChevronDown class="h-4 w-4 shrink-0 text-ink-gray-5" />
					</button>

					<!-- Capped and scrollable: the sheet itself scrolls, and a list
					     long enough to push the Open button off screen would make the
					     form look broken at exactly the wrong moment. -->
					<div
						v-if="cashierMenu"
						class="absolute z-10 mt-1 max-h-56 w-full overflow-y-auto rounded-xl border border-outline-gray-2 bg-surface-white py-1 shadow-lg"
					>
						<!-- Accounts that cannot sell are listed too, disabled, with the
						     reason. Filtering them out is what made somebody add a user
						     to the till and then not find them here. -->
						<button
							v-for="c in cashierOptions"
							:key="c.user"
							type="button"
							:disabled="!c.eligible"
							class="flex min-h-touch w-full items-center gap-2 px-3 py-2 text-left text-p-base disabled:cursor-not-allowed enabled:hover:bg-surface-gray-2"
							:class="
								!c.eligible
									? 'text-ink-gray-4'
									: pickedCashiers.has(c.user)
										? 'font-medium text-ink-gray-9'
										: 'text-ink-gray-7'
							"
							@click="toggleCashier(c.user)"
						>
							<span
								class="grid h-4 w-4 shrink-0 place-items-center rounded border"
								:class="
									!c.eligible
										? 'border-outline-gray-2 bg-surface-gray-2'
										: pickedCashiers.has(c.user)
											? 'border-outline-gray-4 bg-surface-gray-7'
											: 'border-outline-gray-3'
								"
							>
								<LucideCheck v-if="pickedCashiers.has(c.user)" class="h-3 w-3 text-ink-white" />
							</span>
							<span class="min-w-0 flex-1">
								<span class="block truncate">{{ c.label }}</span>
								<span v-if="!c.eligible" class="block truncate text-p-sm text-ink-gray-4">
									{{ c.reason }}
								</span>
							</span>
						</button>
					</div>
				</div>

				<p class="mt-1.5 text-p-sm text-ink-gray-5">
					Their sales settle on this shift. You are on it already.
				</p>
			</div>

			<div class="flex flex-col gap-2">
				<label class="text-p-sm font-medium text-ink-gray-7">Opening float</label>
				<div v-for="m in openingModes" :key="m" class="flex items-center gap-3">
					<span class="w-24 shrink-0 text-p-base text-ink-gray-7">{{ m }}</span>
					<input
						v-model="floats[m]"
						type="number"
						inputmode="decimal"
						placeholder="0"
						class="tabular h-11 min-w-0 flex-1 rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-lg font-semibold text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none focus:ring-2 focus:ring-outline-gray-3"
						@focus="$event.target.select()"
					/>
				</div>
			</div>

			<button
				class="min-h-touch w-full rounded-xl bg-surface-gray-7 py-3 text-p-lg font-semibold text-ink-white transition-all active:scale-[0.98] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
				:disabled="!profile || busy"
				@click="submitOpen"
			>
				{{ busy ? 'Opening…' : 'Open shift' }}
			</button>

		</div>

		<!-- ---------- Close ---------- -->
		<div v-else class="flex flex-col gap-2.5 px-4 pb-4 pt-1">
			<div class="flex items-center gap-3">
				<div class="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-surface-gray-3">
					<LucideSunset class="h-5 w-5 text-ink-gray-7" />
				</div>
				<div class="min-w-0 flex-1">
					<div class="text-p-lg font-semibold text-ink-gray-9">Shift</div>
					<div class="text-p-sm text-ink-gray-5">
						{{ summary?.invoice_count || 0 }} sales ·
						{{ fmtMoneyShort(summary?.grand_total || 0) }}
						<!-- Named, not counted. Closing a drawer for two people is a
						     different act from closing your own, and the money on the
						     counter belongs to whoever is listed here. -->
						<template v-if="shiftCashiers.length > 1">
							· {{ shiftCashiers.length }} cashiers
						</template>
					</div>
					<div v-if="shiftCashiers.length > 1" class="truncate text-p-sm text-ink-gray-5">
						{{ shiftCashiers.join(', ') }}
					</div>
				</div>
			</div>

			<!-- Three things move money at a till; this is which one you are
			     looking at. Counts on the tabs so nothing needs opening to be
			     noticed. -->
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
					<span
						v-if="t.value === 'money' && movements?.count"
						class="tabular ml-1 text-ink-gray-5"
						>{{ movements.count }}</span
					>
					<span
						v-else-if="t.value === 'neighbours' && neighbour?.count"
						class="tabular ml-1 text-ink-gray-5"
						>{{ neighbour.count }}</span
					>
				</button>
			</div>

			<!-- ---------- Count ---------- -->
			<template v-if="tab === 'count'">
				<div class="flex flex-col gap-2">
					<div
						v-for="r in rows"
						:key="r.mode_of_payment"
						class="rounded-xl border border-outline-gray-2 p-2.5"
					>
						<div class="flex items-baseline justify-between gap-2">
							<span class="text-p-base font-medium text-ink-gray-8">
								{{ r.mode_of_payment }}
							</span>
							<span class="tabular text-p-xs text-ink-gray-5">
								float {{ fmtMoneyShort(r.opening_amount) }} + sales
								{{ fmtMoneyShort(r.taken) }}
								<!-- Spelled out rather than folded into "expected": a cashier
								     asked to produce less than the sales say is owed the
								     reason on the same line. -->
								<template v-if="r.paid_out">
									− out {{ fmtMoneyShort(r.paid_out) }}
								</template>
							</span>
						</div>
						<div class="mt-1.5 flex items-center gap-3">
							<div class="min-w-0 flex-1">
								<div class="text-p-xs text-ink-gray-5">Expected</div>
								<div class="tabular text-p-lg font-semibold text-ink-gray-9">
									{{ fmtMoneyShort(r.expected_amount) }}
								</div>
							</div>
							<div class="min-w-0 flex-1">
								<div class="mb-0.5 text-p-xs text-ink-gray-5">Counted</div>
								<input
									v-model="counted[r.mode_of_payment]"
									type="number"
									inputmode="decimal"
									class="tabular h-10 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base font-semibold text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none focus:ring-2 focus:ring-outline-gray-3"
									@focus="$event.target.select()"
								/>
							</div>
						</div>

						<!-- Appears only once this mode is actually short. A name box on
						     a balanced till is an accusation looking for somebody. -->
						<div v-if="differenceFor(r) < 0" class="mt-3 border-t border-outline-gray-2 pt-3">
							<label class="mb-1.5 block text-p-xs font-medium text-ink-red-3">
								Short {{ fmtMoney(Math.abs(differenceFor(r))) }} — who is it against?
							</label>

							<div
								v-for="(c, i) in claimsFor(r.mode_of_payment)"
								:key="i"
								class="mb-2 flex items-center gap-2"
							>
								<input
									:value="c.person"
									type="text"
									placeholder="Name"
									class="h-11 min-w-0 flex-1 rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
									@input="setClaim(r.mode_of_payment, i, { person: $event.target.value })"
								/>
								<!-- Blank means "share what is left". Most shortfalls are not
								     divided by anyone knowing whose they were. -->
								<input
									:value="c.amount"
									type="number"
									inputmode="decimal"
									placeholder="Share"
									class="tabular h-11 w-24 rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base font-semibold text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
									@input="setClaim(r.mode_of_payment, i, { amount: $event.target.value })"
									@focus="$event.target.select()"
								/>
								<!-- Their account, when the shop keeps one per person. Left as
								     "the till's account", every named short goes to the one on
								     the POS Profile, which is right for a shop with a single
								     "owed by staff" account. -->
								<select
									:value="c.account"
									class="h-11 w-[150px] shrink-0 rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-2 text-p-xs text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
									:aria-label="`Account for ${c.person || 'this person'}`"
									@change="setClaim(r.mode_of_payment, i, { account: $event.target.value || null })"
								>
									<option :value="''">The till's account</option>
									<option v-for="a in options?.accounts || []" :key="a.name" :value="a.name">
										{{ a.label }}
									</option>
								</select>
								<button
									class="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-ink-gray-5 hover:bg-surface-red-2 hover:text-ink-red-3"
									aria-label="Remove this name"
									@click="removeClaim(r.mode_of_payment, i)"
								>
									<LucideX class="h-4 w-4" />
								</button>
							</div>

							<button
								class="flex min-h-touch w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-outline-gray-3 py-2 text-p-sm font-medium text-ink-gray-6 hover:bg-surface-gray-2"
								@click="addClaim(r.mode_of_payment)"
							>
								<LucidePlus class="h-4 w-4" />
								{{ claimsFor(r.mode_of_payment).length ? 'Another person' : 'Name someone' }}
							</button>

							<!-- The remainder, always visible. It is the number being
							     decided about: anything unclaimed is written off to the
							     company rather than charged to anybody, and that should be a
							     choice rather than something noticed at month end. -->
							<p
								v-if="unclaimedFor(r.mode_of_payment) > 0.005"
								class="mt-2 text-p-xs"
								:class="sharingFor(r.mode_of_payment) ? 'text-ink-gray-6' : 'text-ink-amber-3'"
							>
								<template v-if="sharingFor(r.mode_of_payment)">
									{{ fmtMoney(unclaimedFor(r.mode_of_payment)) }} split evenly between
									{{ sharingFor(r.mode_of_payment) }}
									{{ sharingFor(r.mode_of_payment) === 1 ? 'person' : 'people' }}
								</template>
								<template v-else>
									{{ fmtMoney(unclaimedFor(r.mode_of_payment)) }} nobody is named for —
									written off to the shop
								</template>
							</p>
							<p
								v-else-if="unclaimedFor(r.mode_of_payment) < -0.005"
								class="mt-2 text-p-xs font-medium text-ink-red-3"
							>
								That is {{ fmtMoney(Math.abs(unclaimedFor(r.mode_of_payment))) }} more than
								is missing
							</p>
						</div>
					</div>
				</div>

				<!-- Credit sales never hit the drawer, so they are called out rather
				     than silently missing from the numbers above. -->
				<div
					v-if="summary?.credit?.count"
					class="rounded-xl bg-surface-amber-2 px-4 py-3 text-p-sm"
				>
					<div class="font-medium text-ink-amber-3">
						{{ summary.credit.count }} credit
						{{ summary.credit.count === 1 ? 'sale' : 'sales' }} this shift
					</div>
					<div class="tabular mt-0.5 text-ink-gray-7">
						{{ fmtMoney(summary.credit.outstanding) }} still owed · not counted in the
						drawer
					</div>
				</div>

				<!-- Same treatment for money that left the drawer: already subtracted
				     above, so it is stated rather than left as an unexplained gap. -->
				<button
					v-if="movements?.paid_out_total"
					class="rounded-xl bg-surface-blue-2 px-4 py-3 text-left text-p-sm"
					@click="tab = 'money'"
				>
					<div class="font-medium text-ink-blue-3">
						{{ fmtMoney(movements.paid_out_total) }} paid out this shift
					</div>
					<div class="tabular mt-0.5 text-ink-gray-7">
						Already taken off what you are counting against — tap to see it
					</div>
				</button>

				<div
					class="flex items-center justify-between rounded-xl px-4 py-2.5"
					:class="
						totalDifference === 0
							? 'bg-surface-green-2'
							: totalDifference > 0
								? 'bg-surface-blue-2'
								: 'bg-surface-red-2'
					"
				>
					<span
						class="text-p-base font-medium"
						:class="
							totalDifference === 0
								? 'text-ink-green-3'
								: totalDifference > 0
									? 'text-ink-blue-3'
									: 'text-ink-red-3'
						"
					>
						{{
							totalDifference === 0
								? 'Balanced'
								: totalDifference > 0
									? 'Over'
									: 'Short'
						}}
					</span>
					<span
						class="tabular text-2xl font-semibold"
						:class="
							totalDifference === 0
								? 'text-ink-green-3'
								: totalDifference > 0
									? 'text-ink-blue-3'
									: 'text-ink-red-3'
						"
					>
						{{ fmtMoney(Math.abs(totalDifference)) }}
					</span>
				</div>

				<button
					class="flex min-h-touch w-full items-center justify-center gap-2 rounded-xl bg-surface-gray-7 py-3 text-p-lg font-semibold text-ink-white transition-all active:scale-[0.98] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
					:disabled="busy || !!shortProblem"
					@click="submitClose"
				>
					<LucideCheck class="h-5 w-5" />
					{{ busy ? 'Closing…' : shortProblem || 'Close shift' }}
				</button>
			</template>

			<!-- ---------- Money out ---------- -->
			<template v-else-if="tab === 'money'">
				<div class="rounded-xl border border-outline-gray-2 p-2.5">
					<div class="grid grid-cols-2 gap-3">
						<div>
							<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">
								Amount
							</label>
							<input
								v-model="expenseAmount"
								type="number"
								inputmode="decimal"
								placeholder="0"
								class="tabular h-12 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-lg font-semibold text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
								@focus="$event.target.select()"
							/>
						</div>
						<div>
							<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">
								Out of
							</label>
							<select
								v-model="expenseMode"
								class="h-12 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
							>
								<option v-for="m in options?.modes || paymentModes" :key="m" :value="m">
									{{ m }}
								</option>
							</select>
						</div>
					</div>

					<div class="mt-3">
						<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">
							Booked to
						</label>
						<select
							v-model="expenseAccount"
							class="h-12 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
						>
							<option :value="null">Default expense account</option>
							<option v-for="a in options?.accounts || []" :key="a.name" :value="a.name">
								{{ a.label }}
							</option>
						</select>
					</div>


					<div class="mt-3 grid grid-cols-2 gap-3">
						<div>
							<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">
								What for
							</label>
							<input
								v-model="expenseReason"
								type="text"
								placeholder="Transport, lunch…"
								class="h-12 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
							/>
						</div>
						<div>
							<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">
								Who took it
							</label>
							<input
								v-model="expensePerson"
								type="text"
								placeholder="Name (optional)"
								class="h-12 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
							/>
						</div>
					</div>

					<button
						class="mt-3 flex min-h-touch w-full items-center justify-center gap-2 rounded-xl bg-surface-gray-7 py-3.5 text-p-base font-semibold text-ink-white transition-all active:scale-[0.98] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
						:disabled="!canRecord || movementBusy"
						@click="submitMovement"
					>
						<LucidePlus class="h-4 w-4" />
						{{ movementBusy ? 'Recording…' : `Take ${fmtMoney(expenseAmountNum)} out` }}
					</button>

					<p class="mt-2 text-p-xs text-ink-gray-5">
						An expense posts a journal entry against the drawer, so the ledger and the
						count agree. Paying a neighbour only records the cash — the purchase itself
						is already on their invoice.
					</p>
				</div>

				<div v-if="expenseMovements.length" class="flex flex-col gap-2">
					<div class="flex items-baseline justify-between">
						<span class="text-p-sm font-medium text-ink-gray-7">Expenses this shift</span>
						<span class="tabular text-p-sm font-semibold text-ink-gray-9">
							{{ fmtMoney(expenseTotal) }} out
						</span>
					</div>
					<!-- Expenses only. Neighbour purchases and refunds are money out of
					     the same drawer, but they belong to a trade with a named shop and
					     are read on their own tab; mixing them here made "what did we
					     spend today" unanswerable from the screen that asks it. -->
					<div
						v-for="m in expenseMovements"
						:key="m.name"
						class="flex items-center gap-3 rounded-xl border border-outline-gray-2 px-3 py-2.5"
					>
						<component
							:is="MOVEMENT_ICONS[m.movement_type] || LucideBanknote"
							class="h-4 w-4 shrink-0 text-ink-gray-5"
						/>
						<div class="min-w-0 flex-1">
							<div class="truncate text-p-sm font-medium text-ink-gray-8">
								{{ m.reason || m.movement_type }}
							</div>
							<div class="truncate text-p-xs text-ink-gray-5">
								{{ m.mode_of_payment }}
								<template v-if="m.person"> · {{ m.person }}</template>
								<template v-if="m.party"> · {{ m.party }}</template>
							</div>
						</div>
						<span
							class="tabular shrink-0 text-p-base font-semibold"
							:class="
								m.movement_type === 'Short'
									? 'text-ink-red-3'
									: CASH_IN_TYPES.includes(m.movement_type)
										? 'text-ink-green-3'
										: 'text-ink-gray-9'
							"
						>
							{{ CASH_IN_TYPES.includes(m.movement_type) ? '+' : '' }}{{ fmtMoney(m.amount) }}
						</span>
						<!-- Voidable only while the shift is open, and never a short: a
						     short is attributed at closing, against a counted figure. -->
						<button
							v-if="m.movement_type !== 'Short'"
							class="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-ink-gray-5 hover:bg-surface-red-2 hover:text-ink-red-3"
							:aria-label="`Void ${m.name}`"
							@click="emit('void-movement', m)"
						>
							<LucideX class="h-4 w-4" />
						</button>
					</div>
				</div>
				<p v-else class="px-1 text-p-sm text-ink-gray-5">
					No expenses have been taken out of the drawer this shift.
				</p>
			</template>

			<!-- ---------- Neighbours ---------- -->
			<template v-else-if="tab === 'neighbours'">
				<!-- Recording the payment sits with the trade it belongs to. It used
				     to be a toggle on the expenses tab, one screen away from the list
				     of what was owed — so the cashier read the debt in one place and
				     settled it in another. -->
				<div class="rounded-xl border border-outline-gray-2 p-2.5">
					<div class="grid grid-cols-2 gap-3">
						<div>
							<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">Amount</label>
							<input
								v-model="expenseAmount"
								type="number"
								inputmode="decimal"
								placeholder="0"
								class="tabular h-12 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-lg font-semibold text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
								@focus="$event.target.select()"
							/>
						</div>
						<div>
							<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">Out of</label>
							<select
								v-model="expenseMode"
								class="h-12 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
							>
								<option v-for="m in options?.modes || paymentModes" :key="m" :value="m">
									{{ m }}
								</option>
							</select>
						</div>
					</div>

					<div class="mt-3">
						<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">Which shop</label>
						<select
							v-model="expenseParty"
							class="h-12 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
						>
							<option v-for="n in options?.neighbours || []" :key="n" :value="n">{{ n }}</option>
						</select>
					</div>

					<button
						class="mt-3 flex min-h-touch w-full items-center justify-center gap-2 rounded-xl bg-surface-gray-7 py-3.5 text-p-base font-semibold text-ink-white transition-all active:scale-[0.98] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
						:disabled="!canRecord || movementBusy"
						@click="submitMovement"
					>
						<LucidePlus class="h-4 w-4" />
						{{ movementBusy ? 'Recording…' : `Pay ${fmtMoney(expenseAmountNum)} next door` }}
					</button>

					<p class="mt-2 text-p-xs text-ink-gray-5">
						This records the cash leaving the drawer. The purchase itself is
						already on their invoice — nothing is posted twice.
					</p>
				</div>

				<!-- Every neighbour movement this shift, both directions. -->
				<div v-if="neighbourMovements.length" class="flex flex-col gap-2">
					<span class="text-p-sm font-medium text-ink-gray-7">Paid and refunded</span>
					<div
						v-for="m in neighbourMovements"
						:key="m.name"
						class="flex items-center gap-3 rounded-xl border border-outline-gray-2 px-3 py-2.5"
					>
						<LucideStore class="h-4 w-4 shrink-0 text-ink-gray-5" />
						<div class="min-w-0 flex-1">
							<div class="truncate text-p-sm font-medium text-ink-gray-8">
								{{ m.reason || m.movement_type }}
							</div>
							<div class="truncate text-p-xs text-ink-gray-5">
								{{ m.mode_of_payment }}<template v-if="m.party"> · {{ m.party }}</template>
							</div>
						</div>
						<span
							class="tabular shrink-0 text-p-base font-semibold"
							:class="
								CASH_IN_TYPES.includes(m.movement_type) ? 'text-ink-green-3' : 'text-ink-gray-9'
							"
						>
							{{ CASH_IN_TYPES.includes(m.movement_type) ? '+' : '−' }}{{ fmtMoney(m.amount) }}
						</span>
						<button
							class="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-ink-gray-5 hover:bg-surface-red-2 hover:text-ink-red-3"
							:aria-label="`Void ${m.name}`"
							@click="emit('void-movement', m)"
						>
							<LucideX class="h-4 w-4" />
						</button>
					</div>
				</div>

				<div v-if="neighbour?.count" class="flex flex-col gap-3">
					<div class="grid grid-cols-2 gap-3">
						<div class="rounded-xl bg-surface-amber-2 px-3 py-2.5">
							<div class="text-p-xs font-medium text-ink-amber-3">Still owed</div>
							<div class="tabular text-p-lg font-semibold text-ink-gray-9">
								{{ fmtMoney(neighbour.unpaid) }}
							</div>
							<div class="text-p-xs text-ink-gray-6">
								{{ neighbour.unpaid_count }} of {{ neighbour.count }} invoices
							</div>
						</div>
						<div class="rounded-xl bg-surface-gray-2 px-3 py-2.5">
							<div class="text-p-xs font-medium text-ink-gray-6">Paid at the till</div>
							<div class="tabular text-p-lg font-semibold text-ink-gray-9">
								{{ fmtMoney(neighbour.paid) }}
							</div>
							<div class="text-p-xs text-ink-gray-6">Off the expected count</div>
						</div>
					</div>

					<div
						v-for="inv in neighbour.invoices"
						:key="inv.name"
						class="flex items-center gap-3 rounded-xl border border-outline-gray-2 px-3 py-2.5"
					>
						<LucideStore class="h-4 w-4 shrink-0 text-ink-gray-5" />
						<div class="min-w-0 flex-1">
							<div class="truncate text-p-sm font-medium text-ink-gray-8">
								{{ inv.supplier }}
							</div>
							<div class="truncate text-p-xs text-ink-gray-5">{{ inv.name }}</div>
						</div>
						<div class="shrink-0 text-right">
							<div class="tabular text-p-base font-semibold text-ink-gray-9">
								{{ fmtMoney(inv.total) }}
							</div>
							<div
								class="tabular text-p-xs"
								:class="inv.outstanding > 0 ? 'text-ink-amber-3' : 'text-ink-green-3'"
							>
								{{ inv.outstanding > 0 ? `${fmtMoney(inv.outstanding)} owed` : 'Paid' }}
							</div>
						</div>
					</div>

					<p class="px-1 text-p-xs text-ink-gray-5">
						An unpaid purchase is a debt this counter opened. It is not taken off the
						drawer — nothing left it — but somebody has to settle it.
					</p>
				</div>
				<p v-else class="px-1 text-p-sm text-ink-gray-5">
					Nothing was sourced from a neighbour this shift.
				</p>
			</template>

			<!-- ---------- Credit sales ---------- -->
			<template v-else-if="tab === 'credit'">
				<div class="grid grid-cols-2 gap-3">
					<div class="rounded-xl bg-surface-amber-2 px-3 py-2.5">
						<div class="text-p-xs font-medium text-ink-amber-3">Still owed</div>
						<div class="tabular text-p-lg font-semibold text-ink-gray-9">
							{{ fmtMoney(creditSales?.totals?.outstanding || 0) }}
						</div>
						<div class="text-p-xs text-ink-gray-6">
							{{ creditSales?.totals?.count || 0 }} sales ·
							{{ creditSales?.totals?.customers || 0 }} customers
						</div>
					</div>
					<div class="rounded-xl bg-surface-gray-2 px-3 py-2.5">
						<div class="text-p-xs font-medium text-ink-gray-6">Taken this shift</div>
						<div class="tabular text-p-lg font-semibold text-ink-green-3">
							{{ fmtMoney(movements?.credit_payment_total || 0) }}
						</div>
						<div class="text-p-xs text-ink-gray-6">Counted in the drawer</div>
					</div>
				</div>

				<p v-if="creditSales?.reason" class="px-1 text-p-sm text-ink-gray-5">
					{{ creditSales.reason }}
				</p>

				<p v-else-if="!creditSales?.rows?.length" class="px-1 text-p-sm text-ink-gray-5">
					Nothing is owed. Every sale has been paid for.
				</p>

				<!-- Overdue first is deliberate: the list is long on a shop that sells
				     on account, and the ones worth chasing are the ones that are late,
				     not the ones that are biggest. -->
				<div
					v-for="c in creditSales?.rows || []"
					:key="c.name"
					class="rounded-xl border px-3 py-2.5"
					:class="c.overdue ? 'border-outline-red-2 bg-surface-red-1' : 'border-outline-gray-2'"
				>
					<div class="flex items-baseline justify-between gap-2">
						<span class="min-w-0 truncate text-p-base font-medium text-ink-gray-9">
							{{ c.customer_name }}
						</span>
						<span class="tabular shrink-0 text-p-base font-semibold text-ink-amber-3">
							{{ fmtMoney(c.outstanding) }}
						</span>
					</div>
					<div class="mt-0.5 truncate text-p-xs text-ink-gray-5">
						{{ c.name }} · {{ c.date }}
						<template v-if="c.paid"> · {{ fmtMoney(c.paid) }} already paid</template>
						<span v-if="c.overdue" class="font-medium text-ink-red-3">
							· due {{ c.due_date }}
						</span>
					</div>
					<div class="mt-2 flex items-center gap-2">
						<input
							:value="payAmount[c.name] ?? ''"
							type="number"
							inputmode="decimal"
							:placeholder="String(c.outstanding)"
							class="tabular h-11 w-28 rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base font-semibold text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
							:aria-label="`Amount paid against ${c.name}`"
							@input="payAmount = { ...payAmount, [c.name]: $event.target.value }"
							@focus="$event.target.select()"
						/>
						<button
							class="min-h-touch rounded-lg border border-outline-gray-2 px-3 text-p-sm font-medium text-ink-gray-7 hover:bg-surface-gray-2 disabled:opacity-40"
							:disabled="creditBusy"
							@click="submitPayment(c)"
						>
							Take part
						</button>
						<button
							class="ml-auto min-h-touch rounded-lg bg-surface-gray-7 px-4 text-p-sm font-semibold text-ink-white transition-all active:scale-[0.98] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
							:disabled="creditBusy"
							@click="payFull(c)"
						>
							{{ creditBusy && payingFor === c.name ? 'Taking…' : `Settle ${fmtMoneyShort(c.outstanding)}` }}
						</button>
					</div>
				</div>

				<p class="px-1 text-p-xs text-ink-gray-5">
					A payment here posts against the invoice and adds the cash to what this
					shift is expected to hold, so the close still balances.
				</p>
			</template>

		</div>
	</BottomSheet>
</template>
