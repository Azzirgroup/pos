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
})

const emit = defineEmits(['update:modelValue', 'request-transfer', 'source', 'sell-anyway'])

// 'menu' → pick an approach; the other two are the detail forms.
const mode = ref('menu')
const qty = ref(1)
const warehouse = ref(null)
const neighbour = ref(null)
const buyRate = ref('')

watch(
	() => props.modelValue,
	(open) => {
		if (!open) return
		mode.value = 'menu'
		qty.value = 1
		warehouse.value = props.warehouses.find((w) => !w.is_default)?.name || null
		neighbour.value = props.neighbours[0]?.name || null
		// Seed with the shelf price so the cashier only edits when the neighbour
		// quotes something different.
		buyRate.value = props.item ? String(props.item.price) : ''
	},
)

const buyRateNum = computed(() => Number(buyRate.value) || 0)
const sellTotal = computed(() => round2((props.item?.price || 0) * qty.value))
const costTotal = computed(() => round2(buyRateNum.value * qty.value))
const margin = computed(() => round2(sellTotal.value - costTotal.value))

const canSource = computed(() => neighbour.value && qty.value > 0 && buyRateNum.value > 0)
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
	emit('sell-anyway', { item: props.item, qty: 1 })
	close()
}

function submitSource() {
	if (!canSource.value) return
	emit('source', {
		item: props.item,
		qty: qty.value,
		supplier: neighbour.value,
		buyRate: buyRateNum.value,
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
						<span
							class="rounded px-1.5 py-0.5 font-medium"
							:class="
								item.stock <= 0
									? 'bg-surface-red-2 text-ink-red-3'
									: 'bg-surface-amber-2 text-ink-amber-3'
							"
						>
							{{ item.stock <= 0 ? 'Out of stock' : `${item.stock} left` }}
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
					<div class="flex flex-col gap-2">
						<button
							v-for="n in neighbours"
							:key="n.name"
							class="min-h-touch rounded-lg border px-3 py-2.5 text-left text-p-base transition-colors"
							:class="
								neighbour === n.name
									? 'border-outline-gray-4 bg-surface-gray-3 font-medium text-ink-gray-9'
									: 'border-outline-gray-2 bg-surface-white text-ink-gray-7 hover:bg-surface-gray-2'
							"
							@click="neighbour = n.name"
						>
							{{ n.name }}
						</button>
					</div>
				</div>

				<div class="grid grid-cols-2 gap-3">
					<div>
						<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">
							Quantity
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
							Sell {{ fmtMoneyShort(sellTotal) }} · cost
							{{ fmtMoneyShort(costTotal) }}
						</div>
					</div>
					<div
						class="tabular text-2xl font-semibold"
						:class="margin >= 0 ? 'text-ink-green-3' : 'text-ink-red-3'"
					>
						{{ fmtMoney(margin) }}
					</div>
				</div>

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
