<script setup>
import { computed } from 'vue'
import { fmtMoneyShort } from '@/utils/format'

const props = defineProps({
	item: { type: Object, required: true },
	/** Qty already in the cart — shown as a pip so the cashier can see it at a glance. */
	inCart: { type: Number, default: 0 },
})

defineEmits(['add'])

// For a shade variant the swatch shows the shade name itself — "Ruby" tells the
// cashier far more than "ML", and three lipsticks must never look alike.
const swatchLabel = computed(() => {
	if (props.item.variant) return props.item.variant
	return props.item.item_name
		.replace(/[^a-zA-Z ]/g, '')
		.split(' ')
		.filter(Boolean)
		.slice(0, 2)
		.map((w) => w[0].toUpperCase())
		.join('')
})

const isVariant = computed(() => Boolean(props.item.variant))

// Swatch instead of a photo: renders instantly, never 404s, and stays legible
// on a cheap till screen. Real images can replace this without layout change.
const swatch = computed(() => ({
	background: `linear-gradient(140deg, hsl(${props.item.hue} 62% 92%), hsl(${(props.item.hue + 40) % 360} 58% 84%))`,
	color: `hsl(${props.item.hue} 45% 28%)`,
}))

const stockTone = computed(() => {
	if (props.item.stock <= 0) return 'out'
	if (props.item.stock <= 5) return 'low'
	return 'ok'
})
</script>

<template>
	<button
		class="group relative flex flex-col overflow-hidden rounded-xl border border-outline-gray-2 bg-surface-white text-left transition-all duration-100 hover:border-outline-gray-3 hover:shadow-sm active:scale-[0.97] active:shadow-none"
		:class="inCart ? 'ring-2 ring-outline-gray-4' : ''"
		@click="$emit('add', item)"
	>
		<!-- Swatch. Shorter aspect than a product photo would need — vertical space
		     on the grid is better spent on more rows than on decoration. -->
		<div
			class="relative grid aspect-[2/1] place-items-center px-2"
			:style="swatch"
		>
			<span
				class="line-clamp-2 text-center font-semibold tracking-tight"
				:class="isVariant ? 'text-p-base leading-tight' : 'text-p-2xl'"
			>
				{{ swatchLabel }}
			</span>

			<!-- Qty already in cart -->
			<span
				v-if="inCart"
				class="tabular absolute right-1.5 top-1.5 grid h-6 min-w-6 place-items-center rounded-full bg-surface-gray-7 px-1.5 text-p-xs font-semibold text-ink-white shadow-sm"
			>
				{{ inCart }}
			</span>

			<!-- Stock signal. Only shown when it needs action. -->
			<span
				v-if="stockTone !== 'ok'"
				class="absolute bottom-1.5 left-1.5 rounded px-1.5 py-0.5 text-p-xs font-medium"
				:class="
					stockTone === 'out'
						? 'bg-surface-red-2 text-ink-red-3'
						: 'bg-surface-amber-2 text-ink-amber-3'
				"
			>
				{{ stockTone === 'out' ? 'Out' : `${item.stock} left` }}
			</span>
		</div>

		<!-- Detail -->
		<div class="flex min-w-0 flex-1 flex-col gap-1 p-2.5">
			<div class="text-p-xs uppercase tracking-wide text-ink-gray-5">
				{{ item.brand }}
			</div>
			<!-- Base name only: the shade already reads large on the swatch, so
			     repeating it here would just cost a line of height. -->
			<div class="line-clamp-2 text-p-sm font-medium leading-snug text-ink-gray-8">
				{{ item.base_name || item.item_name }}
			</div>
			<div class="tabular mt-auto pt-1 text-p-lg font-semibold text-ink-gray-9">
				{{ fmtMoneyShort(item.price) }}
			</div>
		</div>
	</button>
</template>
