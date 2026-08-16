<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Button } from 'frappe-ui'
import { fmtMoney } from '@/utils/format'
import {
	listCreditCustomers,
	getCustomerCredit,
	payCustomer,
	payCreditSale,
	getPaymentMethods,
} from '@/data/api'
import PageHeader from '@/components/PageHeader.vue'
import StatTiles from '@/components/StatTiles.vue'
import BottomSheet from '@/components/BottomSheet.vue'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideSearch from '~icons/lucide/search'
import LucideWallet from '~icons/lucide/wallet'
import LucidePhone from '~icons/lucide/phone'

/**
 * What the shop is owed, and taking it when the customer walks back in.
 *
 * ## Why this is a screen and not a tab in the closing sheet
 *
 * It was one. Receivables lived inside the sheet whose primary action is "Close
 * shift", which meant a cashier taking a payment mid-morning was one mis-tap
 * from ending the day — the same mistake that moved Expenses out to its own
 * page. The shop asked for it on the top strip, and that is the right place: a
 * customer settling a debt is an ordinary counter transaction, not part of
 * banking the drawer.
 *
 * ## Why the list is customers and not invoices
 *
 * A customer walks in and says "I've come to pay". They do not know which
 * invoice they mean, and neither does the cashier. Leading with invoices makes
 * that a guessing game whose wrong answers scatter one customer's payments
 * across documents in no order, and the ageing report becomes fiction.
 *
 * So a row is a person and a balance, and the money lands on their oldest
 * invoice first — automatically, on the server, in one Payment Entry. The
 * invoices are still there, one tap down, for the customer who *does* know
 * which one they mean.
 */
const data = ref(null)
const loading = ref(false)
const search = ref('')
const methods = ref([])

const rows = computed(() => {
	const all = data.value?.rows || []
	const term = search.value.trim().toLowerCase()
	if (!term) return all
	// Filtered here rather than on the server: the whole list is already loaded
	// (a shop selling on account has tens of debtors, not thousands) and a round
	// trip per keystroke would be slower than the filter it replaces.
	return all.filter(
		(r) =>
			(r.customer_name || '').toLowerCase().includes(term) ||
			(r.customer || '').toLowerCase().includes(term) ||
			(r.phone || '').includes(term),
	)
})

const stats = computed(() => {
	const t = data.value?.totals || {}
	return [
		{
			label: 'Owed to the shop',
			value: t.outstanding || 0,
			type: 'currency',
			icon: 'wallet',
			tone: t.outstanding ? 'warn' : 'default',
		},
		{
			label: 'Overdue',
			value: t.overdue || 0,
			type: 'currency',
			icon: 'alert',
			tone: t.overdue ? 'bad' : 'default',
		},
		{ label: 'Customers', value: t.customers || 0, type: 'number', icon: 'users' },
		{ label: 'Unpaid sales', value: t.invoices || 0, type: 'number', icon: 'receipt' },
	]
})

onMounted(async () => {
	await load()
	try {
		const res = await getPaymentMethods()
		methods.value = res?.methods || []
	} catch {
		// The payment still works on the shop's default cash mode; only the
		// picker degrades.
		methods.value = []
	}
})

async function load() {
	loading.value = true
	try {
		data.value = await listCreditCustomers({})
	} catch (e) {
		notify(e.message || 'Could not load what is owed', 'bad')
		data.value = null
	} finally {
		loading.value = false
	}
}

/* ---------- taking the money ---------- */

const payOpen = ref(false)
const paying = ref(false)
const active = ref(null)
const detail = ref(null)
const amount = ref('')
const mode = ref(null)
const reference = ref('')
/** Set when the cashier has chosen one specific invoice instead of the account. */
const againstInvoice = ref('')

const amountNum = computed(() => Number(amount.value) || 0)

/** What this payment will actually settle, worked out the same way the server
 *  will — oldest first — so the sheet can show it before anything is posted. */
const preview = computed(() => {
	if (againstInvoice.value || !detail.value) return []
	let left = amountNum.value
	const out = []
	for (const row of detail.value.rows) {
		if (left <= 0.005) break
		const applied = Math.min(left, row.outstanding)
		out.push({ ...row, applied, remaining: row.outstanding - applied })
		left -= applied
	}
	return out
})

const overpay = computed(() => {
	if (againstInvoice.value || !detail.value) return 0
	return Math.max(0, amountNum.value - detail.value.totals.outstanding)
})

async function openPay(row) {
	active.value = row
	detail.value = null
	againstInvoice.value = ''
	amount.value = ''
	reference.value = ''
	mode.value = methods.value[0]?.mode_of_payment || null
	payOpen.value = true
	try {
		detail.value = await getCustomerCredit({ customer: row.customer })
		// Pre-filled with the whole balance, which is what most customers hand
		// over. A part payment is typing a smaller number, not finding a
		// different control.
		amount.value = String(detail.value.totals.outstanding || '')
	} catch (e) {
		notify(e.message || 'Could not load that account', 'bad')
	}
}

