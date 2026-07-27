<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { fmtMoney, fmtMoneyShort, round2 } from '@/utils/format'
import BottomSheet from './BottomSheet.vue'
import LucideBanknote from '~icons/lucide/banknote'
import LucideSmartphone from '~icons/lucide/smartphone'
import LucideCreditCard from '~icons/lucide/credit-card'
import LucideCheck from '~icons/lucide/check'
import LucideNotebookPen from '~icons/lucide/notebook-pen'
import LucideUserPlus from '~icons/lucide/user-plus'
import LucideAlertTriangle from '~icons/lucide/alert-triangle'
import LucideX from '~icons/lucide/x'
import LucideSplit from '~icons/lucide/split'

const props = defineProps({
	modelValue: { type: Boolean, default: false },
	total: { type: Number, default: 0 },
	/** Selected customer, or null for walk-in. Required for a credit sale. */
	customer: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'complete', 'pick-customer'])

const METHODS = [
	{ key: 'cash', label: 'Cash', icon: LucideBanknote },
	{ key: 'mpesa', label: 'M-Pesa', icon: LucideSmartphone },
	{ key: 'card', label: 'Card', icon: LucideCreditCard },
	{ key: 'credit', label: 'Credit', icon: LucideNotebookPen },
]

const method = ref('cash')
const tendered = ref('')
const reference = ref('')
const tenderedInput = ref(null)

const tenderedNum = computed(() => Number(tendered.value) || 0)
const change = computed(() => round2(Math.max(0, tenderedNum.value - props.total)))
const shortfall = computed(() => round2(Math.max(0, props.total - tenderedNum.value)))

const isCredit = computed(() => method.value === 'credit')

/* ---------- split tender & part payment ---------- */

const splitMode = ref(false)
/** Applied amounts per method; cash may exceed its share, giving change. */
const parts = ref([])

const partsTotal = computed(() =>
	parts.value.reduce((sum, p) => sum + (Number(p.amount) || 0), 0),
)
/** Positive = still owed, negative = over-tendered (change). */
const remaining = computed(() => props.total - partsTotal.value)
const isPartial = computed(() => splitMode.value && remaining.value > 0.005)

function startSplit() {
	splitMode.value = true
	// Seed with the current method for the full amount; the cashier reduces it
	// and adds a second row, which is how a split actually gets entered.
	parts.value = [{ method: method.value === 'credit' ? 'cash' : method.value, amount: '', reference: '' }]
}

