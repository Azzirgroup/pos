<script setup>
import { computed, ref, watch } from 'vue'
import { getItemEverywhere, reconcileStock } from '@/data/api'
import { fmtMoney } from '@/utils/format'
import BottomSheet from './BottomSheet.vue'
import LucideStore from '~icons/lucide/store'
import LucideClipboardList from '~icons/lucide/clipboard-list'
import LucideScale from '~icons/lucide/scale'

/**
 * The item card's quick actions — opened from the ⋮ on a cell.
 *
 * Three questions a salesperson has about one product and could not answer
 * from the till: is it in another store, can I ask for it, and (for the store
 * keeper) the shelf count is wrong — fix it. All three were a trip to another
 * screen, which at a counter means they did not happen.
 */
const props = defineProps({
	modelValue: { type: Boolean, default: false },
	item: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'request', 'reconciled', 'notify'])

const data = ref(null)
const loading = ref(false)
const error = ref('')

const requestQty = ref(1)
const requestFrom = ref('')

const countOpen = ref(false)
const countStore = ref('')
const countQty = ref('')
const countReason = ref('')
const counting = ref(false)

watch(
	() => [props.modelValue, props.item?.item_code],
	([open]) => {
		if (!open || !props.item) return
		countOpen.value = false
		countReason.value = ''
		requestQty.value = 1
		load()
	},
)

async function load() {
	loading.value = true
	error.value = ''
	try {
		data.value = await getItemEverywhere({ itemCode: props.item.item_code })
		const others = data.value.stores.filter((s) => !s.is_here)
		requestFrom.value = (others.find((s) => s.qty > 0) || others[0])?.warehouse || ''
		countStore.value = data.value.here || data.value.stores[0]?.warehouse || ''
		countQty.value = storeQty(countStore.value)
	} catch (e) {
		error.value = e.message || 'Could not load the stock'
	} finally {
		loading.value = false
	}
}

const otherStores = computed(() => (data.value?.stores || []).filter((s) => !s.is_here))

function storeQty(warehouse) {
	return data.value?.stores.find((s) => s.warehouse === warehouse)?.qty ?? 0
}

watch(countStore, (w) => {
	if (data.value) countQty.value = storeQty(w)
})

const fmt = (q) => (Number(q) || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })

function request() {
	const qty = Number(requestQty.value) || 0
	if (qty <= 0 || !requestFrom.value) return
	emit('request', {
		items: [{ item_code: props.item.item_code, qty, from_warehouse: requestFrom.value }],
		warehouse: requestFrom.value,
	})
	emit('update:modelValue', false)
}

const countChanged = computed(
	() => countQty.value !== '' && Number(countQty.value) !== Number(storeQty(countStore.value)),
)

async function saveCount() {
	if (!countChanged.value) return
	counting.value = true
	try {
		const res = await reconcileStock({
			itemCode: props.item.item_code,
			qty: Number(countQty.value),
			warehouse: countStore.value,
			reason: countReason.value,
		})
		emit('notify', { message: res.message, tone: 'good' })
		emit('reconciled', res)
		countOpen.value = false
		await load()
	} catch (e) {
		emit('notify', { message: e.message || 'Could not reconcile', tone: 'bad' })
	} finally {
		counting.value = false
	}
}
</script>

