<script setup>
import LucideLayoutGrid from '~icons/lucide/layout-grid'

defineProps({
	categories: { type: Array, required: true },
	modelValue: { type: String, default: null },
	counts: { type: Object, default: () => ({}) },
	total: { type: Number, default: 0 },
	/** 'rail' = vertical sidebar (desktop), 'chips' = horizontal scroller. */
	variant: { type: String, default: 'chips' },
})

const emit = defineEmits(['update:modelValue'])
</script>

<template>
	<!-- Desktop: a persistent vertical rail. Categories never move, so muscle
	     memory builds up over a shift. -->
	<nav
		v-if="variant === 'rail'"
		class="pos-scroll flex w-52 shrink-0 flex-col gap-0.5 border-r border-outline-gray-2 bg-surface-white p-2"
	>
		<button
			class="flex min-h-touch items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-p-base transition-colors"
			:class="
				modelValue === null
					? 'bg-surface-gray-3 font-medium text-ink-gray-9'
					: 'text-ink-gray-7 hover:bg-surface-gray-2'
			"
			@click="emit('update:modelValue', null)"
		>
			<span class="flex items-center gap-2.5">
				<LucideLayoutGrid class="h-[18px] w-[18px] shrink-0" />
				All items
			</span>
			<span class="tabular text-p-xs text-ink-gray-5">{{ total }}</span>
		</button>

		<div class="my-1 h-px bg-surface-gray-3" />

		<button
			v-for="cat in categories"
			:key="cat.name"
			class="flex min-h-touch items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-p-base transition-colors"
			:class="
				modelValue === cat.name
					? 'bg-surface-gray-3 font-medium text-ink-gray-9'
					: 'text-ink-gray-7 hover:bg-surface-gray-2'
			"
			@click="emit('update:modelValue', cat.name)"
		>
			<span class="truncate">{{ cat.name }}</span>
			<span class="tabular shrink-0 text-p-xs text-ink-gray-5">
				{{ counts[cat.name] || 0 }}
			</span>
		</button>
	</nav>

	<!-- Tablet & mobile: horizontal chips. Scrolls under the thumb, keeps the
	     grid full-width where screen space is scarce. -->
	<nav
		v-else
		class="no-scrollbar flex shrink-0 gap-2 overflow-x-auto border-b border-outline-gray-2 bg-surface-white px-3 py-2 sm:px-4"
	>
		<button
			class="min-h-touch shrink-0 whitespace-nowrap rounded-full px-4 text-p-base transition-colors"
			:class="
				modelValue === null
					? 'bg-surface-gray-7 font-medium text-ink-white'
					: 'bg-surface-gray-2 text-ink-gray-7 active:bg-surface-gray-3'
			"
			@click="emit('update:modelValue', null)"
		>
			All
		</button>
		<button
			v-for="cat in categories"
			:key="cat.name"
			class="min-h-touch shrink-0 whitespace-nowrap rounded-full px-4 text-p-base transition-colors"
			:class="
				modelValue === cat.name
					? 'bg-surface-gray-7 font-medium text-ink-white'
					: 'bg-surface-gray-2 text-ink-gray-7 active:bg-surface-gray-3'
			"
			@click="emit('update:modelValue', cat.name)"
		>
			{{ cat.name }}
		</button>
	</nav>
</template>