function addPart() {
	const used = new Set(parts.value.map((p) => p.method))
	const next = ['cash', 'mpesa', 'card'].find((m) => !used.has(m)) || 'cash'
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

// Cash needs a tendered amount; credit needs a named customer to owe the money;
// the others settle exactly.
const canComplete = computed(() => {
	if (props.total <= 0) return false
	if (isCredit.value) return Boolean(props.customer)
	if (splitMode.value) {
		if (partsTotal.value <= 0) return false
		// An unpaid balance is a debt, so it needs a named customer to sit against.
		return isPartial.value ? Boolean(props.customer) : true
	}
	if (method.value === 'cash') return tenderedNum.value >= props.total
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
		method.value = 'cash'
		tendered.value = ''
		reference.value = ''
		splitMode.value = false
		parts.value = []
		await nextTick()
		tenderedInput.value?.focus()
	},
)

function complete() {
	if (!canComplete.value) return

	if (splitMode.value) {
		emit('complete', {
			method: 'split',
			parts: parts.value
				.filter((p) => Number(p.amount) > 0)
				.map((p) => ({
					method: p.method,
					amount: Number(p.amount),
					reference: p.reference || null,
				})),
			tendered: partsTotal.value,
			change: remaining.value < 0 ? -remaining.value : 0,
			outstanding: isPartial.value ? remaining.value : 0,
		})
		return
	}

	emit('complete', {
		method: method.value,
		// A credit sale collects nothing now.
		tendered: isCredit.value ? 0 : method.value === 'cash' ? tenderedNum.value : props.total,
		change: method.value === 'cash' ? change.value : 0,
		reference: reference.value,
	})
}
</script>

<template>
	<BottomSheet
		:model-value="modelValue"
		tall
		@update:model-value="emit('update:modelValue', $event)"
	>
		<div class="flex flex-col gap-4 px-4 pb-5 pt-1">
			<!-- Amount due leads: it is the number both people in the transaction care about. -->
			<div class="text-center">
				<div class="text-p-sm text-ink-gray-5">Amount due</div>
				<div class="tabular mt-0.5 text-4xl font-semibold tracking-tight text-ink-gray-9">
					{{ fmtMoney(total) }}
				</div>
			</div>

			<!-- Split tender / part payment -->
			<div v-if="splitMode" class="flex flex-col gap-3">
				<div v-for="(p, i) in parts" :key="i" class="rounded-xl border border-outline-gray-2 p-3">
					<div class="flex items-center gap-2">
						<select
							v-model="p.method"
							class="h-11 min-w-0 flex-1 rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-2 text-p-base text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
						>
							<option value="cash">Cash</option>
							<option value="mpesa">M-Pesa</option>
							<option value="card">Card</option>
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
					class="flex items-center justify-between rounded-xl px-4 py-3"
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
					class="flex min-h-touch items-center gap-3 rounded-xl border p-3.5 text-left transition-colors"
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
				class="flex min-h-touch items-center justify-center gap-2 rounded-xl border border-outline-gray-2 py-2.5 text-p-base font-medium text-ink-gray-7 transition-colors hover:bg-surface-gray-2"
				@click="startSplit"
			>
				<LucideSplit class="h-4 w-4" />
				Split or part-pay
			</button>

			<!-- Method -->
			<div v-if="!splitMode" class="grid grid-cols-4 gap-2">
				<button
					v-for="m in METHODS"
					:key="m.key"
					class="flex min-h-touch flex-col items-center gap-1.5 rounded-xl border py-3 transition-colors"
					:class="
						method === m.key
							? 'border-outline-gray-4 bg-surface-gray-3 text-ink-gray-9'
							: 'border-outline-gray-2 bg-surface-white text-ink-gray-6 hover:bg-surface-gray-2'
					"
					@click="method = m.key"
				>
					<component :is="m.icon" class="h-5 w-5" />
					<span class="text-p-sm font-medium">{{ m.label }}</span>
				</button>
			</div>

			<!-- Credit: the customer IS the transaction, so it leads. -->
			<div v-if="!splitMode && isCredit" class="flex flex-col gap-3">
				<button
					class="flex min-h-touch items-center gap-3 rounded-xl border p-3.5 text-left transition-colors"
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
					class="flex items-start gap-2.5 rounded-xl bg-surface-amber-2 px-4 py-3"
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

				<div class="rounded-xl bg-surface-gray-2 px-4 py-3 text-p-sm text-ink-gray-6">
					Nothing is collected now. The invoice stays unpaid on the customer's account
					and is not counted in the drawer at close.
				</div>
			</div>

			<!-- Cash -->
			<div v-else-if="method === 'cash'" class="flex flex-col gap-3">
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
						class="tabular h-14 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-4 text-2xl font-semibold text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none focus:ring-2 focus:ring-outline-gray-3"
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

				<!-- Change is the highest-stakes number on this screen, so it gets
				     colour and size the moment it becomes real. -->
				<div
					class="flex items-center justify-between rounded-xl px-4 py-3 transition-colors"
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

			<!-- M-Pesa / card reference -->
			<div v-else>
				<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">
					{{ method === 'mpesa' ? 'M-Pesa code' : 'Card reference' }}
					<span class="font-normal text-ink-gray-4">(optional)</span>
				</label>
				<input
					v-model="reference"
					type="text"
					autocapitalize="characters"
					:placeholder="method === 'mpesa' ? 'e.g. SLK7XR2QM4' : 'Last 4 digits'"
					class="h-12 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-4 text-p-lg uppercase text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none focus:ring-2 focus:ring-outline-gray-3"
					@keyup.enter="complete"
				/>
			</div>

			<button
				class="flex min-h-touch w-full items-center justify-center gap-2 rounded-xl bg-surface-gray-7 py-4 text-p-lg font-semibold text-ink-white transition-all active:scale-[0.98] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
				:disabled="!canComplete"
				@click="complete"
			>
				<LucideCheck class="h-5 w-5" />
				{{
					isCredit
						? 'Record credit sale'
						: isPartial
							? `Take part-payment · ${fmtMoney(remaining)} owed`
							: 'Complete sale'
				}}
			</button>
		</div>
	</BottomSheet>
</template>
