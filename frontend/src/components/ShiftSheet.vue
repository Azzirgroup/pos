<script setup>
import { ref, computed, watch } from 'vue'
import { fmtMoney, fmtMoneyShort } from '@/utils/format'
import BottomSheet from './BottomSheet.vue'
import LucideSunrise from '~icons/lucide/sunrise'
import LucideSunset from '~icons/lucide/sunset'
import LucideCheck from '~icons/lucide/check'

const props = defineProps({
	modelValue: { type: Boolean, default: false },
	/** 'open' or 'close'. */
	mode: { type: String, default: 'open' },
	profiles: { type: Array, default: () => [] },
	/** Payment modes to collect an opening float for. */
	paymentModes: { type: Array, default: () => ['Cash'] },
	summary: { type: Object, default: null },
	busy: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'open-shift', 'close-shift'])

const profile = ref(null)
const floats = ref({})
const counted = ref({})

watch(
	() => props.modelValue,
	(isOpen) => {
		if (!isOpen) return
		profile.value = props.profiles[0]?.name || null
		floats.value = Object.fromEntries(props.paymentModes.map((m) => [m, '']))
		// Pre-fill the count with what is expected. A quiet till then closes in
		// one tap, and anything the cashier edits is a real discrepancy.
		counted.value = Object.fromEntries(
			(props.summary?.rows || []).map((r) => [r.mode_of_payment, String(r.expected_amount)]),
		)
	},
)

const rows = computed(() => props.summary?.rows || [])

const totalDifference = computed(() =>
	rows.value.reduce(
		(sum, r) => sum + ((Number(counted.value[r.mode_of_payment]) || 0) - r.expected_amount),
		0,
	),
)

function submitOpen() {
	if (!profile.value) return
	emit('open-shift', {
		posProfile: profile.value,
		balances: props.paymentModes.map((m) => ({
			mode_of_payment: m,
			opening_amount: Number(floats.value[m]) || 0,
		})),
	})
}

function submitClose() {
	emit('close-shift', {
		counted: rows.value.map((r) => ({
			mode_of_payment: r.mode_of_payment,
			closing_amount: Number(counted.value[r.mode_of_payment]) || 0,
		})),
	})
}
</script>

