<script setup>
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { Dialog } from 'frappe-ui'
import { useCartStore } from '@/stores/cart'
import { fmtMoney, fmtMoneyShort, fmtQty } from '@/utils/format'
import LucideMinus from '~icons/lucide/minus'
import LucidePlus from '~icons/lucide/plus'
import LucideTrash2 from '~icons/lucide/trash-2'
import LucideShoppingBag from '~icons/lucide/shopping-bag'

/**
 * The whole cart at once, on the whole screen.
 *
 * The docked panel is 360px wide and shows perhaps six lines. That is the right
 * shape for the ordinary sale and the wrong one for the sale this exists for: a
 * trolley of thirty items, where the customer asks "what have you charged me
 * for?" and the only way to answer is to scroll a narrow column past them, or a
 * cashier checking a long basket against the goods on the counter before taking
 * money.
 *
 * So this is the same cart in a table — every line visible, with the numbers in
 * columns that line up so the eye can run down them. A wide screen has the room
 * and the panel was not using it.
 *
 * ## Why it edits rather than only shows
 *
 * "Preview" is what it is for, not what it is allowed to do. Finding the wrong
 * quantity is the *point* of reading the cart back, and a view that then makes
 * you close it and hunt for the same line in the narrow panel is a view that
 * gets used once. The controls are the same ones the panel has.
 *
 * Quantity changes are emitted, never applied here — exactly as `CartPanel`
 * does it. The view that owns the out-of-stock sheet decides whether a `+` is
 * allowed; a second component quietly writing to the store is how the one
 * control that skips the shelf check gets created.
 */
defineProps({
	modelValue: { type: Boolean, default: false },
	/** From the active POS Profile — whether a cashier can override a line's rate. */
	allowRateChange: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'pay', 'inc', 'dec', 'setQty', 'setUom'])

const cart = useCartStore()
const { lines, count, isEmpty, grossTotal, discountAmount, total, taxAmount } = storeToRefs(cart)

/** Numbered, because reading a long list back to a customer needs a place to
 *  keep your finger. */
const numbered = computed(() => lines.value.map((line, i) => ({ ...line, index: i + 1 })))

function close() {
	emit('update:modelValue', false)
}
</script>

