<script setup>
import { ref, computed, watch } from 'vue'
import { fmtMoney } from '@/utils/format'
import { getReturnableSale, createSalesReturn } from '@/data/api'
import BottomSheet from './BottomSheet.vue'
import LucideUndo from '~icons/lucide/undo-2'
import LucideBanknote from '~icons/lucide/banknote'
import LucideNotebookPen from '~icons/lucide/notebook-pen'

/**
 * Taking goods back, from the sale they came from.
 *
 * Started from a sale rather than from a blank form because that is the only
 * way to know what may come back. A free-form return would let a customer be
 * refunded for something they never bought, or twice for one purchase, and the
 * cashier would have no way to tell.
 *
 * Quantities default to zero, not to everything. Most returns are one item out
 * of several, and a form pre-filled with the whole basket is one where a hurried
 * tap refunds the lot.
 */
const props = defineProps({
	modelValue: { type: Boolean, default: false },
	/** Invoice number to return against. */
	invoice: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'returned'])

const sale = ref(null)
const loading = ref(false)
const busy = ref(false)
const error = ref(null)

/** item_code → quantity coming back. */
const qty = ref({})
const method = ref('cash')
const reason = ref('')

watch(
	() => props.modelValue,
	async (open) => {
		if (!open || !props.invoice) return
		sale.value = null
		qty.value = {}
		method.value = 'cash'
		reason.value = ''
		error.value = null
		loading.value = true
		try {
			sale.value = await getReturnableSale({ invoice: props.invoice })
		} catch (e) {
			error.value = e.message || 'Could not load that sale'
		} finally {
			loading.value = false
		}
	},
)

const lines = computed(() => (sale.value?.items || []).filter((i) => i.qty > 0))

const refundTotal = computed(() =>
	lines.value.reduce((sum, l) => sum + (Number(qty.value[l.item_code]) || 0) * l.rate, 0),
)

const canSubmit = computed(() => refundTotal.value > 0 && !busy.value)

function setQty(line, value) {
	const n = Math.max(0, Math.min(line.qty, Number(value) || 0))
	qty.value = { ...qty.value, [line.item_code]: n }
}

/** The common case is "all of this one line", so it is one tap. */
function takeAll(line) {
	setQty(line, line.qty)
}