<template>
	<BottomSheet
		:model-value="modelValue"
		tall
		@update:model-value="emit('update:modelValue', $event)"
	>
		<!-- ---------- Open ---------- -->
		<div v-if="mode === 'open'" class="flex flex-col gap-4 px-4 pb-5 pt-1">
			<div class="flex items-center gap-3">
				<div class="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-surface-amber-2">
					<LucideSunrise class="h-5 w-5 text-ink-amber-3" />
				</div>
				<div>
					<div class="text-p-lg font-semibold text-ink-gray-9">Start shift</div>
					<div class="text-p-sm text-ink-gray-5">Count the drawer before you sell</div>
				</div>
			</div>

			<div v-if="profiles.length > 1">
				<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">Till</label>
				<div class="flex flex-col gap-2">
					<button
						v-for="p in profiles"
						:key="p.name"
						class="min-h-touch rounded-lg border px-3 py-2.5 text-left text-p-base transition-colors"
						:class="
							profile === p.name
								? 'border-outline-gray-4 bg-surface-gray-3 font-medium text-ink-gray-9'
								: 'border-outline-gray-2 bg-surface-white text-ink-gray-7 hover:bg-surface-gray-2'
						"
						@click="profile = p.name"
					>
						{{ p.name }}
					</button>
				</div>
			</div>

			<div class="flex flex-col gap-3">
				<label class="text-p-sm font-medium text-ink-gray-7">Opening float</label>
				<div v-for="m in paymentModes" :key="m" class="flex items-center gap-3">
					<span class="w-24 shrink-0 text-p-base text-ink-gray-7">{{ m }}</span>
					<input
						v-model="floats[m]"
						type="number"
						inputmode="decimal"
						placeholder="0"
						class="tabular h-12 min-w-0 flex-1 rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-lg font-semibold text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none focus:ring-2 focus:ring-outline-gray-3"
						@focus="$event.target.select()"
					/>
				</div>
			</div>

			<button
				class="min-h-touch w-full rounded-xl bg-surface-gray-7 py-4 text-p-lg font-semibold text-ink-white transition-all active:scale-[0.98] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
				:disabled="!profile || busy"
				@click="submitOpen"
			>
				{{ busy ? 'Opening…' : 'Open shift' }}
			</button>
		</div>

		<!-- ---------- Close ---------- -->
		<div v-else class="flex flex-col gap-4 px-4 pb-5 pt-1">
			<div class="flex items-center gap-3">
				<div class="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-surface-gray-3">
					<LucideSunset class="h-5 w-5 text-ink-gray-7" />
				</div>
				<div>
					<div class="text-p-lg font-semibold text-ink-gray-9">Close shift</div>
					<div class="text-p-sm text-ink-gray-5">
						{{ summary?.invoice_count || 0 }} sales ·
						{{ fmtMoneyShort(summary?.grand_total || 0) }}
					</div>
				</div>
			</div>

			<div class="flex flex-col gap-3">
				<div v-for="r in rows" :key="r.mode_of_payment" class="rounded-xl border border-outline-gray-2 p-3">
					<div class="flex items-baseline justify-between">
						<span class="text-p-base font-medium text-ink-gray-8">
							{{ r.mode_of_payment }}
						</span>
						<span class="tabular text-p-xs text-ink-gray-5">
							float {{ fmtMoneyShort(r.opening_amount) }} + sales
							{{ fmtMoneyShort(r.taken) }}
						</span>
					</div>
					<div class="mt-2 flex items-center gap-3">
						<div class="min-w-0 flex-1">
							<div class="text-p-xs text-ink-gray-5">Expected</div>
							<div class="tabular text-p-lg font-semibold text-ink-gray-9">
								{{ fmtMoneyShort(r.expected_amount) }}
							</div>
						</div>
						<div class="min-w-0 flex-1">
							<div class="mb-0.5 text-p-xs text-ink-gray-5">Counted</div>
							<input
								v-model="counted[r.mode_of_payment]"
								type="number"
								inputmode="decimal"
								class="tabular h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-lg font-semibold text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none focus:ring-2 focus:ring-outline-gray-3"
								@focus="$event.target.select()"
							/>
						</div>
					</div>
				</div>
			</div>

			<!-- Credit sales never hit the drawer, so they are called out rather
			     than silently missing from the numbers above. -->
			<div
				v-if="summary?.credit?.count"
				class="rounded-xl bg-surface-amber-2 px-4 py-3 text-p-sm"
			>
				<div class="font-medium text-ink-amber-3">
					{{ summary.credit.count }} credit
					{{ summary.credit.count === 1 ? 'sale' : 'sales' }} this shift
				</div>
				<div class="tabular mt-0.5 text-ink-gray-7">
					{{ fmtMoney(summary.credit.outstanding) }} still owed · not counted in the
					drawer
				</div>
			</div>

			<div
				class="flex items-center justify-between rounded-xl px-4 py-3"
				:class="
					totalDifference === 0
						? 'bg-surface-green-2'
						: totalDifference > 0
							? 'bg-surface-blue-2'
							: 'bg-surface-red-2'
				"
			>
				<span
					class="text-p-base font-medium"
					:class="
						totalDifference === 0
							? 'text-ink-green-3'
							: totalDifference > 0
								? 'text-ink-blue-3'
								: 'text-ink-red-3'
					"
				>
					{{
						totalDifference === 0
							? 'Balanced'
							: totalDifference > 0
								? 'Over'
								: 'Short'
					}}
				</span>
				<span
					class="tabular text-2xl font-semibold"
					:class="
						totalDifference === 0
							? 'text-ink-green-3'
							: totalDifference > 0
								? 'text-ink-blue-3'
								: 'text-ink-red-3'
					"
				>
					{{ fmtMoney(Math.abs(totalDifference)) }}
				</span>
			</div>

			<button
				class="flex min-h-touch w-full items-center justify-center gap-2 rounded-xl bg-surface-gray-7 py-4 text-p-lg font-semibold text-ink-white transition-all active:scale-[0.98] disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
				:disabled="busy"
				@click="submitClose"
			>
				<LucideCheck class="h-5 w-5" />
				{{ busy ? 'Closing…' : 'Close shift' }}
			</button>
		</div>
	</BottomSheet>
</template>
