<script setup>
import ItemCard from './ItemCard.vue'
import LucideSearchX from '~icons/lucide/search-x'

defineProps({
	items: { type: Array, required: true },
	cartQtys: { type: Object, default: () => ({}) },
	query: { type: String, default: '' },
})

defineEmits(['add'])
</script>

<template>
	<div class="pos-scroll min-h-0 flex-1 bg-surface-gray-1">
		<div v-if="items.length" class="p-3 sm:p-4">
			<!-- auto-fill rather than fixed breakpoint columns: the grid reflows
			     continuously as the cart panel appears/disappears, so there is no
			     awkward width where cards are stretched or cramped. -->
			<div
				class="grid gap-2.5 sm:gap-3"
				style="grid-template-columns: repeat(auto-fill, minmax(148px, 1fr))"
			>
				<ItemCard
					v-for="item in items"
					:key="item.item_code"
					:item="item"
					:in-cart="cartQtys[item.item_code] || 0"
					@add="$emit('add', $event)"
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