<template>
	<Dialog
		:model-value="modelValue"
		:options="{ title: `Cart · ${count} ${count === 1 ? 'item' : 'items'}`, size: '5xl' }"
		@update:model-value="$event || close()"
	>
		<template #body-content>
			<div v-if="isEmpty" class="grid place-items-center py-16">
				<div class="flex flex-col items-center gap-3 text-center">
					<div class="grid h-12 w-12 place-items-center rounded-full bg-surface-gray-2">
						<LucideShoppingBag class="h-5 w-5 text-ink-gray-4" />
					</div>
					<div class="text-p-base font-medium text-ink-gray-7">Cart is empty</div>
				</div>
			</div>

			<!-- Scrolls inside itself rather than growing the dialog past the
			     viewport: the totals below have to stay on screen, since checking a
			     long cart is checking it *against* a total. -->
			<div v-else class="max-h-[58dvh] overflow-auto">
				<table class="w-full border-collapse text-p-sm">
					<thead class="sticky top-0 z-10 bg-surface-white">
						<tr class="border-b border-outline-gray-2 text-left text-p-xs text-ink-gray-5">
							<th class="w-8 py-2 pl-1 font-medium">#</th>
							<th class="py-2 font-medium">Item</th>
							<th class="w-28 py-2 text-right font-medium">Price</th>
							<th class="w-[136px] py-2 text-center font-medium">Qty</th>
							<th class="w-28 py-2 text-right font-medium">Total</th>
							<th class="w-10 py-2" />
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="line in numbered"
							:key="line.id"
							class="border-b border-outline-gray-1 last:border-b-0 hover:bg-surface-gray-1"
						>
							<td class="tabular py-2 pl-1 align-top text-p-xs text-ink-gray-4">
								{{ line.index }}
							</td>
							<td class="min-w-0 py-2 align-top">
								<div class="font-medium leading-snug text-ink-gray-8">
									{{ line.item_name }}
								</div>
								<div class="tabular mt-0.5 flex flex-wrap items-center gap-x-2 text-p-xs text-ink-gray-5">
									<span>{{ line.item_code }}</span>
									<span v-if="line.uom">· {{ line.uom }}</span>
									<!-- Named here as well as on the narrow panel: a sourced
									     line is one the shop does not own yet, and reading the
									     cart back is exactly when that matters. -->
									<span v-if="line.sourced" class="font-medium text-ink-green-3">
										· from {{ line.sourced.supplier }}
									</span>
									<span v-if="line.discountPct" class="font-medium text-ink-amber-3">
										· {{ line.discountPct }}% off
									</span>
								</div>
							</td>
							<td class="tabular py-2 text-right align-top">
								<input
									v-if="allowRateChange"
									:value="line.rate"
									type="number"
									min="0"
									step="0.01"
									inputmode="decimal"
									class="tabular h-8 w-24 rounded border border-outline-gray-2 bg-surface-white px-1.5 text-right text-p-sm text-ink-gray-8 focus:border-outline-gray-4 focus:outline-none"
									@focus="$event.target.select()"
									@change="cart.setRate(line.id, $event.target.value)"
								/>
								<span v-else class="text-ink-gray-6">{{ fmtMoneyShort(line.rate) }}</span>
							</td>
							<td class="py-2 align-top">
								<div class="flex items-center justify-center gap-1">
									<button
										class="grid h-8 w-8 shrink-0 place-items-center rounded border border-outline-gray-2 text-ink-gray-6 transition-colors hover:bg-surface-gray-2"
										:aria-label="`One less ${line.item_name}`"
										@click="emit('dec', line.id)"
									>
										<LucideMinus class="h-3.5 w-3.5" />
									</button>
									<input
										:value="fmtQty(line.qty)"
										type="number"
										min="0"
										step="any"
										inputmode="decimal"
										class="tabular h-8 w-14 rounded border border-outline-gray-2 bg-surface-white px-1 text-center text-p-sm font-medium text-ink-gray-8 focus:border-outline-gray-4 focus:outline-none"
										@focus="$event.target.select()"
										@change="emit('setQty', line.id, Number($event.target.value))"
									/>
									<button
										class="grid h-8 w-8 shrink-0 place-items-center rounded border border-outline-gray-2 text-ink-gray-6 transition-colors hover:bg-surface-gray-2"
										:aria-label="`One more ${line.item_name}`"
										@click="emit('inc', line.id)"
									>
										<LucidePlus class="h-3.5 w-3.5" />
									</button>
								</div>
							</td>
							<td class="tabular py-2 text-right align-top font-semibold text-ink-gray-9">
								{{ fmtMoneyShort(cart.lineTotal(line)) }}
							</td>
							<td class="py-2 pr-1 align-top">
								<button
									class="grid h-8 w-8 place-items-center rounded text-ink-red-3 transition-colors hover:bg-surface-red-2"
									:aria-label="`Remove ${line.item_name}`"
									@click="cart.remove(line.id)"
								>
									<LucideTrash2 class="h-3.5 w-3.5" />
								</button>
							</td>
						</tr>
					</tbody>
				</table>
			</div>

			<!-- The same four figures the panel shows, in the same order, so the two
			     views never look like they disagree about the sale. -->
			<dl
				v-if="!isEmpty"
				class="tabular mt-3 space-y-1 border-t border-outline-gray-2 pt-3 text-p-sm"
			>
				<div class="flex justify-between text-ink-blue-3">
					<dt class="font-medium text-ink-gray-6">Subtotal</dt>
					<dd class="font-medium">{{ fmtMoneyShort(grossTotal) }}</dd>
				</div>
				<div v-if="discountAmount" class="flex justify-between text-ink-amber-3">
					<dt class="font-medium text-ink-gray-6">Discount</dt>
					<dd class="font-medium">−{{ fmtMoneyShort(discountAmount) }}</dd>
				</div>
				<div class="flex justify-between">
					<dt class="text-ink-gray-6">VAT {{ Math.round(cart.vatRate * 100) }}% (incl.)</dt>
					<dd class="font-medium text-violet-600">{{ fmtMoneyShort(taxAmount) }}</dd>
				</div>
			</dl>
		</template>

		<template #actions>
			<div class="flex items-center gap-3">
				<div class="tabular mr-auto flex items-baseline gap-2">
					<span class="text-p-sm font-medium text-ink-gray-6">Total</span>
					<span class="text-p-2xl font-semibold tracking-tight text-ink-gray-9">
						{{ fmtMoney(total) }}
					</span>
				</div>
				<button
					class="min-h-touch rounded-xl border border-outline-gray-2 px-4 text-p-base font-medium text-ink-gray-7 transition-colors hover:bg-surface-gray-2"
					@click="close"
				>
					Back to till
				</button>
				<!-- Paying from here rather than sending the cashier back to the panel
				     to press the same button: they have just finished checking the
				     cart, which is the moment they are ready to charge it. -->
				<button
					class="flex min-h-touch items-center gap-2 rounded-xl bg-surface-gray-7 px-5 text-ink-white transition-all active:scale-[0.98] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
					:disabled="isEmpty"
					@click="emit('pay')"
				>
					<span class="text-p-base font-semibold">Pay</span>
					<span class="tabular text-p-lg font-semibold">{{ fmtMoneyShort(total) }}</span>
				</button>
			</div>
		</template>
	</Dialog>
</template>
