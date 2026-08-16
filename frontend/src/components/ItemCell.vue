<script setup>
import { computed, ref, watch } from 'vue'
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
	/**
	 * Draw the product's photo properly, rather than as the 32px corner square.
	 *
	 * Off by default, and a shop-wide setting rather than a per-cashier one: a
	 * grid of photos is worth several times a grid of names to staff who know the
	 * packaging and not the product code, and worth nothing at all to a shop that
	 * has never uploaded any — where it would just make every cell taller and fit
	 * fewer products on screen. See `show_item_images` in the till settings.
	 */
	showImage: { type: Boolean, default: false },
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
 * A picture where the item has one, the shop's own mark where it does not.
 *
 * Kept to a 32px square deliberately. This grid earns its speed from density —
 * a cashier scanning sixty products needs them all on one screen — so the
 * thumbnail is a recognition aid at the edge of the cell, not a product photo
 * the layout is built around.
 *
 * ## Why a broken photo and a missing one look the same
 *
 * `Item.image` is a path the shop's data carries, and it is routinely a path to
 * a file that is not there: items imported from another site keep the old URL,
 * and a file uploaded as **private** is served from `/private/files/…` while the
 * field still reads `/files/…`, so the browser gets a 404 or a login page. On
 * Frappe Cloud this shows up as every photo attempting to load and failing.
 *
 * Nothing in the till can repair that — the file genuinely is not at that
 * address — so the only question is what the cell does about it. It used to
 * drop the band entirely, which left that one cell shorter than its neighbours
 * and the grid visibly ragged, reading as a rendering bug rather than as a
 * missing photo. Now the band stays and shows the shop's mark: same height,
 * same baseline, and a cell that plainly has no picture rather than one that
 * looks broken.
 */
const LOGO = '/assets/cosmestics/images/logo.svg'

const broken = ref(false)
const thumbnail = computed(() => (props.item.image && !broken.value ? props.item.image : null))

/**
 * Give a repaired photo another chance.
 *
 * The grid keys cells by item code, so this component survives a catalogue
 * refresh — and with it a `broken` flag set an hour ago, against an image the
 * shop has since fixed. Watching the path rather than the item means the reset
 * happens exactly when there is something new to try.
 */
watch(
	() => props.item.image,
	() => {
		broken.value = false
	},
)

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
		class="flex flex-col overflow-hidden rounded-md border bg-surface-white text-left transition-colors"
		:class="
			inCart
				? 'border-outline-gray-4 ring-1 ring-outline-gray-3'
				: 'border-outline-gray-2 hover:border-outline-gray-3 hover:bg-surface-gray-1'
		"
		@click="emit('add', item)"
	>
		<!-- The photo, when the shop has asked for photos and this product has
		     one. A band across the top rather than a bigger corner square: at a
		     glance across sixty cells the eye is matching packaging, and a 32px
		     crop of a bottle is not something anyone recognises. Fixed height so
		     the grid stays on one baseline whatever shape the uploads are. -->
		<div
			v-if="showImage"
			class="relative h-20 w-full shrink-0 overflow-hidden bg-surface-gray-2"
		>
			<img
				v-if="thumbnail"
				:src="thumbnail"
				alt=""
				class="h-full w-full object-cover"
				loading="lazy"
				@error="broken = true"
			/>
			<!-- No photo, or one whose file is not where the item says it is. The
			     shop's own mark, muted: it fills the band so the grid keeps one
			     baseline, without pretending to be a picture of the product. -->
			<div v-else class="grid h-full w-full place-items-center bg-surface-gray-1">
				<img
					:src="LOGO"
					alt=""
					aria-hidden="true"
					class="h-9 w-9 opacity-25 grayscale"
					draggable="false"
				/>
			</div>
		</div>

		<div class="flex min-w-0 flex-1 flex-col gap-0.5 px-2.5 py-2">
			<div class="flex items-start gap-1.5">
				<!-- Always the category icon, never the photo: the photo has one home,
				     the band above, and it appears only when the shop has asked for
				     photos. A 32px crop shown regardless would make the setting a
				     half-switch — off, but still pictures. This square exists to carry
				     the availability dot, which every cell needs. -->
				<span class="relative mt-0.5 shrink-0">
					<span
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
		<!-- The three controls are what this row is *for*, so they never give up
		     width: `shrink-0` on them and `min-w-0` on the running total means a
		     long total truncates instead of shoving the buttons out of the cell.
		     They used to overflow — the cell does not clip, so the `+` and the bin
		     ended up drawn over the next cell along, which paints after this one
		     and therefore swallowed the tap. That is why adding a quantity
		     sometimes did nothing: the press was landing on the neighbouring
		     product, not on the button under the finger. -->
		<div
			v-if="inCart"
			class="flex items-center justify-between gap-1 border-t border-outline-gray-2 px-1.5 py-1"
			@click.stop
		>
			<span class="tabular min-w-0 truncate pl-1 text-p-xs font-medium text-ink-gray-7">
				{{ inCart }}: {{ Math.round(inCart * item.price).toLocaleString() }}
			</span>
			<div class="flex shrink-0 items-center gap-0.5">
				<span
					class="grid h-6 w-6 shrink-0 cursor-pointer place-items-center rounded text-ink-gray-6 hover:bg-surface-gray-3"
					@click="emit('setQty', { item, qty: inCart - 1 })"
				>
					<LucideMinus class="h-3 w-3" />
				</span>
				<span
					class="grid h-6 w-6 shrink-0 cursor-pointer place-items-center rounded text-ink-gray-6 hover:bg-surface-gray-3"
					@click="emit('setQty', { item, qty: inCart + 1 })"
				>
					<LucidePlus class="h-3 w-3" />
				</span>
				<span
					class="grid h-6 w-6 shrink-0 cursor-pointer place-items-center rounded text-ink-red-3 hover:bg-surface-red-2"
					@click="emit('remove', item)"
				>
					<LucideTrash2 class="h-3 w-3" />
				</span>
			</div>
		</div>
	</button>
</template>
