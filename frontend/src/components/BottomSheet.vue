<script setup>
import { watch, onUnmounted } from 'vue'
import LucideX from '~icons/lucide/x'

const props = defineProps({
	modelValue: { type: Boolean, default: false },
	title: { type: String, default: '' },
	/** Cap the sheet height on mobile; desktop uses a centred dialog instead. */
	tall: { type: Boolean, default: false },
	/**
	 * For sheets that list documents rather than ask a question.
	 *
	 * The default 28rem suits a form — one column of fields — but a list row
	 * carries a customer, a reference, a total and three actions side by side.
	 * At 28rem the actions and the amount take their width first and the
	 * customer, the one field the row exists to identify, was squeezed down to
	 * "Wanjiru Salon Sup…" on a 1180px screen with room to spare.
	 */
	wide: { type: Boolean, default: false },
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
				class="fixed inset-x-0 bottom-0 z-50 flex flex-col rounded-t-2xl bg-surface-modal shadow-2xl sm:inset-0 sm:m-auto sm:h-fit sm:max-h-[85vh] sm:rounded-2xl"
				:class="[
					tall ? 'max-h-[88dvh]' : 'max-h-[80dvh]',
					wide
						? 'sm:w-[min(46rem,calc(100vw-2rem))]'
						: 'sm:w-[min(28rem,calc(100vw-2rem))]',
				]"
			>
				<!-- Grab handle, mobile only -->
				<div class="grid shrink-0 place-items-center pt-2 sm:hidden">
					<div class="h-1 w-9 rounded-full bg-surface-gray-4" />
				</div>

				<!-- A way out, on every sheet.
				     There was none: closing meant tapping the backdrop or pressing
				     Escape, which is discoverable on a desktop and invisible on a
				     counter tablet — a cashier who opened the wrong sheet mid-sale
				     had no obvious way back to the cart. Floated over the content
				     rather than placed in the header, because most sheets here draw
				     their own heading instead of passing `title`. -->
				<button
					type="button"
					class="absolute right-3 top-3 z-20 grid h-9 w-9 place-items-center rounded-full bg-surface-gray-7 text-ink-white shadow-md transition-all hover:bg-surface-gray-6 active:scale-95"
					aria-label="Close"
					@click="close"
				>
					<LucideX class="h-[18px] w-[18px]" stroke-width="2.5" />
				</button>

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
