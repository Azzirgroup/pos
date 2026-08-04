<script setup>
import { computed, ref, watch, nextTick } from 'vue'
import { storeToRefs } from 'pinia'
import { useCartStore } from '@/stores/cart'
import { fmtMoney, fmtMoneyShort } from '@/utils/format'
import CartLine from './CartLine.vue'
import LucideShoppingBag from '~icons/lucide/shopping-bag'
import LucideUserPlus from '~icons/lucide/user-plus'
import LucidePause from '~icons/lucide/pause'
import LucideUndo from '~icons/lucide/undo-2'
import LucideTrash2 from '~icons/lucide/trash-2'

defineProps({
	/** Hides the panel's own header when rendered inside the mobile sheet. */
	embedded: { type: Boolean, default: false },
	/** From the active POS Profile — whether a cashier can override a line's rate. */
	allowRateChange: { type: Boolean, default: false },
	/** From the active POS Profile — whether a cashier can apply a discount. */
	allowDiscountChange: { type: Boolean, default: false },
})

/**
 * Quantity changes are emitted rather than applied.
 *
 * They used to go straight to the store, which meant the `+` beside a line —
 * the control most likely to push a quantity past what is on the shelf — was
 * the one that never checked. The view that owns the out-of-stock sheet decides
 * now; this panel only says what the cashier pressed.
 */
const emit = defineEmits(['pay', 'hold', 'pickCustomer', 'inc', 'dec', 'setQty', 'setUom'])

const cart = useCartStore()
const {
	lines,
	lastTouched,
	count,
	isEmpty,
	grossTotal,
	discountAmount,
	total,
	taxAmount,
	sourcedLines,
	sourcedCost,
	sourcedMargin,
} = storeToRefs(cart)

/**
 * The hold button becomes an undo button once there is nothing left to hold.
 *
 * Only with an empty cart: with items in it, "hold" is unambiguous, and turning
 * the same control into a restore that would have to merge two carts is a worse
 * trade than asking the cashier to finish or clear the one in front of them.
 */
const canUnhold = computed(() => isEmpty.value && cart.held.length > 0)

const scroller = ref(null)

// Keep the newest line in view. In a long cart the cashier otherwise has no
// feedback that a scan at the bottom actually registered.
watch(
	() => [lines.value.length, lastTouched.value],
	async () => {
		await nextTick()
		const el = scroller.value
		if (el) el.scrollTop = el.scrollHeight
	},
)
</script>

