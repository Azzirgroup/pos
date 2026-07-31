<script setup>
import { ref, computed, watch } from 'vue'
import { fmtMoney, fmtMoneyShort, round2 } from '@/utils/format'
import BottomSheet from './BottomSheet.vue'
import LucideArrowLeftRight from '~icons/lucide/arrow-left-right'
import LucideStore from '~icons/lucide/store'
import LucideAlertTriangle from '~icons/lucide/alert-triangle'
import LucideChevronLeft from '~icons/lucide/chevron-left'

const props = defineProps({
	modelValue: { type: Boolean, default: false },
	item: { type: Object, default: null },
	warehouses: { type: Array, default: () => [] },
	neighbours: { type: Array, default: () => [] },
	/** How many units the cart is short by. Seeds the quantity fields. */
	suggestedQty: { type: Number, default: 1 },
})

const emit = defineEmits(['update:modelValue', 'request-transfer', 'source', 'sell-anyway'])

// 'menu' → pick an approach; the other two are the detail forms.
const mode = ref('menu')
const qty = ref(1)
/**
 * How many to *buy*, which is not always how many to sell.
 *
 * The shop next door sells a carton, not a unit. Buying 100 to satisfy a sale
 * of 10 is ordinary, and until now impossible: one quantity drove both the
 * purchase and the cart line, so the shop could only ever buy exactly what it
 * was selling and the other 90 could not be brought onto the shelf.
 *
 * Defaults to the sell quantity, because that is still the common case — and a
 * cashier who does not touch this field gets exactly the old behaviour.
 */
const buyQty = ref(1)
const warehouse = ref(null)
const neighbour = ref(null)
const buyRate = ref('')
/**
 * Whether the cashier handed over money there and then.
 *
 * Defaults to off because the usual arrangement between neighbouring shops is
 * to settle at the end of the week, and booking a payment that never happened
 * invents a cash movement the drawer will be short by. Turning it on both marks
 * the purchase paid and takes the cash off what the shift expects to count.
 */
const paidNow = ref(false)

watch(
	() => props.modelValue,
	(open) => {
		if (!open) return
		mode.value = 'menu'
		// The gap, not one. A cashier who has just tried to sell six of the last
		// two should not have to work out that they need four.
		qty.value = Math.max(1, props.suggestedQty || 1)
		buyQty.value = qty.value
		warehouse.value = props.warehouses.find((w) => !w.is_default)?.name || null
		neighbour.value = props.neighbours[0]?.name || null
		paidNow.value = false
		// Seed with the shelf price so the cashier only edits when the neighbour
		// quotes something different.
		buyRate.value = props.item ? String(props.item.price) : ''
	},
)

const buyRateNum = computed(() => Number(buyRate.value) || 0)
const buyQtyNum = computed(() => Math.max(Number(buyQty.value) || 0, qty.value))
/** What is bought but not sold now, and therefore stays on the shelf. */
const keptQty = computed(() => round2(buyQtyNum.value - qty.value))

const sellTotal = computed(() => round2((props.item?.price || 0) * qty.value))
/** The whole outlay, including the part that becomes stock. */
const costTotal = computed(() => round2(buyRateNum.value * buyQtyNum.value))
/**
 * Margin on *this sale*, not on the purchase.
 *
 * Costing the sale at the full carton would show a loss on every bulk buy,
 * which is wrong: the rest is not spent, it is stock, and it earns its margin
 * when it sells. The outlay is shown separately so nobody is surprised at the
 * drawer.
 */
const margin = computed(() => round2(sellTotal.value - buyRateNum.value * qty.value))

const canSource = computed(
	() => neighbour.value && qty.value > 0 && buyQtyNum.value >= qty.value && buyRateNum.value > 0,
)
const canRequest = computed(() => warehouse.value && qty.value > 0)

function close() {
	emit('update:modelValue', false)
}

function submitTransfer() {
	if (!canRequest.value) return
	emit('request-transfer', {
		item: props.item,
		qty: qty.value,
		warehouse: warehouse.value,
	})
	close()
}

function submitSellAnyway() {
	emit('sell-anyway', { item: props.item, qty: qty.value })
	close()
}

function submitSource() {
	if (!canSource.value) return
	emit('source', {
		item: props.item,
		qty: qty.value,
		buyQty: buyQtyNum.value,
		supplier: neighbour.value,
		buyRate: buyRateNum.value,
		paidNow: paidNow.value,
	})
	close()
}
</script>