const payBlocker = computed(() => {
	if (!detail.value) return 'Loading'
	if (amountNum.value <= 0) return 'Enter how much is being paid'
	if (againstInvoice.value) {
		const row = detail.value.rows.find((r) => r.name === againstInvoice.value)
		if (row && amountNum.value > row.outstanding + 0.005) {
			return `That is more than the ${fmtMoney(row.outstanding)} owed on ${row.name}`
		}
	}
	return null
})

async function takePayment() {
	if (payBlocker.value) return
	paying.value = true
	try {
		const res = againstInvoice.value
			? await payCreditSale({
					invoice: againstInvoice.value,
					amount: amountNum.value,
					modeOfPayment: mode.value,
					reference: reference.value || null,
				})
			: await payCustomer({
					customer: active.value.customer,
					amount: amountNum.value,
					modeOfPayment: mode.value,
					reference: reference.value || null,
				})

		payOpen.value = false
		await load()
		notify(said(res), 'good')
	} catch (e) {
		notify(e.message || 'Could not take that payment', 'bad')
	} finally {
		paying.value = false
	}
}

/**
 * What actually happened, in a sentence.
 *
 * Names the invoices the money landed on rather than reporting a bare total:
 * the whole promise of this screen is that a payment reconciles itself, and a
 * confirmation that does not say where it went is one nobody can check.
 */
function said(res) {
	if (againstInvoice.value) {
		return res.settled
			? `${fmtMoney(res.paid)} received · ${res.invoice} settled`
			: `${fmtMoney(res.paid)} received · ${fmtMoney(res.outstanding)} still owed`
	}

	const settled = res.settled?.length || 0
	const parts = [`${fmtMoney(res.paid)} received`]
	if (settled) parts.push(`${settled} invoice${settled === 1 ? '' : 's'} settled`)
	if (res.unallocated > 0) parts.push(`${fmtMoney(res.unallocated)} left on account`)
	if (res.outstanding > 0) parts.push(`${fmtMoney(res.outstanding)} still owed`)
	return parts.join(' · ')
}

const toast = ref(null)
let toastTimer = null
function notify(message, tone = 'good') {
	toast.value = { message, tone }
	clearTimeout(toastTimer)
	toastTimer = setTimeout(() => (toast.value = null), 4000)
}

