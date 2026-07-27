<script setup>
import { watch, onUnmounted } from 'vue'

const props = defineProps({
	modelValue: { type: Boolean, default: false },
	title: { type: String, default: '' },
	/** Cap the sheet height on mobile; desktop uses a centred dialog instead. */
	tall: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])

function close() {
	emit('update:modelValue', false)
}

// Lock the page behind the sheet — without this, iOS scrolls the grid under
// the overlay while the cashier is trying to scroll the sheet.
watch(
	() => props.modelValue,
	(open) => {
		document.body.style.overflow = open ? 'hidden' : ''
	},
)

onUnmounted(() => {
	document.body.style.overflow = ''
})
</script>

<template>
	<Teleport to="body">
		<Transition
			enter-active-class="transition-opacity duration-150"
			leave-active-class="transition-opacity duration-150"
			enter-from-class="opacity-0"
			leave-to-class="opacity-0"
		>
			<div
				v-if="modelValue"
				class="fixed inset-0 z-40 bg-black/40"
				@click="close"
			/>
		</Transition>

		<Transition
			enter-active-class="transition-transform duration-200 ease-out"
			leave-active-class="transition-transform duration-150 ease-in"
			enter-from-class="translate-y-full sm:translate-y-4 sm:opacity-0"
			leave-to-class="translate-y-full sm:translate-y-4 sm:opacity-0"
		>
			<!-- Mobile: bottom sheet. sm+: centred dialog. One component, because
			     the content and behaviour are identical — only the framing differs. -->
			<div
				v-if="modelValue"
				role="dialog"
				aria-modal="true"
				class="fixed inset-x-0 bottom-0 z-50 flex flex-col rounded-t-2xl bg-surface-modal shadow-2xl sm:inset-0 sm:m-auto sm:h-fit sm:max-h-[85vh] sm:w-[min(28rem,calc(100vw-2rem))] sm:rounded-2xl"
				:class="tall ? 'max-h-[88dvh]' : 'max-h-[80dvh]'"
			>
				<!-- Grab handle, mobile only -->
				<div class="grid shrink-0 place-items-center pt-2 sm:hidden">
					<div class="h-1 w-9 rounded-full bg-surface-gray-4" />
				</div>

				<div
					v-if="title"
					class="shrink-0 px-4 pb-3 pt-3 text-p-lg font-semibold text-ink-gray-9"
				>
					{{ title }}
				</div>

				<div class="pos-scroll min-h-0 flex-1">
					<slot />
				</div>
			</div>
		</Transition>
	</Teleport>
</template>
