<script setup>
/**
 * Tabs within a screen.
 *
 * The same shape as `ModuleTabs`, which is the point: a reader should not have
 * to learn that tabs above the content and tabs inside it are different
 * controls. frappe-ui's `TabButtons` is a compact segmented pill with
 * half-pixel gaps — good for a two-way toggle, cramped for six departments, and
 * visibly a different control sitting next to ours.
 *
 * Takes the same `buttons` shape as `TabButtons` so swapping it in is a one-line
 * change at each call site.
 */
defineProps({
	/** [{ label, value }] */
	buttons: { type: Array, required: true },
	modelValue: { type: [String, Number, Boolean], default: null },
	/** Sits inside a card rather than under a page header: no rule beneath. */
	inset: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])
</script>

<template>
	<div
		class="flex shrink-0 items-center gap-4 overflow-x-auto"
		:class="inset ? 'py-1' : 'border-b border-outline-gray-2 px-4 py-2.5'"
	>
		<button
			v-for="b in buttons"
			:key="b.value ?? b.label"
			class="flex shrink-0 items-center gap-1.5 rounded-lg px-4 py-2 text-p-sm transition-colors"
			:class="
				modelValue === (b.value ?? b.label)
					? 'bg-surface-violet-1 font-medium text-violet-600 ring-1 ring-violet-200'
					: 'text-ink-gray-6 hover:bg-surface-gray-2 hover:text-ink-gray-8'
			"
			@click="emit('update:modelValue', b.value ?? b.label)"
		>
			{{ b.label }}
			<span
				v-if="b.badge"
				class="tabular rounded-full bg-surface-red-5 px-1.5 text-[10px] font-semibold text-ink-white"
			>
				{{ b.badge }}
			</span>
		</button>
	</div>
</template>
