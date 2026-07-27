<script setup>
import { ref, watch, nextTick } from 'vue'
import { fmtMoney } from '@/utils/format'
import { searchCustomers, createCustomer } from '@/data/api'
import BottomSheet from './BottomSheet.vue'
import LucideSearch from '~icons/lucide/search'
import LucideUserPlus from '~icons/lucide/user-plus'
import LucideUserX from '~icons/lucide/user-x'

const props = defineProps({
	modelValue: { type: Boolean, default: false },
	/** Credit sales cannot fall back to walk-in, so the sheet cannot be dismissed empty. */
	required: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'select'])

const query = ref('')
const results = ref([])
const loading = ref(false)
const creating = ref(false)
const mobile = ref('')
const input = ref(null)

let seq = 0

async function run() {
	const mine = ++seq
	loading.value = true
	try {
		const rows = await searchCustomers(query.value)
		// Drop stale responses: the cashier types faster than the server replies.
		if (mine === seq) results.value = rows || []
	} catch (e) {
		console.error('[pos] customer search failed', e)
		if (mine === seq) results.value = []
	} finally {
		if (mine === seq) loading.value = false
	}
}

let timer = null
watch(query, () => {
	clearTimeout(timer)
	timer = setTimeout(run, 200)
})

watch(
	() => props.modelValue,
	async (open) => {
		if (!open) return
		query.value = ''
		mobile.value = ''
		creating.value = false
		results.value = []
		run()
		await nextTick()
		input.value?.focus()
	},
)

function pick(customer) {
	emit('select', customer)
	emit('update:modelValue', false)
}

async function create() {
	if (!query.value.trim()) return
	try {
		const c = await createCustomer({ customerName: query.value.trim(), mobileNo: mobile.value })
		pick(c)
	} catch (e) {
		console.error('[pos] customer create failed', e)
	}
}
</script>

<template>
	<BottomSheet
		:model-value="modelValue"
		tall
		title="Customer"
		@update:model-value="emit('update:modelValue', $event)"
	>
		<div class="flex flex-col gap-3 px-4 pb-5">
			<div class="relative">
				<LucideSearch
					class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-gray-5"
				/>
				<input
					ref="input"
					v-model="query"
					type="text"
					autocomplete="off"
					placeholder="Search name or phone…"
					class="h-12 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 pl-9 pr-3 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none focus:ring-2 focus:ring-outline-gray-3"
				/>
			</div>

			<!-- Walk-in is not offered on a credit sale: somebody has to owe the money. -->
			<button
				v-if="!required"
				class="flex min-h-touch items-center gap-2.5 rounded-xl border border-outline-gray-2 px-3 py-2.5 text-left transition-colors hover:bg-surface-gray-2"
				@click="pick(null)"
			>
				<LucideUserX class="h-4 w-4 shrink-0 text-ink-gray-5" />
				<span class="text-p-base text-ink-gray-7">Walk-in customer</span>
			</button>

			<div v-if="results.length" class="flex flex-col gap-2">
				<button
					v-for="c in results"
					:key="c.name"
					class="flex items-center gap-3 rounded-xl border border-outline-gray-2 p-3 text-left transition-colors hover:bg-surface-gray-2"
					@click="pick(c)"
				>
					<div class="min-w-0 flex-1">
						<div class="truncate text-p-base font-medium text-ink-gray-9">
							{{ c.customer_name || c.name }}
						</div>
						<div v-if="c.mobile_no" class="tabular text-p-xs text-ink-gray-5">
							{{ c.mobile_no }}
						</div>
					</div>
					<!-- Existing debt is the number that decides whether to extend more. -->
					<span
						v-if="c.outstanding > 0"
						class="tabular shrink-0 rounded bg-surface-amber-2 px-2 py-1 text-p-xs font-medium text-ink-amber-3"
					>
						owes {{ fmtMoney(c.outstanding) }}
					</span>
				</button>
			</div>

			<div v-else-if="!loading && query" class="py-2 text-center text-p-sm text-ink-gray-5">
				No customer matches “{{ query }}”
			</div>

			<!-- Create inline: making the cashier leave the sale to add a customer
			     is how credit sales end up on the wrong account. -->
			<div v-if="query.trim()" class="flex flex-col gap-2 border-t border-outline-gray-2 pt-3">
				<input
					v-if="creating"
					v-model="mobile"
					type="tel"
					inputmode="tel"
					placeholder="Phone number (optional)"
					class="h-12 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none focus:ring-2 focus:ring-outline-gray-3"
					@keyup.enter="create"
				/>
				<button
					class="flex min-h-touch items-center justify-center gap-2 rounded-xl bg-surface-gray-7 py-3 text-p-base font-semibold text-ink-white transition-all active:scale-[0.98]"
					@click="creating ? create() : (creating = true)"
				>
					<LucideUserPlus class="h-4 w-4" />
					{{ creating ? `Create “${query.trim()}”` : `Add “${query.trim()}” as new` }}
				</button>
			</div>
		</div>
	</BottomSheet>
</template>
