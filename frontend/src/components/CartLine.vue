<script setup>
import { ref, watch } from 'vue'
import { fmtMoneyShort, fmtQty } from '@/utils/format'
import LucideMinus from '~icons/lucide/minus'
import LucidePlus from '~icons/lucide/plus'
import LucideTrash2 from '~icons/lucide/trash-2'

const props = defineProps({
	line: { type: Object, required: true },
	lineTotal: { type: Number, required: true },
	highlight: { type: Boolean, default: false },
	allowRateChange: { type: Boolean, default: false },
})

const emit = defineEmits(['inc', 'dec', 'remove', 'setQty', 'setUom', 'setRate'])

function onRateChange(event) {
	emit('setRate', props.line.id, event.target.value)
}

// A one-shot tint when the line is touched. Confirms the tap landed on the
// right line without a toast — critical when scanning the same item repeatedly.
const flash = ref(false)
watch(
	() => [props.highlight, props.line.qty],
	() => {
		if (!props.highlight) return
		flash.value = true
		setTimeout(() => (flash.value = false), 500)
	},
)
</script>

<template>
	<div
		class="flex items-start gap-2 rounded-lg px-2 py-2 transition-colors duration-500"
		:class="flash ? 'bg-surface-green-2' : 'bg-transparent'"
	>
		<!-- Name & unit price -->
		<div class="min-w-0 flex-1 pt-0.5">
			<div class="line-clamp-2 text-p-sm font-medium leading-snug text-ink-gray-8">
				{{ line.item_name }}
			</div>
			<div class="tabular mt-0.5 flex flex-wrap items-center gap-1.5 text-p-xs text-ink-gray-5">
				<!-- A unit picker only where there is a choice. Most items have one
				     unit, and a select with a single option is a control that looks
				     like a decision and is not. -->
				<select
					v-if="line.units && line.units.length > 1"
					:value="line.uom"
					class="h-6 rounded border border-outline-gray-2 bg-surface-gray-2 px-1 text-p-xs font-medium text-ink-gray-8 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
					:aria-label="`Unit for ${line.item_name}`"
					@change="$emit('setUom', line.id, $event.target.value)"
					@click.stop
				>
					<option v-for="u in line.units" :key="u.uom" :value="u.uom">{{ u.uom }}</option>
				</select>
				<span v-if="!allowRateChange">{{ fmtMoneyShort(line.rate) }} / {{ line.uom }}</span>
				<span v-else class="inline-flex items-center gap-0.5">
					<input
						:value="line.rate"
						type="number"
						min="0"
						step="0.01"
						inputmode="decimal"
						class="tabular h-6 w-16 rounded border border-outline-gray-2 bg-surface-gray-2 px-1 text-right text-p-xs font-medium text-ink-gray-8 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
						:aria-label="`Rate for ${line.item_name}`"
						@focus="$event.target.select()"
						@change="onRateChange"
						@click.stop
					/>
					<span>/ {{ line.uom }}</span>
				</span>
				<!-- What actually leaves the shelf, when that differs from what was
				     typed. A cashier selling two dozen should see "24 pcs" without
				     doing the arithmetic. -->
				<span v-if="(line.conversionFactor || 1) !== 1" class="text-ink-gray-4">
					= {{ (line.qty * line.conversionFactor).toLocaleString() }} {{ line.units?.[0]?.uom }}
				</span>
				<span
					v-if="line.discountPct"
					class="rounded bg-surface-amber-2 px-1 font-medium text-ink-amber-3"
				>
					−{{ line.discountPct }}%
				</span>
				<!-- Sourced lines look different because they behave differently:
				     they carry a cost and generate a purchase on checkout. -->
				<span
					v-if="line.sourced"
					class="rounded bg-surface-green-2 px-1 font-medium text-ink-green-3"
				>
					{{ line.sourced.supplier }} @ {{ fmtMoneyShort(line.sourced.buyRate) }}
				</span>
			</div>
		</div>

		<!-- Qty stepper. 32px targets on desktop, comfortably tappable on a tablet. -->
		<div
			class="flex shrink-0 items-center rounded-lg border border-outline-gray-2 bg-surface-white"
		>
			<button
				class="grid h-8 w-8 place-items-center rounded-l-lg text-ink-gray-6 transition-colors hover:bg-surface-gray-2 active:bg-surface-gray-3"
				:aria-label="`Decrease ${line.item_name}`"
				@click="$emit('dec', line.id)"
			>
				<LucideMinus class="h-3.5 w-3.5" />
			</button>
			<input
				:value="fmtQty(line.qty)"
				inputmode="decimal"
				class="tabular h-8 w-9 border-0 bg-transparent p-0 text-center text-p-sm font-semibold text-ink-gray-9 focus:outline-none focus:ring-0"
				:aria-label="`Quantity for ${line.item_name}`"
				@focus="$event.target.select()"
				@change="$emit('setQty', line.id, Number($event.target.value))"
			/>
			<button
				class="grid h-8 w-8 place-items-center rounded-r-lg text-ink-gray-6 transition-colors hover:bg-surface-gray-2 active:bg-surface-gray-3"
				:aria-label="`Increase ${line.item_name}`"
				@click="$emit('inc', line.id)"
			>
				<LucidePlus class="h-3.5 w-3.5" />
			</button>
		</div>

		<!-- Line total, right-aligned and fixed width so the column never jitters. -->
		<div class="tabular w-16 shrink-0 pt-1.5 text-right text-p-sm font-semibold text-ink-gray-9">
			{{ fmtMoneyShort(lineTotal) }}
		</div>

		<button
			class="grid h-8 w-7 shrink-0 place-items-center rounded-md text-ink-gray-4 transition-colors hover:bg-surface-red-2 hover:text-ink-red-3"
			:aria-label="`Remove ${line.item_name}`"
			@click="$emit('remove', line.id)"
		>
			<LucideTrash2 class="h-3.5 w-3.5" />
		</button>
	</div>
</template>
