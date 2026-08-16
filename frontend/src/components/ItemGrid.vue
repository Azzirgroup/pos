<script setup>
import ItemCell from './ItemCell.vue'
import LucideSearchX from '~icons/lucide/search-x'

defineProps({
	items: { type: Array, required: true },
	cartQtys: { type: Object, default: () => ({}) },
	query: { type: String, default: '' },
	/** Draw product photos, per the shop's setting. See `ItemCell`. */
	showImages: { type: Boolean, default: false },
})

defineEmits(['add', 'setQty', 'remove'])
</script>

<template>
	<div class="pos-scroll min-h-0 flex-1 bg-surface-gray-1">
		<div v-if="items.length" class="p-2 sm:p-3">
			<!-- Dense auto-fill grid of flat cells, per the reference design. It
			     reflows continuously as the cart panel appears, so there is no
			     width at which cells are stretched or cramped.

			     Wider cells when photos are on. The 160px track is sized for two
			     lines of product name, and a photo squeezed into it is a letterbox
			     — the point of turning photos on is that staff recognise the
			     packaging, which needs the picture to be big enough to recognise.
			     A shop with photos off keeps the denser grid, which is what it is
			     for. -->
			<div
				class="grid gap-1.5"
				:style="{
					gridTemplateColumns: `repeat(auto-fill, minmax(${showImages ? 190 : 160}px, 1fr))`,
				}"
			>
				<ItemCell
					v-for="item in items"
					:key="item.item_code"
					:item="item"
					:in-cart="cartQtys[item.item_code] || 0"
					:show-image="showImages"
					@add="$emit('add', $event)"
					@set-qty="$emit('setQty', $event)"
					@remove="$emit('remove', $event)"
				/>
			</div>
		</div>

		<div v-else class="grid h-full place-items-center p-8">
			<div class="flex max-w-xs flex-col items-center gap-3 text-center">
				<div class="grid h-12 w-12 place-items-center rounded-full bg-surface-gray-3">
					<LucideSearchX class="h-5 w-5 text-ink-gray-5" />
				</div>
				<div>
					<div class="text-p-base font-medium text-ink-gray-8">No items found</div>
					<div class="mt-1 text-p-sm text-ink-gray-5">
						<template v-if="query">
							Nothing matches “{{ query }}”. Check the spelling or scan the barcode.
						</template>
						<template v-else> This category is empty. </template>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
