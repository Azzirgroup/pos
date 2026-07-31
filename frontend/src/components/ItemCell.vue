<script setup>
import { computed, ref } from 'vue'
import { fmtMoneyShort } from '@/utils/format'
import LucideMinus from '~icons/lucide/minus'
import LucidePlus from '~icons/lucide/plus'
import LucideTrash2 from '~icons/lucide/trash-2'
import LucideSprayCan from '~icons/lucide/spray-can'
import LucideDroplet from '~icons/lucide/droplet'
import LucideScissors from '~icons/lucide/scissors'
import LucidePill from '~icons/lucide/pill'
import LucideShirt from '~icons/lucide/shirt'
import LucideCookie from '~icons/lucide/cookie'
import LucidePackage from '~icons/lucide/package'

const props = defineProps({
	item: { type: Object, required: true },
	inCart: { type: Number, default: 0 },
})

const emit = defineEmits(['add', 'setQty', 'remove'])

const out = computed(() => props.item.stock <= 0)
const low = computed(() => props.item.stock > 0 && props.item.stock <= 5)

/**
 * Availability as a coloured dot rather than a word. It has to be readable at a
 * glance across a grid of sixty items, and a dot costs no layout.
 */
const dot = computed(() => {
	if (out.value) return 'bg-surface-red-5'
	if (low.value) return 'bg-surface-amber-3'
	return 'bg-surface-green-3'
})

/**
 * The count in words a cashier uses. "Out" rather than "0" because the two are
 * read differently under pressure, and fractional quantities (grams, ml) are
 * rounded down — promising a customer 2.7 units of anything is not useful.
 *
 * Just the number otherwise: in a column headed by a price, beside a coloured
 * pill, "left" is the one part a cashier never reads.
 */
const stockLabel = computed(() => {
	const qty = Number(props.item.stock) || 0
	if (qty <= 0) return 'Out'
	return Math.floor(qty).toLocaleString()
})

/**
 * The balance carries its own background, not just coloured text.
 *
 * Text tone alone was too quiet to catch at a glance across a dense grid, and
 * it was the same weight as the price beside it. A filled pill separates the
 * two and makes "nearly out" visible without being read. Green stays the
 * quietest of the three — most items are in stock, and a grid where every cell
 * shouts says nothing.
 */
const stockTone = computed(() => {
	if (out.value) return 'bg-surface-red-2 text-ink-red-3'
	if (low.value) return 'bg-surface-amber-2 text-ink-amber-3'
	return 'bg-surface-green-2 text-ink-green-3'
})

/**
 * A picture where the item has one, an icon where it does not.
 *
 * Kept to a 32px square deliberately. This grid earns its speed from density —
 * a cashier scanning sixty products needs them all on one screen — so the
 * thumbnail is a recognition aid at the edge of the cell, not a product photo
 * the layout is built around.
 */
const broken = ref(false)
const thumbnail = computed(() => (props.item.image && !broken.value ? props.item.image : null))

/**
 * Fallback icon by category. Keyword-matched rather than an exact table of item
 * groups: every shop names its groups differently, and a wrong-but-plausible
 * icon is no worse than the generic one it replaces.
 */
const CATEGORY_ICONS = [
	[/perfume|spray|deodorant|fragrance|scent/, LucideSprayCan],
	[/lotion|oil|cream|moistur|serum|shampoo|gel|liquid/, LucideDroplet],
	[/hair|salon|razor|shav|comb|brush/, LucideScissors],
	[/pharma|medicine|drug|tablet|capsule|supplement/, LucidePill],
	[/cloth|wear|apparel|bag|shoe|acces/, LucideShirt],
	[/food|snack|cake|bake|drink|beverage/, LucideCookie],
]

const fallbackIcon = computed(() => {
	const haystack = `${props.item.category || ''} ${props.item.brand || ''}`.toLowerCase()
	return CATEGORY_ICONS.find(([pattern]) => pattern.test(haystack))?.[1] || LucidePackage
})
</script>

<template>
	<!-- Flat bordered cell, not a card: no image, no shadow, minimal padding. A
	     dense list shows three times as many items per screen, which is what a
	     cashier scanning for a product actually needs. -->
	<button
		class="flex flex-col rounded-md border bg-surface-white text-left transition-colors"
		:class="
			inCart
				? 'border-outline-gray-4 ring-1 ring-outline-gray-3'
				: 'border-outline-gray-2 hover:border-outline-gray-3 hover:bg-surface-gray-1'
		"
		@click="emit('add', item)"
	>
		<div class="flex min-w-0 flex-1 flex-col gap-0.5 px-2.5 py-2">
			<div class="flex items-start gap-1.5">
				<!-- Thumbnail carries the availability dot in its corner, so the two
				     share one column instead of each taking their own. -->
				<span class="relative mt-0.5 shrink-0">
					<img
						v-if="thumbnail"
						:src="thumbnail"
						alt=""
						class="h-8 w-8 rounded object-cover"
						loading="lazy"
						@error="broken = true"
					/>
					<span
						v-else
						class="grid h-8 w-8 place-items-center rounded bg-surface-gray-2 text-ink-gray-5"
					>
						<component :is="fallbackIcon" class="h-4 w-4" aria-hidden="true" />
					</span>
					<span
						class="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full ring-2 ring-white"
						:class="dot"
					/>
				</span>
				<span class="line-clamp-2 min-w-0 text-p-sm font-medium leading-snug text-ink-gray-8">
					{{ item.item_name }}
				</span>
			</div>
			<!-- Price and stock on one line. The dot alone said "low" but never how
			     low, and a cashier deciding whether to promise the last two units
			     needs the number, not a colour. -->
			<div class="flex items-baseline justify-between gap-1.5 pl-[38px]">
				<span class="tabular text-p-xs text-ink-gray-6">
					KES {{ fmtMoneyShort(item.price).replace(/^\D+/, '') }}
				</span>
				<span
					class="tabular shrink-0 rounded px-1.5 py-0.5 text-p-xs font-medium"
					:class="stockTone"
				>
					{{ stockLabel }}
				</span>
			</div>
		</div>

		<!-- Quantity controls only once the item is in the cart, mirroring the
		     reference: an untouched cell stays completely quiet. -->
		<div
			v-if="inCart"
			class="flex items-center justify-between gap-1 border-t border-outline-gray-2 px-1.5 py-1"
			@click.stop
		>
			<span class="tabular pl-1 text-p-xs font-medium text-ink-gray-7">
				{{ inCart }}: {{ Math.round(inCart * item.price).toLocaleString() }}
			</span>
			<div class="flex items-center gap-0.5">
				<span
					class="grid h-6 w-6 cursor-pointer place-items-center rounded text-ink-gray-6 hover:bg-surface-gray-3"
					@click="emit('setQty', { item, qty: inCart - 1 })"
				>
					<LucideMinus class="h-3 w-3" />
				</span>
				<span
					class="grid h-6 w-6 cursor-pointer place-items-center rounded text-ink-gray-6 hover:bg-surface-gray-3"
					@click="emit('setQty', { item, qty: inCart + 1 })"
				>
					<LucidePlus class="h-3 w-3" />
				</span>
				<span
					class="grid h-6 w-6 cursor-pointer place-items-center rounded text-ink-red-3 hover:bg-surface-red-2"
					@click="emit('remove', item)"
				>
					<LucideTrash2 class="h-3 w-3" />
				</span>
			</div>
		</div>
	</button>
</template>