<template>
	<BottomSheet :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)">
		<div v-if="item" class="flex flex-col gap-3 px-4 pb-5 pt-1">
			<div class="min-w-0">
				<div class="text-p-lg font-semibold text-ink-gray-9">{{ item.item_name }}</div>
				<div class="text-p-sm text-ink-gray-5">
					{{ item.item_code }} · {{ fmtMoney(item.price) }}
				</div>
			</div>

			<p v-if="error" class="rounded-lg bg-surface-red-2 px-3 py-2 text-p-sm text-ink-red-3">{{ error }}</p>
			<p v-else-if="loading && !data" class="text-p-sm text-ink-gray-5">Checking every store…</p>

			<template v-if="data">
				<!-- Stock standing across the shop, this till's shelf first. -->
				<section class="rounded-xl border border-outline-gray-2">
					<div class="flex items-center gap-2 border-b border-outline-gray-2 px-3 py-2">
						<LucideStore class="h-4 w-4 text-ink-gray-5" />
						<span class="text-p-sm font-medium text-ink-gray-8">Stock in every store</span>
						<span class="tabular ml-auto text-p-sm text-ink-gray-6">
							{{ fmt(data.total) }} {{ data.uom }} in total
						</span>
					</div>
					<div
						v-for="s in data.stores"
						:key="s.warehouse"
						class="flex items-center gap-2 border-t border-outline-gray-1 px-3 py-2 first:border-t-0"
						:class="s.is_here ? 'bg-surface-gray-1' : ''"
					>
						<span class="min-w-0 flex-1 truncate text-p-sm text-ink-gray-8">
							{{ s.label }}
							<span v-if="s.is_here" class="ml-1 rounded-full bg-surface-gray-3 px-1.5 py-0.5 text-p-xs text-ink-gray-6">this till</span>
						</span>
						<span
							class="tabular rounded px-1.5 py-0.5 text-p-sm font-medium"
							:class="
								s.qty <= 0
									? 'bg-surface-red-2 text-ink-red-3'
									: s.qty <= 5
										? 'bg-surface-amber-2 text-ink-amber-3'
										: 'bg-surface-green-2 text-ink-green-3'
							"
						>
							{{ s.qty <= 0 ? 'Out' : fmt(s.qty) }}
						</span>
					</div>
				</section>

				<!-- Ask another store for it. -->
				<section v-if="otherStores.length" class="flex flex-col gap-2 rounded-xl border border-outline-gray-2 p-3">
					<div class="flex items-center gap-2">
						<LucideClipboardList class="h-4 w-4 text-ink-gray-5" />
						<span class="text-p-sm font-medium text-ink-gray-8">Request this item</span>
					</div>
					<div class="flex flex-wrap items-end gap-2">
						<label class="min-w-[180px] flex-1">
							<span class="mb-1.5 block text-p-xs text-ink-gray-6">From</span>
							<select
								v-model="requestFrom"
								class="h-10 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-2 text-p-sm text-ink-gray-9"
							>
								<option v-for="s in otherStores" :key="s.warehouse" :value="s.warehouse">
									{{ s.label }} — {{ s.qty > 0 ? `${fmt(s.qty)} there` : 'none there' }}
								</option>
							</select>
						</label>
						<label class="w-24">
							<span class="mb-1.5 block text-p-xs text-ink-gray-6">Qty</span>
							<input
								v-model.number="requestQty"
								type="number"
								min="1"
								inputmode="numeric"
								class="tabular h-10 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-2 text-right text-p-sm text-ink-gray-9"
								@focus="$event.target.select()"
							/>
						</label>
						<button
							class="h-10 rounded-lg bg-surface-gray-7 px-4 text-p-sm font-semibold text-ink-white disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
							:disabled="!requestFrom || !(Number(requestQty) > 0)"
							@click="request"
						>
							Request {{ Number(requestQty) || 0 }}
						</button>
					</div>
				</section>

				<!-- The shelf count is wrong: store keeper only. -->
				<section v-if="data.can_reconcile" class="flex flex-col gap-2 rounded-xl border border-outline-gray-2 p-3">
					<button class="flex items-center gap-2 text-left" @click="countOpen = !countOpen">
						<LucideScale class="h-4 w-4 text-ink-gray-5" />
						<span class="text-p-sm font-medium text-ink-gray-8">Reconcile stock</span>
						<span class="ml-auto text-p-xs text-ink-blue-3">{{ countOpen ? 'Hide' : 'Count it' }}</span>
					</button>
					<template v-if="countOpen">
						<div class="flex flex-wrap items-end gap-2">
							<label class="min-w-[180px] flex-1">
								<span class="mb-1.5 block text-p-xs text-ink-gray-6">Store counted</span>
								<select
									v-model="countStore"
									class="h-10 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-2 text-p-sm text-ink-gray-9"
								>
									<option v-for="s in data.stores" :key="s.warehouse" :value="s.warehouse">
										{{ s.label }} (system says {{ fmt(s.qty) }})
									</option>
								</select>
							</label>
							<label class="w-28">
								<span class="mb-1.5 block text-p-xs text-ink-gray-6">Counted</span>
								<input
									v-model="countQty"
									type="number"
									min="0"
									step="any"
									inputmode="decimal"
									class="tabular h-10 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-2 text-right text-p-sm text-ink-gray-9"
									@focus="$event.target.select()"
								/>
							</label>
						</div>
						<input
							v-model="countReason"
							type="text"
							placeholder="Why — damaged, miscount… (optional)"
							class="h-10 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4"
						/>
						<button
							class="h-10 rounded-lg bg-surface-gray-7 text-p-sm font-semibold text-ink-white disabled:bg-surface-gray-4 disabled:text-ink-gray-5"
							:disabled="!countChanged || counting"
							@click="saveCount"
						>
							{{
								counting
									? 'Saving…'
									: countChanged
										? `Set to ${fmt(countQty)} (${Number(countQty) - storeQty(countStore) > 0 ? '+' : ''}${fmt(Number(countQty) - storeQty(countStore))})`
										: 'Enter the counted quantity'
							}}
						</button>
					</template>
				</section>
			</template>
		</div>
	</BottomSheet>
</template>
