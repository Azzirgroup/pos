<script setup>
import { computed, ref, watch } from 'vue'
import { Dialog } from 'frappe-ui'
import { moveStockHere } from '@/data/api'
import { useCatalogStore } from '@/stores/catalog'
import LucideMinus from '~icons/lucide/minus'
import LucidePlus from '~icons/lucide/plus'

/**
 * "Move stock here", from an item card.
 *
 * Pick the store to take it from, say how many, send. What is sent is a
 * transfer *request* — nothing leaves the other store until the store keeper
 * approves it (`stock.approve_transfer`), and the card shows "Request sent"
 * meanwhile.
 */
const props = defineProps({
	modelValue: { type: Boolean, default: false },
	item: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'sent', 'notify'])

const catalog = useCatalogStore()

const from = ref('')
const qty = ref(1)
const sending = ref(false)
const error = ref('')

const here = computed(() => catalog.stores.find((s) => s.is_here))

/** Stores holding some, fullest first. */
const sources = computed(() =>
	catalog.stores
		.filter((s) => !s.is_here)
		.map((s) => ({ ...s, qty: Math.floor(Number(props.item?.byStore?.[s.name]) || 0) }))
		.filter((s) => s.qty > 0)
		.sort((a, b) => b.qty - a.qty),
)

const available = computed(() => sources.value.find((s) => s.name === from.value)?.qty || 0)

watch(
	() => props.modelValue,
	(open) => {
		if (!open) return
		from.value = sources.value[0]?.name || ''
		qty.value = 1
		error.value = ''
	},
)

watch(from, () => {
	if (qty.value > available.value) qty.value = Math.max(1, available.value)
})

function step(delta) {
	qty.value = Math.min(Math.max(1, (Number(qty.value) || 0) + delta), available.value || 1)
}

const valid = computed(() => from.value && qty.value >= 1 && qty.value <= available.value)

function close() {
	emit('update:modelValue', false)
}

async function send() {
	if (!valid.value) return
	sending.value = true
	error.value = ''
	try {
		const res = await moveStockHere({
			itemCode: props.item.item_code,
			fromWarehouse: from.value,
			qty: Number(qty.value),
		})
		catalog.markRequested(props.item.item_code, Number(qty.value))
		emit('sent', res)
		emit('notify', { message: res.message, tone: 'good' })
		close()
	} catch (e) {
		error.value = e.message || 'Could not send the request'
	} finally {
		sending.value = false
	}
}
</script>

<template>
	<Dialog :model-value="modelValue" :options="{ size: 'md' }" @update:model-value="emit('update:modelValue', $event)">
		<template #body>
			<div v-if="item" class="flex flex-col gap-4 p-5">
				<div>
					<h2 class="text-lg font-semibold text-ink-gray-9">
						Move stock to {{ here?.label || 'this till' }}
					</h2>
					<p class="text-p-sm text-ink-gray-5">{{ item.item_name }}</p>
				</div>

				<div>
					<div class="mb-2 text-p-sm text-ink-gray-7">From</div>
					<p v-if="!sources.length" class="rounded-lg bg-surface-gray-2 px-3 py-2 text-p-sm text-ink-gray-6">
						No other store has any of this.
					</p>
					<div class="flex flex-col gap-2">
						<label
							v-for="s in sources"
							:key="s.name"
							class="flex min-h-touch cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 transition-colors"
							:class="
								from === s.name
									? 'border-violet-400 bg-surface-violet-1'
									: 'border-outline-gray-2 hover:bg-surface-gray-2'
							"
						>
							<input v-model="from" type="radio" :value="s.name" class="h-4 w-4 text-violet-600" />
							<span class="flex-1 text-p-base text-ink-gray-9">{{ s.label }}</span>
							<span class="tabular text-p-sm text-ink-gray-6">{{ s.qty }} available</span>
						</label>
					</div>
				</div>

				<div v-if="sources.length">
					<div class="mb-2 text-p-sm text-ink-gray-7">Quantity</div>
					<div class="flex items-center gap-3">
						<div class="flex items-center rounded-xl border border-outline-gray-2">
							<button
								type="button"
								class="grid h-11 w-11 place-items-center text-ink-gray-7 hover:bg-surface-gray-2 disabled:opacity-40"
								:disabled="qty <= 1"
								aria-label="One fewer"
								@click="step(-1)"
							>
								<LucideMinus class="h-4 w-4" />
							</button>
							<input
								v-model.number="qty"
								type="number"
								min="1"
								:max="available"
								inputmode="numeric"
								class="tabular h-11 w-16 border-x border-outline-gray-2 bg-surface-white text-center text-p-lg font-semibold text-ink-gray-9 focus:outline-none"
								@focus="$event.target.select()"
							/>
							<button
								type="button"
								class="grid h-11 w-11 place-items-center text-ink-gray-7 hover:bg-surface-gray-2 disabled:opacity-40"
								:disabled="qty >= available"
								aria-label="One more"
								@click="step(1)"
							>
								<LucidePlus class="h-4 w-4" />
							</button>
						</div>
						<span class="text-p-sm text-ink-gray-6">
							of {{ available }} at {{ sources.find((s) => s.name === from)?.label }}
						</span>
					</div>
					<p class="mt-2 text-p-xs text-ink-gray-5">
						Only the amount you pick leaves the source store — the rest stays put. It moves
						once the store keeper approves the request.
					</p>
				</div>

				<p v-if="error" class="rounded-lg bg-surface-red-2 px-3 py-2 text-p-sm text-ink-red-3">{{ error }}</p>

				<div class="grid grid-cols-2 gap-2">
					<button
						type="button"
						class="min-h-touch rounded-xl border border-outline-gray-2 py-3 text-p-base font-semibold text-ink-gray-8 hover:bg-surface-gray-2"
						@click="close"
					>
						Cancel
					</button>
					<button
						type="button"
						class="min-h-touch rounded-xl bg-violet-600 py-3 text-p-base font-semibold text-white transition-colors hover:bg-violet-700 disabled:opacity-50"
						:disabled="!valid || sending"
						@click="send"
					>
						{{ sending ? 'Sending…' : 'Send request' }}
					</button>
				</div>
			</div>
		</template>
	</Dialog>
</template>
