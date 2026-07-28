<script setup>
import { computed } from 'vue'
import { fmtMoneyShort } from '@/utils/format'
import LucideMinus from '~icons/lucide/minus'
import LucidePlus from '~icons/lucide/plus'
import LucideTrash2 from '~icons/lucide/trash-2'

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
				<span class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" :class="dot" />
				<span class="line-clamp-2 min-w-0 text-p-sm font-medium leading-snug text-ink-gray-8">
					{{ item.item_name }}
				</span>
			</div>
			<span class="tabular pl-3 text-p-xs text-ink-gray-6">
				KES {{ fmtMoneyShort(item.price).replace(/^\D+/, '') }}
			</span>
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
