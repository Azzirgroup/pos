<script setup>
import { ref, computed, watch } from 'vue'
import { fmtMoney } from '@/utils/format'
import { getSaleActions, voidSale, changeSalePayment } from '@/data/api'
import BottomSheet from './BottomSheet.vue'
import LucideUndo from '~icons/lucide/undo-2'
import LucideBan from '~icons/lucide/ban'
import LucideWallet from '~icons/lucide/wallet'
import LucidePlus from '~icons/lucide/plus'
import LucideX from '~icons/lucide/x'
import LucideChevronRight from '~icons/lucide/chevron-right'

/**
 * Correcting a sale after it was rung up — see `cosmestics.api.sale_changes`.
 *
 * `reverse` is what the undo button on a sale opens: the cashier picks between
 * taking goods back (a refund, out of the drawer) and voiding the sale (it never
 * happened — stock, accounts and shift all reversed). They are different
 * accounting and the wrong one leaves the drawer short, so the difference is
 * spelled out on each option rather than left to the label.
 *
 * `payment` re-books the tenders on a sale without changing what was paid.
 *
 * What cannot be done is asked for before anything is drawn, so an option that
 * would be refused says why instead of failing after the tap.
 */
const props = defineProps({
	modelValue: { type: Boolean, default: false },
	invoice: { type: String, default: '' },
	/** 'reverse' | 'payment' */
	mode: { type: String, default: 'reverse' },
	/** The till's tenders, from `pos.get_payment_methods`. */
	methods: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:modelValue', 'return', 'changed'])

const sale = ref(null)
const loading = ref(false)
const busy = ref(false)
const error = ref(null)
const confirmVoid = ref(false)
const reason = ref('')
/** [{ mode_of_payment, amount, reference }] */
const rows = ref([])

watch(
	() => props.modelValue,
	async (open) => {
		if (!open || !props.invoice) return
		sale.value = null
		error.value = null
		confirmVoid.value = false
		reason.value = ''
		rows.value = []
		loading.value = true
		try {
			sale.value = await getSaleActions({ invoice: props.invoice })
			rows.value = (sale.value.payments || []).map((p) => ({
				mode_of_payment: p.mode_of_payment,
				amount: p.amount,
				reference: p.reference || '',
			}))
		} catch (e) {
			error.value = e.message || 'Could not load that sale'
		} finally {
			loading.value = false
		}
	},
)

function close() {
	emit('update:modelValue', false)
}

/* ---------- reverse ---------- */

function chooseReturn() {
	close()
	emit('return', props.invoice)
}

async function doVoid() {
	busy.value = true
	error.value = null
	try {
		const res = await voidSale({ invoice: props.invoice, reason: reason.value || null })
		emit('changed', { kind: 'void', ...res })
		close()
	} catch (e) {
		error.value = e.message || 'Could not void the sale'
	} finally {
		busy.value = false
	}
}

/* ---------- payment ---------- */

/** One entry per Mode of Payment; several till buttons can share one. */
const modeOptions = computed(() => {
	const seen = new Set()
	const out = []
	for (const m of props.methods || []) {
		const mode = m.mode_of_payment
		if (!mode || seen.has(mode)) continue
		seen.add(mode)
		out.push(mode)
	}
	// Whatever the sale is booked to now stays choosable.
	for (const p of sale.value?.payments || []) {
		if (!seen.has(p.mode_of_payment)) {
			seen.add(p.mode_of_payment)
			out.push(p.mode_of_payment)
		}
	}
	return out
})

const entered = computed(() =>
	rows.value.reduce((sum, r) => sum + (Number(r.amount) || 0), 0),
)
const remaining = computed(() => Math.round(((sale.value?.paid || 0) - entered.value) * 100) / 100)

function summary(list) {
	const merged = new Map()
	for (const r of list) {
		const amount = Number(r.amount) || 0
		if (!r.mode_of_payment || amount <= 0) continue
		merged.set(r.mode_of_payment, Math.round(((merged.get(r.mode_of_payment) || 0) + amount) * 100) / 100)
	}
	return [...merged.entries()].map(([m, a]) => `${m}:${a}`).sort().join('|')
}

const unchanged = computed(() => summary(rows.value) === summary(sale.value?.payments || []))

const canSave = computed(
	() =>
		!busy.value &&
		sale.value?.can_change_payment &&
		rows.value.some((r) => r.mode_of_payment && Number(r.amount) > 0) &&
		Math.abs(remaining.value) < 0.005 &&
		!unchanged.value,
)

/** The usual correction is "it was all X", so picking a tender on a single row
 *  moves the whole amount. */
function pickSingle(mode) {
	rows.value = [{ mode_of_payment: mode, amount: sale.value?.paid || 0, reference: '' }]
}

function addRow() {
	const used = new Set(rows.value.map((r) => r.mode_of_payment))
	const next = modeOptions.value.find((m) => !used.has(m)) || modeOptions.value[0] || ''
	rows.value = [...rows.value, { mode_of_payment: next, amount: Math.max(remaining.value, 0), reference: '' }]
}

function removeRow(i) {
	rows.value = rows.value.filter((_, idx) => idx !== i)
}

async function savePayment() {
	if (!canSave.value) return
	busy.value = true
	error.value = null
	try {
		const res = await changeSalePayment({
			invoice: props.invoice,
			payments: rows.value
				.filter((r) => r.mode_of_payment && Number(r.amount) > 0)
				.map((r) => ({
					mode_of_payment: r.mode_of_payment,
					amount: Number(r.amount),
					reference: r.reference || null,
				})),
		})
		emit('changed', { kind: 'payment', ...res })
		close()
	} catch (e) {
		error.value = e.message || 'Could not change the payment'
	} finally {
		busy.value = false
	}
}
</script>

<template>
	<BottomSheet :model-value="modelValue" :tall="mode === 'payment'" @update:model-value="emit('update:modelValue', $event)">
		<div class="flex flex-col gap-3 px-4 pb-5 pt-1">
			<div class="flex items-center gap-3">
				<div
					class="grid h-10 w-10 shrink-0 place-items-center rounded-lg"
					:class="mode === 'payment' ? 'bg-surface-blue-2' : 'bg-surface-amber-2'"
				>
					<LucideWallet v-if="mode === 'payment'" class="h-5 w-5 text-ink-blue-3" />
					<LucideUndo v-else class="h-5 w-5 text-ink-amber-3" />
				</div>
				<div class="min-w-0 flex-1">
					<div class="text-p-lg font-semibold text-ink-gray-9">
						{{ mode === 'payment' ? 'Change payment method' : 'Reverse this sale' }}
					</div>
					<div class="truncate text-p-sm text-ink-gray-5">
						{{ sale ? `${sale.invoice} · ${sale.customer} · ${fmtMoney(sale.grand_total)}` : invoice }}
					</div>
				</div>
			</div>

			<p v-if="loading" class="px-1 text-p-sm text-ink-gray-5">Loading the sale…</p>

			<p v-if="error" class="rounded-lg bg-surface-red-2 px-3 py-2 text-p-sm text-ink-red-3">
				{{ error }}
			</p>

			<!-- ---------- reverse: return goods or void ---------- -->
			<template v-if="sale && mode === 'reverse' && !confirmVoid">
				<button
					class="flex min-h-touch items-center gap-3 rounded-xl border border-outline-gray-2 px-3 py-3 text-left transition-colors hover:bg-surface-gray-2 disabled:cursor-not-allowed disabled:opacity-50"
					:disabled="!sale.can_return"
					@click="chooseReturn"
				>
					<LucideUndo class="h-5 w-5 shrink-0 text-ink-amber-3" />
					<span class="min-w-0 flex-1">
						<span class="block text-p-base font-semibold text-ink-gray-9">Return goods</span>
						<span class="block text-p-xs text-ink-gray-5">
							The customer brings items back and is refunded. Stock returns to the shelf
							and the refund comes out of this shift's cash.
						</span>
						<span v-if="!sale.can_return" class="mt-0.5 block text-p-xs text-ink-amber-3">
							{{ sale.return_reason }}
						</span>
					</span>
					<LucideChevronRight class="h-4 w-4 shrink-0 text-ink-gray-4" />
				</button>

				<button
					class="flex min-h-touch items-center gap-3 rounded-xl border border-outline-gray-2 px-3 py-3 text-left transition-colors hover:bg-surface-red-1 disabled:cursor-not-allowed disabled:opacity-50"
					:disabled="!sale.can_void"
					@click="confirmVoid = true"
				>
					<LucideBan class="h-5 w-5 shrink-0 text-ink-red-3" />
					<span class="min-w-0 flex-1">
						<span class="block text-p-base font-semibold text-ink-gray-9">Void sale</span>
						<span class="block text-p-xs text-ink-gray-5">
							The sale should never have happened. It is cancelled completely — stock,
							accounts and the shift are reversed as if it was never rung up.
						</span>
						<span v-if="!sale.can_void" class="mt-0.5 block text-p-xs text-ink-amber-3">
							{{ sale.void_reason }}
						</span>
					</span>
					<LucideChevronRight class="h-4 w-4 shrink-0 text-ink-gray-4" />
				</button>
			</template>

			<template v-if="sale && mode === 'reverse' && confirmVoid">
				<p class="rounded-lg bg-surface-red-1 px-3 py-2 text-p-sm text-ink-red-3">
					Void {{ sale.invoice }} for {{ fmtMoney(sale.grand_total) }}? This cannot be undone.
				</p>
				<div>
					<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">
						Why <span class="font-normal text-ink-gray-4">(optional)</span>
					</label>
					<input
						v-model="reason"
						type="text"
						placeholder="Rung up twice, customer left…"
						class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
					/>
				</div>
				<div class="grid grid-cols-2 gap-2">
					<button
						class="min-h-touch rounded-xl border border-outline-gray-2 py-3 text-p-base font-medium text-ink-gray-7 hover:bg-surface-gray-2"
						:disabled="busy"
						@click="confirmVoid = false"
					>
						Back
					</button>
					<button
						class="min-h-touch rounded-xl bg-surface-red-5 py-3 text-p-base font-semibold text-ink-white transition-all active:scale-[0.98] disabled:opacity-60"
						:disabled="busy"
						@click="doVoid"
					>
						{{ busy ? 'Voiding…' : 'Void sale' }}
					</button>
				</div>
			</template>

			<!-- ---------- payment ---------- -->
			<template v-if="sale && mode === 'payment'">
				<p
					v-if="!sale.can_change_payment"
					class="rounded-lg bg-surface-amber-2 px-3 py-2 text-p-sm text-ink-amber-3"
				>
					{{ sale.change_reason }}
				</p>

				<template v-else>
					<div class="rounded-xl bg-surface-gray-2 px-3 py-2 text-p-sm text-ink-gray-6">
						Booked now as
						<span class="font-medium text-ink-gray-9">
							{{ sale.payments.map((p) => `${p.mode_of_payment} ${fmtMoney(p.amount)}`).join(' + ') }}
						</span>
					</div>

					<!-- One tap for the common mistake: it was all one other tender. -->
					<div>
						<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">It was all paid by</label>
						<div class="flex flex-wrap gap-2">
							<button
								v-for="m in modeOptions"
								:key="m"
								class="min-h-touch rounded-lg border px-3 text-p-sm font-medium transition-colors"
								:class="
									rows.length === 1 && rows[0].mode_of_payment === m
										? 'border-outline-gray-4 bg-surface-gray-3 text-ink-gray-9'
										: 'border-outline-gray-2 text-ink-gray-7 hover:bg-surface-gray-2'
								"
								@click="pickSingle(m)"
							>
								{{ m }}
							</button>
						</div>
					</div>

					<div class="flex flex-col gap-2">
						<label class="block text-p-sm font-medium text-ink-gray-7">Or split it</label>
						<div
							v-for="(row, i) in rows"
							:key="i"
							class="flex flex-wrap items-center gap-2 rounded-xl border border-outline-gray-2 p-2"
						>
							<select
								v-model="row.mode_of_payment"
								class="h-11 min-w-0 flex-1 rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-2 text-p-base text-ink-gray-9"
							>
								<option v-for="m in modeOptions" :key="m" :value="m">{{ m }}</option>
							</select>
							<input
								v-model.number="row.amount"
								type="number"
								min="0"
								inputmode="decimal"
								class="tabular h-11 w-28 rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base font-semibold text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
								@focus="$event.target.select()"
							/>
							<input
								v-model="row.reference"
								type="text"
								placeholder="Reference"
								class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none sm:w-36"
							/>
							<button
								v-if="rows.length > 1"
								class="grid h-9 w-9 place-items-center rounded-lg text-ink-gray-5 hover:bg-surface-gray-2"
								aria-label="Remove this payment"
								@click="removeRow(i)"
							>
								<LucideX class="h-4 w-4" />
							</button>
						</div>
						<button
							class="flex min-h-touch items-center justify-center gap-1.5 rounded-xl border border-dashed border-outline-gray-3 text-p-sm font-medium text-ink-gray-7 hover:bg-surface-gray-2"
							@click="addRow"
						>
							<LucidePlus class="h-4 w-4" /> Add another method
						</button>
					</div>

					<div
						class="flex items-center justify-between rounded-xl px-4 py-3"
						:class="Math.abs(remaining) < 0.005 ? 'bg-surface-green-2' : 'bg-surface-amber-2'"
					>
						<span class="text-p-base font-medium text-ink-gray-7">
							{{ Math.abs(remaining) < 0.005 ? 'Adds up to what was paid' : remaining > 0 ? 'Still to allocate' : 'Too much by' }}
						</span>
						<span class="tabular text-xl font-semibold text-ink-gray-9">
							{{ fmtMoney(Math.abs(remaining) < 0.005 ? sale.paid : Math.abs(remaining)) }}
						</span>
					</div>

					<button
						class="min-h-touch w-full rounded-xl bg-surface-gray-7 py-3.5 text-p-lg font-semibold text-ink-white transition-all active:scale-[0.98] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
						:disabled="!canSave"
						@click="savePayment"
					>
						{{ busy ? 'Saving…' : unchanged ? 'Choose the correct method' : 'Save payment method' }}
					</button>
					<p class="text-p-xs text-ink-gray-5">
						The sale is re-booked under a new number ending in “-1”, the accounts move to the
						new method, and the sales group is told what changed.
					</p>
				</template>
			</template>
		</div>
	</BottomSheet>
</template>