<template>
	<BottomSheet
		:model-value="modelValue"
		tall
		@update:model-value="emit('update:modelValue', $event)"
	>
		<div v-if="item" class="flex flex-col gap-4 px-4 pb-5 pt-1">
			<!-- Context: which item, and why we are here -->
			<div class="flex items-start gap-3">
				<button
					v-if="mode !== 'menu'"
					class="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-ink-gray-6 hover:bg-surface-gray-2"
					aria-label="Back"
					@click="mode = 'menu'"
				>
					<LucideChevronLeft class="h-5 w-5" />
				</button>
				<div class="min-w-0 flex-1">
					<div class="text-p-lg font-semibold leading-tight text-ink-gray-9">
						{{ item.item_name }}
					</div>
					<div class="mt-1 flex items-center gap-2 text-p-sm">
						<!-- Two different situations reach this sheet — nothing on the
						     shelf, and not enough of it — and the fix differs, so the
						     line says which one you are in. -->
						<span
							class="rounded px-1.5 py-0.5 font-medium"
							:class="
								item.stock <= 0
									? 'bg-surface-red-2 text-ink-red-3'
									: 'bg-surface-amber-2 text-ink-amber-3'
							"
						>
							{{
								item.stock <= 0
									? 'Out of stock'
									: `Only ${Math.floor(item.stock)} on the shelf`
							}}
						</span>
						<span
							v-if="item.stock > 0 && suggestedQty > 0"
							class="rounded bg-surface-gray-3 px-1.5 py-0.5 font-medium text-ink-gray-7"
						>
							{{ suggestedQty }} short
						</span>
						<span class="tabular text-ink-gray-5">{{ fmtMoney(item.price) }}</span>
					</div>
				</div>
			</div>

			<!-- Step 1: choose how to fulfil -->
			<template v-if="mode === 'menu'">
				<button
					class="flex items-center gap-3 rounded-xl border border-outline-gray-2 bg-surface-white p-3.5 text-left transition-colors hover:bg-surface-gray-2"
					@click="mode = 'source'"
				>
					<div class="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-surface-green-2">
						<LucideStore class="h-5 w-5 text-ink-green-3" />
					</div>
					<div class="min-w-0 flex-1">
						<div class="text-p-base font-medium text-ink-gray-9">
							Buy from a neighbour
						</div>
						<div class="text-p-sm text-ink-gray-5">
							Customer waits · sells on this receipt
						</div>
					</div>
				</button>

				<button
					class="flex items-center gap-3 rounded-xl border border-outline-gray-2 bg-surface-white p-3.5 text-left transition-colors hover:bg-surface-gray-2"
					@click="mode = 'transfer'"
				>
					<div class="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-surface-blue-2">
						<LucideArrowLeftRight class="h-5 w-5 text-ink-blue-3" />
					</div>
					<div class="min-w-0 flex-1">
						<div class="text-p-base font-medium text-ink-gray-9">
							Request from another store
						</div>
						<div class="text-p-sm text-ink-gray-5">
							Raises a material request · posts to WhatsApp
						</div>
					</div>
				</button>

				<button
					class="flex items-center gap-3 rounded-xl border border-outline-gray-2 bg-surface-white p-3.5 text-left transition-colors hover:bg-surface-gray-2"
					@click="submitSellAnyway"
				>
					<div class="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-surface-amber-2">
						<LucideAlertTriangle class="h-5 w-5 text-ink-amber-3" />
					</div>
					<div class="min-w-0 flex-1">
						<div class="text-p-base font-medium text-ink-gray-9">Sell anyway</div>
						<div class="text-p-sm text-ink-gray-5">
							It is on the shelf but not yet received in the system
						</div>
					</div>
				</button>
			</template>

			<!-- Step 2a: buy from a neighbour -->
			<template v-else-if="mode === 'source'">
				<div>
					<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">
						Which shop
					</label>
					<!-- A select rather than a button per shop. The list starts at one
					     and grows every time the till sources from somewhere new —
					     `_ensure_supplier` creates unknown shops on the spot — so a
					     stack of buttons would push the price and the margin off the
					     screen exactly as the shop got busier. A native select also
					     gets the platform's own picker, which on a phone is a
					     scrollable wheel rather than a list to hunt through. -->
					<select
						v-model="neighbour"
						class="h-12 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none focus:ring-2 focus:ring-outline-gray-3"
					>
						<option v-if="!neighbours.length" :value="null">
							No neighbour shops set up
						</option>
						<option v-for="n in neighbours" :key="n.name" :value="n.name">
							{{ n.name }}
						</option>
					</select>
				</div>

				<div class="grid grid-cols-3 gap-3">
					<div>
						<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">
							Selling
						</label>
						<input
							v-model.number="qty"
							type="number"
							min="1"
							inputmode="numeric"
							class="tabular h-12 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-lg font-semibold text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none focus:ring-2 focus:ring-outline-gray-3"
							@focus="$event.target.select()"
						/>
					</div>
					<!-- Separate from what is sold, because the shop next door sells a
					     carton and the customer wants two. Defaults to the sell
					     quantity, so leaving it alone behaves exactly as before. -->
					<div>
						<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">
							Buying
						</label>
						<input
							v-model.number="buyQty"
							type="number"
							:min="qty"
							inputmode="numeric"
							class="tabular h-12 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-lg font-semibold text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none focus:ring-2 focus:ring-outline-gray-3"
							@focus="$event.target.select()"
						/>
					</div>
					<div>
						<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">
							Their price
						</label>
						<input
							v-model="buyRate"
							type="number"
							inputmode="decimal"
							class="tabular h-12 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-lg font-semibold text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none focus:ring-2 focus:ring-outline-gray-3"
							@focus="$event.target.select()"
						/>
					</div>
				</div>

				<!-- Margin up front. Buying above your own shelf price is a real
				     mistake in a rush, so it is surfaced before confirming. -->
				<div
					class="flex items-center justify-between rounded-xl px-4 py-3"
					:class="margin >= 0 ? 'bg-surface-green-2' : 'bg-surface-red-2'"
				>
					<div>
						<div
							class="text-p-sm font-medium"
							:class="margin >= 0 ? 'text-ink-green-3' : 'text-ink-red-3'"
						>
							{{ margin >= 0 ? 'Margin on this line' : 'You would lose money' }}
						</div>
						<div class="tabular mt-0.5 text-p-xs text-ink-gray-6">
							Sell {{ fmtMoneyShort(sellTotal) }} · paying
							{{ fmtMoneyShort(costTotal) }}
							<template v-if="keptQty > 0">
								· {{ keptQty }} stays on the shelf
							</template>
						</div>
					</div>
					<div
						class="tabular text-2xl font-semibold"
						:class="margin >= 0 ? 'text-ink-green-3' : 'text-ink-red-3'"
					>
						{{ fmtMoney(margin) }}
					</div>
				</div>

				<!-- Off by default: shops next door usually settle weekly, and a
				     payment recorded here that never happened leaves the drawer
				     short by exactly this much at closing. -->
				<label
					class="flex min-h-touch cursor-pointer items-center gap-3 rounded-xl border border-outline-gray-2 px-3.5 py-3"
				>
					<input
						v-model="paidNow"
						type="checkbox"
						class="h-5 w-5 shrink-0 rounded border-outline-gray-3 text-ink-gray-8 focus:ring-outline-gray-3"
					/>
					<span class="min-w-0 flex-1">
						<span class="block text-p-base font-medium text-ink-gray-9">
							Paid them now
						</span>
						<span class="block text-p-xs text-ink-gray-5">
							{{
								paidNow
									? `${fmtMoney(costTotal)} comes out of the drawer`
									: 'Leave off if you settle at the end of the week'
							}}
						</span>
					</span>
				</label>

				<button
					class="min-h-touch w-full rounded-xl bg-surface-gray-7 py-4 text-p-lg font-semibold text-ink-white transition-all active:scale-[0.98] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
					:disabled="!canSource"
					@click="submitSource"
				>
					Add to sale
				</button>
			</template>

			<!-- Step 2b: request a transfer from another store -->
			<template v-else>
				<div>
					<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">
						Request from
					</label>
					<div class="flex flex-col gap-2">
						<button
							v-for="w in warehouses.filter((x) => !x.is_default)"
							:key="w.name"
							class="min-h-touch rounded-lg border px-3 py-2.5 text-left text-p-base transition-colors"
							:class="
								warehouse === w.name
									? 'border-outline-gray-4 bg-surface-gray-3 font-medium text-ink-gray-9'
									: 'border-outline-gray-2 bg-surface-white text-ink-gray-7 hover:bg-surface-gray-2'
							"
							@click="warehouse = w.name"
						>
							{{ w.label }}
						</button>
					</div>
				</div>

				<div>
					<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">Quantity</label>
					<input
						v-model.number="qty"
						type="number"
						min="1"
						inputmode="numeric"
						class="tabular h-12 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-lg font-semibold text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none focus:ring-2 focus:ring-outline-gray-3"
						@focus="$event.target.select()"
					/>
				</div>

				<p class="text-p-sm text-ink-gray-5">
					A material request is raised and posted to the staff WhatsApp group. This does
					not add anything to the current sale.
				</p>

				<button
					class="min-h-touch w-full rounded-xl bg-surface-gray-7 py-4 text-p-lg font-semibold text-ink-white transition-all active:scale-[0.98] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
					:disabled="!canRequest"
					@click="submitTransfer"
				>
					Send request
				</button>
			</template>
		</div>
	</BottomSheet>
</template>
