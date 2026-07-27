<script setup>
import { fmtMoney } from '@/utils/format'
import LucideShoppingBag from '~icons/lucide/shopping-bag'
import LucideChevronUp from '~icons/lucide/chevron-up'

defineProps({
	count: { type: Number, default: 0 },
	total: { type: Number, default: 0 },
})

defineEmits(['open', 'pay'])
</script>

<template>
	<!-- Always-visible on mobile. Splits into "review the cart" and "take the
	     money" so the common path (scan → pay) is a single tap from anywhere. -->
	<div
		class="pb-safe shrink-0 border-t border-outline-gray-2 bg-surface-white px-3 pt-2"
		:class="count ? '' : 'opacity-60'"
	>
		<div class="flex items-center gap-2 pb-2">
			<button
				class="flex min-h-touch flex-1 items-center gap-2.5 rounded-xl bg-surface-gray-2 px-3 py-2.5 text-left transition-colors active:bg-surface-gray-3 disabled:opacity-60"
				:disabled="!count"
				@click="$emit('open')"
			>
				<div class="relative shrink-0">
					<LucideShoppingBag class="h-5 w-5 text-ink-gray-7" />
					<span
						v-if="count"
						class="tabular absolute -right-1.5 -top-1.5 grid h-4 min-w-4 place-items-center rounded-full bg-surface-gray-7 px-1 text-[10px] font-semibold text-ink-white"
					>
						{{ count }}
					</span>
				</div>
				<div class="min-w-0 flex-1">
					<div class="tabular text-p-base font-semibold leading-tight text-ink-gray-9">
						{{ fmtMoney(total) }}
					</div>
					<div class="text-p-xs text-ink-gray-5">
						{{ count }} {{ count === 1 ? 'item' : 'items' }} · tap to review
					</div>
				</div>
				<LucideChevronUp class="h-4 w-4 shrink-0 text-ink-gray-5" />
			</button>

			<button
				class="min-h-touch shrink-0 rounded-xl bg-surface-gray-7 px-6 py-3 text-p-base font-semibold text-ink-white transition-all active:scale-[0.97] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
				:disabled="!count"
				@click="$emit('pay')"
			>
				Pay
			</button>
		</div>
	</div>
</template>
