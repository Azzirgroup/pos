<script setup>
import { ref, computed, onMounted } from 'vue'
import { Button } from 'frappe-ui'
import { fmtMoney } from '@/utils/format'
import {
	getMovementOptions,
	listMovements,
	recordMovement,
	voidMovement,
	getOpenShift,
} from '@/data/api'
import PageHeader from '@/components/PageHeader.vue'
import StatTiles from '@/components/StatTiles.vue'
import LucidePlus from '~icons/lucide/plus'
import LucideX from '~icons/lucide/x'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideBanknote from '~icons/lucide/banknote'

/**
 * Money out of the drawer that is not a purchase — transport, lunch, a repair.
 *
 * Its own page rather than a tab inside the closing sheet. Recording an expense
 * happens mid-shift, several times a day, and it had to be done on a screen
 * whose main action was "Close shift" — one mis-tap from ending the shift of a
 * cashier who only wanted to write down 200 shillings of matatu fare.
 *
 * Expenses only. Paying a neighbouring shop is also cash out of the same
 * drawer, but it belongs to a trade with a named supplier and has its own page;
 * mixing the two made "what did we spend today" unanswerable from the screen
 * that asks it.
 */
const options = ref(null)
const movements = ref(null)
const shift = ref(null)
const loading = ref(false)
const busy = ref(false)

const amount = ref('')
const mode = ref(null)
const account = ref(null)
const reason = ref('')
const person = ref('')

const amountNum = computed(() => Number(amount.value) || 0)
const canRecord = computed(() => amountNum.value > 0 && !!mode.value && !busy.value)

/** Only expenses. The endpoint returns every movement on the shift. */
const rows = computed(() =>
	(movements.value?.rows || []).filter((m) => m.movement_type === 'Expense'),
)

const stats = computed(() => [
	{
		label: 'Spent this shift',
		value: movements.value?.expense_total || 0,
		type: 'currency',
		icon: 'wallet',
		tone: movements.value?.expense_total ? 'warn' : 'default',
	},
	{ label: 'Expenses', value: rows.value.length, type: 'number', icon: 'receipt' },
])

onMounted(load)

async function load() {
	loading.value = true
	try {
		const [s, o, m] = await Promise.all([
			getOpenShift(),
			getMovementOptions(),
			listMovements({}),
		])
		shift.value = s
		options.value = o
		movements.value = m
		if (!mode.value) mode.value = o?.modes?.[0] || null
		if (!account.value) account.value = o?.default_expense_account || null
	} catch (e) {
		notify(e.message || 'Could not load this shift', 'bad')
	} finally {
		loading.value = false
	}
}

async function submit() {
	if (!canRecord.value) return
	busy.value = true
	try {
		const res = await recordMovement({
			movementType: 'Expense',
			amount: amountNum.value,
			modeOfPayment: mode.value,
			expenseAccount: account.value,
			reason: reason.value || null,
			person: person.value || null,
		})
		amount.value = ''
		reason.value = ''
		person.value = ''
		await load()
		notify(`${fmtMoney(res.amount)} out of ${res.mode_of_payment}`, 'good')
	} catch (e) {
		notify(e.message || 'Could not record that', 'bad')
	} finally {
		busy.value = false
	}
}

async function voidOne(m) {
	busy.value = true
	try {
		await voidMovement({ name: m.name })
		await load()
		notify(`${fmtMoney(m.amount)} put back`, 'good')
	} catch (e) {
		notify(e.message || 'Could not undo that', 'bad')
	} finally {
		busy.value = false
	}
}

