<script setup>
import { fmtMoney } from '@/utils/format'
import BottomSheet from './BottomSheet.vue'
import LucidePause from '~icons/lucide/pause'
import LucideTrash2 from '~icons/lucide/trash-2'

defineProps({
	modelValue: { type: Boolean, default: false },
	tickets: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:modelValue', 'resume', 'drop'])

function since(ts) {
	const mins = Math.floor((Date.now() - ts) / 60000)
	if (mins < 1) return 'just now'
	if (mins < 60) return `${mins}m ago`
	return `${Math.floor(mins / 60)}h ago`
}
</script>

<template>
	<BottomSheet
		:model-value="modelValue"
		title="Held sales"
		@update:model-value="emit('update:modelValue', $event)"
	>
		<div v-if="tickets.length" class="flex flex-col gap-2 px-4 pb-5">
			<div
				v-for="t in tickets"
				:key="t.id"
				class="flex items-center gap-3 rounded-xl border border-outline-gray-2 bg-surface-white p-3"
			>
				<button class="min-w-0 flex-1 text-left" @click="emit('resume', t.id)">
					<div class="flex items-baseline gap-2">
						<span class="text-p-base font-semibold text-ink-gray-9">{{ t.id }}</span>
						<span class="text-p-xs text-ink-gray-5">{{ since(t.at) }}</span>
					</div>
					<div class="tabular mt-0.5 text-p-sm text-ink-gray-6">
						{{ t.count }} {{ t.count === 1 ? 'item' : 'items' }} ·
						{{ fmtMoney(t.total) }}
					</div>
				</button>
				<button
					class="min-h-touch shrink-0 rounded-lg bg-surface-gray-2 px-4 text-p-sm font-medium text-ink-gray-8 transition-colors hover:bg-surface-gray-3"
					@click="emit('resume', t.id)"
				>
					Resume
				</button>
				<button
					class="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-ink-gray-4 transition-colors hover:bg-surface-red-2 hover:text-ink-red-3"
					:aria-label="`Discard ${t.id}`"
					@click="emit('drop', t.id)"
				>
					<LucideTrash2 class="h-4 w-4" />
				</button>
			</div>
		</div>

		<div v-else class="grid place-items-center px-4 pb-8 pt-2">
			<div class="flex flex-col items-center gap-3 text-center">
				<div class="grid h-12 w-12 place-items-center rounded-full bg-surface-gray-2">
					<LucidePause class="h-5 w-5 text-ink-gray-4" />
				</div>
				<div>
					<div class="text-p-base font-medium text-ink-gray-7">No held sales</div>
					<div class="mt-1 max-w-[15rem] text-p-sm text-ink-gray-5">
						Park a sale to serve the next customer, then pick it back up here.
					</div>
				</div>
			</div>
		</div>
	</BottomSheet>
</template>
