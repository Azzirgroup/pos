<script setup>
defineProps({
	title: { type: String, required: true },
	subtitle: { type: String, default: '' },
})
</script>

<template>
	<!-- Shared so every back-office screen has the same title block and the same
	     place for its filters, rather than each inventing a layout.

	     Two rows, because the things in them are different in kind. The title
	     line carries the one action that *creates* something; the row under it
	     carries the controls that narrow what is already there. Sharing a line
	     put "New supplier" immediately beside a search box and a period picker,
	     where the button a mis-tap reaches is the one that opens a form. -->
	<header class="shrink-0 border-b border-outline-gray-2 bg-surface-white px-4 py-2.5">
		<div class="flex flex-wrap items-center gap-3">
			<div class="min-w-0">
				<h1 class="text-p-base font-semibold text-ink-gray-9">{{ title }}</h1>
				<p v-if="subtitle" class="truncate text-p-xs text-ink-gray-5">{{ subtitle }}</p>
			</div>
			<div v-if="$slots.primary" class="ml-auto flex shrink-0 items-center gap-2">
				<slot name="primary" />
			</div>
		</div>

		<!-- Only takes vertical space when a screen actually has filters. -->
		<div v-if="$slots.actions" class="mt-2.5 flex flex-wrap items-center gap-2">
			<slot name="actions" />
		</div>
	</header>
</template>