const toast = ref(null)
let toastTimer = null
function notify(message, tone = 'good') {
	toast.value = { message, tone }
	clearTimeout(toastTimer)
	toastTimer = setTimeout(() => (toast.value = null), 2800)
}
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col overflow-hidden">
		<PageHeader title="Expenses" subtitle="Money out of the drawer that is not a purchase">
			<template #actions>
				<Button variant="subtle" :icon-left="LucideRefreshCw" :loading="loading" @click="load" />
			</template>
		</PageHeader>

		<!-- An expense belongs to a shift: it changes what the drawer should hold,
		     so one recorded outside a shift is accounting nobody ever counts. -->
		<p
			v-if="!loading && !shift"
			class="shrink-0 bg-surface-amber-1 px-4 py-2 text-p-sm text-ink-amber-3"
		>
			No shift is open. Open one at the till before taking money out of the drawer.
		</p>

		<StatTiles :stats="stats" />

		<div class="min-h-0 flex-1 overflow-auto px-4 pb-6">
			<div class="mx-auto flex w-full max-w-2xl flex-col gap-4">
				<div class="rounded-xl border border-outline-gray-2 bg-surface-white p-4">
					<div class="grid gap-3 sm:grid-cols-2">
						<div>
							<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">Amount</label>
							<input
								v-model="amount"
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
								v-model="mode"
								class="h-12 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
							>
								<option v-for="m in options?.modes || []" :key="m" :value="m">{{ m }}</option>
							</select>
						</div>
					</div>

					<div class="mt-3">
						<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">Booked to</label>
						<select
							v-model="account"
							class="h-12 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
						>
							<option :value="null">Default expense account</option>
							<option v-for="a in options?.accounts || []" :key="a.name" :value="a.name">
								{{ a.label }}
							</option>
						</select>
					</div>

					<div class="mt-3 grid gap-3 sm:grid-cols-2">
						<div>
							<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">What for</label>
							<input
								v-model="reason"
								type="text"
								placeholder="Transport, lunch…"
								class="h-12 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
							/>
						</div>
						<div>
							<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">Who took it</label>
							<input
								v-model="person"
								type="text"
								placeholder="Name (optional)"
								class="h-12 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
							/>
						</div>
					</div>

					<button
						class="mt-4 flex min-h-touch w-full items-center justify-center gap-2 rounded-xl bg-surface-gray-7 py-3.5 text-p-base font-semibold text-ink-white transition-all active:scale-[0.98] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
						:disabled="!canRecord || !shift"
						@click="submit"
					>
						<LucidePlus class="h-4 w-4" />
						{{ busy ? 'Recording…' : `Take ${fmtMoney(amountNum)} out` }}
					</button>

					<p class="mt-2 text-p-xs text-ink-gray-5">
						An expense posts a journal entry against the drawer, so the ledger and the
						count agree at closing.
					</p>
				</div>

				<div v-if="rows.length" class="flex flex-col gap-2">
					<div class="flex items-baseline justify-between px-1">
						<span class="text-p-sm font-medium text-ink-gray-7">This shift</span>
						<span class="tabular text-p-sm font-semibold text-ink-gray-9">
							{{ fmtMoney(movements?.expense_total || 0) }} out
						</span>
					</div>
					<div
						v-for="m in rows"
						:key="m.name"
						class="flex items-center gap-3 rounded-xl border border-outline-gray-2 bg-surface-white px-3 py-2.5"
					>
						<LucideBanknote class="h-4 w-4 shrink-0 text-ink-gray-5" />
						<div class="min-w-0 flex-1">
							<div class="truncate text-p-sm font-medium text-ink-gray-8">
								{{ m.reason || 'Expense' }}
							</div>
							<div class="truncate text-p-xs text-ink-gray-5">
								{{ m.mode_of_payment }}
								<template v-if="m.person"> · {{ m.person }}</template>
							</div>
						</div>
						<span class="tabular shrink-0 text-p-base font-semibold text-ink-gray-9">
							{{ fmtMoney(m.amount) }}
						</span>
						<button
							class="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-ink-gray-5 hover:bg-surface-red-2 hover:text-ink-red-3"
							:aria-label="`Void ${m.name}`"
							@click="voidOne(m)"
						>
							<LucideX class="h-4 w-4" />
						</button>
					</div>
				</div>
				<p v-else-if="!loading" class="px-1 text-p-sm text-ink-gray-5">
					Nothing has come out of the drawer this shift.
				</p>
			</div>
		</div>

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