async function submit() {
	if (!canSubmit.value) return
	busy.value = true
	error.value = null
	try {
		const res = await createSalesReturn({
			invoice: props.invoice,
			lines: lines.value
				.filter((l) => (Number(qty.value[l.item_code]) || 0) > 0)
				.map((l) => ({ item_code: l.item_code, qty: Number(qty.value[l.item_code]) })),
			refundMethod: method.value,
			reason: reason.value || null,
		})
		emit('returned', res)
		emit('update:modelValue', false)
	} catch (e) {
		error.value = e.message || 'Could not complete the return'
	} finally {
		busy.value = false
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
				<div class="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-surface-amber-2">
					<LucideUndo class="h-5 w-5 text-ink-amber-3" />
				</div>
				<div class="min-w-0 flex-1">
					<div class="text-p-lg font-semibold text-ink-gray-9">Take goods back</div>
					<div class="truncate text-p-sm text-ink-gray-5">
						{{ sale ? `${sale.invoice} · ${sale.customer_name}` : invoice }}
					</div>
				</div>
			</div>

			<p v-if="loading" class="px-1 text-p-sm text-ink-gray-5">Loading the sale…</p>

			<p
				v-else-if="error"
				class="rounded-lg bg-surface-red-2 px-3 py-2 text-p-sm text-ink-red-3"
			>
				{{ error }}
			</p>

			<p
				v-else-if="sale?.fully_returned"
				class="rounded-lg bg-surface-gray-2 px-3 py-2 text-p-sm text-ink-gray-6"
			>
				Everything on this sale has already been returned.
			</p>

			<template v-else-if="sale">
				<!-- Quantities start at zero: most returns are one line out of
				     several, and a pre-filled basket is one a hurried tap refunds
				     in full. -->
				<div class="flex flex-col gap-2">
					<div
						v-for="line in lines"
						:key="line.item_code"
						class="rounded-xl border border-outline-gray-2 p-3"
					>
						<div class="flex items-baseline justify-between gap-2">
							<span class="min-w-0 truncate text-p-base font-medium text-ink-gray-9">
								{{ line.item_name }}
							</span>
							<span class="tabular shrink-0 text-p-sm text-ink-gray-5">
								{{ fmtMoney(line.rate) }}
							</span>
						</div>
						<div class="mt-0.5 text-p-xs text-ink-gray-5">
							{{ line.sold_qty }} sold
							<template v-if="line.returned_qty">
								· {{ line.returned_qty }} already back
							</template>
							· {{ line.qty }} can return
						</div>
						<div class="mt-2 flex items-center gap-2">
							<input
								:value="qty[line.item_code] ?? 0"
								type="number"
								min="0"
								:max="line.qty"
								inputmode="numeric"
								class="tabular h-11 w-24 rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-lg font-semibold text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
								@input="setQty(line, $event.target.value)"
								@focus="$event.target.select()"
							/>
							<button
								class="min-h-touch rounded-lg border border-outline-gray-2 px-3 text-p-sm font-medium text-ink-gray-7 hover:bg-surface-gray-2"
								@click="takeAll(line)"
							>
								All {{ line.qty }}
							</button>
							<span class="tabular ml-auto text-p-base font-semibold text-ink-gray-9">
								{{ fmtMoney((Number(qty[line.item_code]) || 0) * line.rate) }}
							</span>
						</div>
					</div>
				</div>

				<!-- The one decision that changes the accounting rather than the
				     screen: cash comes out of this shift's drawer, credit sits on
				     the customer's account until they spend it. -->
				<div>
					<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">
						How is it refunded?
					</label>
					<div class="grid grid-cols-2 gap-2">
						<button
							v-for="m in [
								{ key: 'cash', label: 'Cash back', icon: LucideBanknote, hint: 'Out of the drawer' },
								{ key: 'credit', label: 'On account', icon: LucideNotebookPen, hint: 'Needs a customer' },
							]"
							:key="m.key"
							class="flex min-h-touch flex-col items-start gap-0.5 rounded-xl border px-3 py-2.5 text-left transition-colors"
							:class="
								method === m.key
									? 'border-outline-gray-4 bg-surface-gray-3 text-ink-gray-9'
									: 'border-outline-gray-2 bg-surface-white text-ink-gray-6 hover:bg-surface-gray-2'
							"
							@click="method = m.key"
						>
							<span class="flex items-center gap-1.5 text-p-base font-medium">
								<component :is="m.icon" class="h-4 w-4" />
								{{ m.label }}
							</span>
							<span class="text-p-xs text-ink-gray-5">{{ m.hint }}</span>
						</button>
					</div>
					<p class="mt-1.5 text-p-xs text-ink-gray-5">
						Cash comes off what this shift expects to hold, so the close still
						balances.
					</p>
				</div>

				<div>
					<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">
						Why <span class="font-normal text-ink-gray-4">(optional)</span>
					</label>
					<input
						v-model="reason"
						type="text"
						placeholder="Damaged, wrong shade…"
						class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
					/>
				</div>

				<div
					class="flex items-center justify-between rounded-xl px-4 py-3"
					:class="refundTotal > 0 ? 'bg-surface-amber-2' : 'bg-surface-gray-2'"
				>
					<span
						class="text-p-base font-medium"
						:class="refundTotal > 0 ? 'text-ink-amber-3' : 'text-ink-gray-6'"
					>
						Refund
					</span>
					<span
						class="tabular text-2xl font-semibold"
						:class="refundTotal > 0 ? 'text-ink-amber-3' : 'text-ink-gray-7'"
					>
						{{ fmtMoney(refundTotal) }}
					</span>
				</div>

				<button
					class="min-h-touch w-full rounded-xl bg-surface-gray-7 py-3.5 text-p-lg font-semibold text-ink-white transition-all active:scale-[0.98] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
					:disabled="!canSubmit"
					@click="submit"
				>
					{{
						busy
							? 'Returning…'
							: refundTotal > 0
								? `Refund ${fmtMoney(refundTotal)}`
								: 'Choose what is coming back'
					}}
				</button>
			</template>
		</div>
	</BottomSheet>
</template>