watch(payOpen, (open) => {
	if (!open) active.value = null
})
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col overflow-hidden">
		<PageHeader
			title="Credit"
			subtitle="What the shop is owed, and taking it when they come back"
		>
			<template #actions>
				<Button variant="subtle" :icon-left="LucideRefreshCw" :loading="loading" @click="load" />
			</template>
		</PageHeader>

		<StatTiles :stats="stats" dense />

		<div class="flex shrink-0 items-center gap-2 border-b border-outline-gray-2 px-4 pb-3">
			<div class="relative w-full sm:w-[320px]">
				<LucideSearch
					class="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-gray-4"
				/>
				<input
					v-model="search"
					type="text"
					placeholder="Customer or phone number…"
					class="h-9 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 pl-8 pr-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
				/>
			</div>
			<span class="tabular ml-auto shrink-0 text-p-sm text-ink-gray-6">
				{{ rows.length }} {{ rows.length === 1 ? 'customer' : 'customers' }}
			</span>
		</div>

		<div class="min-h-0 flex-1 overflow-auto px-4 py-4">
			<p v-if="loading && !rows.length" class="py-10 text-center text-p-sm text-ink-gray-5">
				Loading…
			</p>
			<p v-else-if="!rows.length" class="py-10 text-center text-p-sm text-ink-gray-5">
				{{ data?.reason || 'Nobody owes the shop anything.' }}
			</p>

			<div v-else class="flex flex-col gap-2">
				<div
					v-for="row in rows"
					:key="row.customer"
					class="flex flex-wrap items-center gap-3 rounded-xl border bg-surface-white p-3"
					:class="row.overdue > 0 ? 'border-outline-red-2' : 'border-outline-gray-2'"
				>
					<div class="min-w-0 flex-1">
						<div class="truncate text-p-base font-medium text-ink-gray-9">
							{{ row.customer_name || row.customer }}
						</div>
						<div class="flex flex-wrap items-center gap-x-3 truncate text-p-xs text-ink-gray-5">
							<span>
								{{ row.invoices }} unpaid ·
								<!-- The invoice the money is about to land on. Said before the
								     cashier presses anything, because "oldest first" is a
								     promise this screen is making on their behalf. -->
								oldest {{ row.oldest_invoice }} ({{ row.oldest_date }})
							</span>
							<a
								v-if="row.phone"
								:href="`tel:${row.phone}`"
								class="flex items-center gap-1 underline underline-offset-2"
							>
								<LucidePhone class="h-3 w-3" />
								{{ row.phone }}
							</a>
						</div>
					</div>

					<div class="shrink-0 text-right">
						<div class="tabular text-p-base font-semibold text-ink-gray-9">
							{{ fmtMoney(row.outstanding) }}
						</div>
						<div v-if="row.overdue > 0" class="tabular text-p-xs font-medium text-ink-red-3">
							{{ fmtMoney(row.overdue) }} overdue
						</div>
					</div>

					<button
						class="shrink-0 rounded-lg bg-surface-gray-7 px-3 py-2 text-p-sm font-semibold text-ink-white transition-colors hover:bg-surface-gray-6"
						@click="openPay(row)"
					>
						Receive payment
					</button>
				</div>
			</div>
		</div>

		<BottomSheet v-model="payOpen" tall wide>
			<div v-if="active" class="flex flex-col gap-3 px-4 pb-5 pt-1">
				<header class="flex items-start gap-3">
					<span class="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-surface-green-2 text-ink-green-3">
						<LucideWallet class="h-4 w-4" />
					</span>
					<div class="min-w-0 flex-1">
						<h2 class="truncate text-p-lg font-semibold text-ink-gray-9">
							{{ active.customer_name || active.customer }}
						</h2>
						<p class="text-p-xs text-ink-gray-5">
							Owes {{ fmtMoney(active.outstanding) }} across
							{{ active.invoices }} sale{{ active.invoices === 1 ? '' : 's' }}
						</p>
					</div>
				</header>

				<div class="grid gap-2 sm:grid-cols-2">
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
						<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">Paid by</label>
						<select
							v-model="mode"
							class="h-12 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
						>
							<option :value="null">Cash (shop default)</option>
							<option v-for="m in methods" :key="m.key" :value="m.mode_of_payment">
								{{ m.label }}
							</option>
						</select>
					</div>
				</div>

				<input
					v-model="reference"
					type="text"
					placeholder="M-Pesa code or reference (optional)"
					class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm uppercase text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
				/>

				<!-- Where the money is going, before it goes. Oldest first is the
				     shop's own rule and the one ERPNext's ageing assumes; showing the
				     split makes it checkable rather than something the cashier has to
				     take on trust. -->
				<div class="rounded-xl border border-outline-gray-2">
					<div class="flex items-center justify-between border-b border-outline-gray-1 px-3 py-2">
						<span class="text-p-sm font-medium text-ink-gray-7">
							{{ againstInvoice ? 'Against one invoice' : 'Settles, oldest first' }}
						</span>
						<button
							v-if="againstInvoice"
							class="text-p-xs font-medium text-ink-blue-3"
							@click="againstInvoice = ''"
						>
							Spread across the account instead
						</button>
					</div>

					<p v-if="!detail" class="px-3 py-4 text-center text-p-sm text-ink-gray-5">Loading…</p>

					<div v-else class="max-h-[38dvh] overflow-auto">
						<button
							v-for="row in detail.rows"
							:key="row.name"
							class="flex w-full items-center gap-3 border-b border-outline-gray-1 px-3 py-2 text-left last:border-b-0"
							:class="
								againstInvoice === row.name
									? 'bg-surface-blue-1'
									: preview.some((p) => p.name === row.name)
										? 'bg-surface-green-1'
										: ''
							"
							@click="againstInvoice = againstInvoice === row.name ? '' : row.name"
						>
							<div class="min-w-0 flex-1">
								<div class="truncate text-p-sm font-medium text-ink-gray-8">
									{{ row.name }}
									<span v-if="row.overdue" class="font-medium text-ink-red-3">· overdue</span>
								</div>
								<div class="truncate text-p-xs text-ink-gray-5">
									{{ row.date }} · {{ fmtMoney(row.grand_total) }} billed
								</div>
							</div>
							<div class="shrink-0 text-right">
								<div class="tabular text-p-sm font-semibold text-ink-gray-9">
									{{ fmtMoney(row.outstanding) }}
								</div>
								<div
									v-if="preview.find((p) => p.name === row.name)"
									class="tabular text-p-xs font-medium text-ink-green-3"
								>
									−{{ fmtMoney(preview.find((p) => p.name === row.name).applied) }}
									→ {{ fmtMoney(preview.find((p) => p.name === row.name).remaining) }}
								</div>
							</div>
						</button>
					</div>
				</div>

				<p
					v-if="overpay > 0"
					class="rounded-lg bg-surface-blue-2 px-3 py-2 text-p-xs font-medium text-ink-blue-3"
				>
					{{ fmtMoney(overpay) }} more than is owed — it stays on the account as an advance.
				</p>
				<p v-else class="text-p-xs text-ink-gray-5">
					Tap an invoice to pay that one specifically. Otherwise the money comes off the
					oldest first.
				</p>

				<button
					class="flex min-h-touch w-full items-center justify-center gap-2 rounded-xl bg-surface-gray-7 py-3 text-p-lg font-semibold text-ink-white transition-all active:scale-[0.98] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
					:disabled="!!payBlocker || paying"
					@click="takePayment"
				>
					<LucideWallet class="h-5 w-5" />
					{{ payBlocker || (paying ? 'Posting…' : `Receive ${fmtMoney(amountNum)}`) }}
				</button>
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
				class="pos-toast pointer-events-none absolute bottom-5 left-1/2 -translate-x-1/2 max-w-[92vw] rounded-lg px-4 py-2.5 text-center text-p-sm font-medium text-ink-white shadow-lg"
				:class="toast.tone === 'bad' ? 'bg-surface-red-5' : 'bg-surface-green-3'"
			>
				{{ toast.message }}
			</div>
		</Transition>
	</div>
</template>