<template>
	<aside class="flex min-h-0 w-full flex-col border-outline-gray-2 bg-surface-white">
		<!-- Header -->
		<div
			v-if="!embedded"
			class="flex shrink-0 items-center justify-between gap-2 border-b border-outline-gray-2 px-3 py-2.5"
		>
			<button
				class="flex min-h-touch min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-surface-gray-2"
				@click="emit('pickCustomer')"
			>
				<LucideUserPlus class="h-4 w-4 shrink-0 text-ink-gray-5" />
				<span class="truncate text-p-sm text-ink-gray-7">
					{{ cart.customer || 'Walk-in customer' }}
				</span>
			</button>
			<span class="tabular shrink-0 text-p-xs text-ink-gray-5">
				{{ count }} {{ count === 1 ? 'item' : 'items' }}
			</span>
		</div>

		<!-- Lines -->
		<div v-if="!isEmpty" ref="scroller" class="pos-scroll min-h-0 flex-1 divide-y divide-outline-gray-1 p-1.5">
			<CartLine
				v-for="line in lines"
				:key="line.id"
				:line="line"
				:line-total="cart.lineTotal(line)"
				:highlight="lastTouched === line.id"
				:allow-rate-change="allowRateChange"
				@inc="emit('inc', $event)"
				@dec="emit('dec', $event)"
				@remove="cart.remove"
				@set-qty="(id, qty) => emit('setQty', id, qty)"
				@set-uom="(id, uom) => emit('setUom', id, uom)"
				@set-rate="cart.setRate"
			/>
		</div>

		<!-- Empty -->
		<div v-else class="grid min-h-0 flex-1 place-items-center p-6">
			<div class="flex flex-col items-center gap-3 text-center">
				<div class="grid h-12 w-12 place-items-center rounded-full bg-surface-gray-2">
					<LucideShoppingBag class="h-5 w-5 text-ink-gray-4" />
				</div>
				<div>
					<div class="text-p-base font-medium text-ink-gray-7">Cart is empty</div>
					<div class="mt-1 text-p-sm text-ink-gray-5">Scan or tap an item to start</div>
				</div>
			</div>
		</div>

		<!-- Totals & pay -->
		<div class="pb-safe shrink-0 border-t border-outline-gray-2 bg-surface-white px-3 pt-3">
			<!-- Only shown when the sale involves neighbour-sourced goods: what we
			     owe next door, and what we actually make on it. -->
			<div
				v-if="sourcedLines.length"
				class="tabular mb-2.5 flex items-center justify-between rounded-lg bg-surface-green-2 px-3 py-2 text-p-xs"
			>
				<span class="text-ink-gray-7">
					Owed to neighbours
					<span class="font-semibold">{{ fmtMoneyShort(sourcedCost) }}</span>
				</span>
				<span class="font-semibold text-ink-green-3">
					+{{ fmtMoneyShort(sourcedMargin) }} margin
				</span>
			</div>

			<dl class="tabular space-y-1.5 text-p-sm">
				<div class="flex justify-between text-ink-gray-6">
					<dt>Subtotal</dt>
					<dd>{{ fmtMoneyShort(grossTotal) }}</dd>
				</div>
				<!-- A whole-sale discount, on top of anything already taken off a
				     line. Always editable rather than hidden behind a button: the
				     common case is a manager saying "knock off fifty bob" once the
				     cart is already full, not planned before the first item is
				     scanned. -->
				<div
					v-if="allowDiscountChange"
					class="flex items-center justify-between"
					:class="discountAmount ? 'text-ink-amber-3' : 'text-ink-gray-6'"
				>
					<dt><label for="cart-discount">Discount</label></dt>
					<dd class="flex items-center gap-1">
						<span v-if="discountAmount">−</span>
						<input
							id="cart-discount"
							:value="cart.discount || ''"
							type="number"
							min="0"
							:max="grossTotal"
							step="0.01"
							inputmode="decimal"
							placeholder="0"
							:disabled="isEmpty"
							class="tabular h-6 w-20 rounded border border-outline-gray-2 bg-surface-white px-1 text-right text-p-xs font-medium focus:border-outline-gray-4 focus:outline-none disabled:opacity-50"
							:class="discountAmount ? 'text-ink-amber-3' : 'text-ink-gray-8'"
							@focus="$event.target.select()"
							@change="cart.setDiscount($event.target.value)"
						/>
					</dd>
				</div>
				<div class="flex justify-between text-ink-gray-5">
					<dt>VAT {{ Math.round(cart.vatRate * 100) }}% (incl.)</dt>
					<dd>{{ fmtMoneyShort(taxAmount) }}</dd>
				</div>
			</dl>

			<div
				class="tabular mt-2.5 flex items-baseline justify-between border-t border-outline-gray-2 pt-2.5"
			>
				<span class="text-p-base font-medium text-ink-gray-7">Total</span>
				<span class="text-p-3xl font-semibold tracking-tight text-ink-gray-9">
					{{ fmtMoney(total) }}
				</span>
			</div>

			<div class="mt-3 flex gap-2 pb-3">
				<button
					class="grid h-12 w-12 shrink-0 place-items-center rounded-xl border border-outline-gray-2 text-ink-gray-6 transition-colors hover:bg-surface-gray-2 disabled:opacity-40"
					:disabled="isEmpty"
					aria-label="Clear cart"
					@click="cart.clear()"
				>
					<LucideTrash2 class="h-[18px] w-[18px]" />
				</button>
				<!-- The same button undoes itself. A cashier who parks a sale by
				     accident is looking at an empty cart with the customer still
				     standing there, and the fix has to be where the mistake was —
				     not in a list of held tickets they have to go and find. -->
				<button
					class="grid h-12 w-12 shrink-0 place-items-center rounded-xl border transition-colors disabled:opacity-40"
					:class="
						canUnhold
							? 'border-outline-amber-2 bg-surface-amber-1 text-ink-amber-3 hover:bg-surface-amber-2'
							: 'border-outline-gray-2 text-ink-gray-6 hover:bg-surface-gray-2'
					"
					:disabled="isEmpty && !canUnhold"
					:aria-label="canUnhold ? 'Undo hold' : 'Hold sale'"
					:title="canUnhold ? `Bring ${cart.held[cart.held.length - 1].id} back` : 'Hold sale'"
					@click="emit('hold')"
				>
					<component :is="canUnhold ? LucideUndo : LucidePause" class="h-[18px] w-[18px]" />
				</button>
				<!-- The pay button carries the amount: the cashier reads one number
				     and presses one target, and it is the largest thing on screen. -->
				<button
					class="flex h-12 flex-1 items-center justify-between gap-2 rounded-xl bg-surface-gray-7 px-4 text-ink-white transition-all hover:bg-surface-gray-6 active:scale-[0.98] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
					:disabled="isEmpty"
					@click="emit('pay')"
				>
					<span class="text-p-base font-semibold">Pay</span>
					<span class="tabular text-p-lg font-semibold">{{ fmtMoneyShort(total) }}</span>
				</button>
			</div>
		</div>
	</aside>
</template>
