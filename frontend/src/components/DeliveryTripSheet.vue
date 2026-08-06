<script setup>
import { ref, computed, watch } from 'vue'
import { Button, Dialog, FormControl } from 'frappe-ui'
import { searchTripInvoices, createDeliveryTrip } from '@/data/api'
import { fmtMoney } from '@/utils/format'
import LucideSearch from '~icons/lucide/search'
import LucideX from '~icons/lucide/x'

/**
 * One delivery run, several invoices.
 *
 * Its own sheet rather than the generic document form the rest of the app
 * uses: that form's whole model of a "line" is an item with a quantity, and
 * a trip's lines are invoices already rung up and paid for — there is
 * nothing to quantify, only to pick. See `Cosmestics Delivery Trip` for why
 * this is a plain custom doctype rather than ERPNext's own Delivery Trip.
 */
const props = defineProps({
	open: { type: Boolean, default: false },
})

const emit = defineEmits(['update:open', 'created', 'notify'])

const driverName = ref('')
const driverPhone = ref('')
const vehicle = ref('')
const departureTime = ref('')
const picked = ref([])
const query = ref('')
const results = ref([])
const searching = ref(false)
const saving = ref(false)

watch(
	() => props.open,
	(open) => {
		if (!open) return
		driverName.value = ''
		driverPhone.value = ''
		vehicle.value = ''
		departureTime.value = ''
		picked.value = []
		query.value = ''
		results.value = []
	},
)

let seq = 0
async function runSearch() {
	const mine = ++seq
	searching.value = true
	try {
		const rows = await searchTripInvoices(query.value)
		if (mine === seq) {
			const onTrip = new Set(picked.value.map((p) => p.name))
			results.value = rows.filter((r) => !onTrip.has(r.name))
		}
	} catch {
		if (mine === seq) results.value = []
	} finally {
		if (mine === seq) searching.value = false
	}
}

let timer = null
watch(query, () => {
	clearTimeout(timer)
	timer = setTimeout(runSearch, 200)
})
watch(() => props.open, (open) => open && runSearch())

function pick(invoice) {
	picked.value.push(invoice)
	results.value = results.value.filter((r) => r.name !== invoice.name)
}

function unpick(i) {
	picked.value.splice(i, 1)
}

const total = computed(() => picked.value.reduce((sum, i) => sum + (i.grand_total || 0), 0))

const blocker = computed(() => {
	if (!driverName.value.trim()) return 'Name the driver'
	if (!picked.value.length) return 'Add at least one invoice'
	return null
})

function close() {
	emit('update:open', false)
}

async function save() {
	if (blocker.value) return
	saving.value = true
	try {
		const res = await createDeliveryTrip({
			driverName: driverName.value.trim(),
			driverPhone: driverPhone.value.trim() || null,
			vehicle: vehicle.value.trim() || null,
			departureTime: departureTime.value || null,
			invoices: picked.value.map((i) => ({ sales_invoice: i.name })),
		})
		emit('notify', { message: res.message, tone: 'good' })
		emit('created', res)
		close()
	} catch (e) {
		emit('notify', { message: e.message || 'Could not create the trip', tone: 'bad' })
	} finally {
		saving.value = false
	}
}
</script>

<template>
	<Dialog
		:model-value="open"
		:options="{ title: 'New Delivery Trip', size: '2xl' }"
		@update:model-value="close"
	>
		<template #body-content>
			<div class="flex flex-col gap-4">
				<div class="grid gap-3 sm:grid-cols-2">
					<FormControl v-model="driverName" type="text" label="Driver *" />
					<FormControl v-model="driverPhone" type="text" label="Driver phone" />
					<FormControl v-model="vehicle" type="text" label="Vehicle" />
					<FormControl v-model="departureTime" type="datetime-local" label="Departure time" />
				</div>

				<div class="flex flex-col gap-2">
					<h3 class="text-p-xs font-medium uppercase tracking-wide text-ink-gray-5">
						Invoices on this trip
					</h3>

					<div v-if="picked.length" class="overflow-hidden rounded-xl border border-outline-gray-2">
						<div
							class="grid grid-cols-[1fr_1fr_100px_28px] gap-x-2 border-b border-outline-gray-2 bg-surface-gray-2 px-2 py-1.5 text-p-xs font-medium text-ink-gray-5"
						>
							<span>Invoice</span>
							<span>Customer</span>
							<span class="text-right">Amount</span>
							<span></span>
						</div>
						<div
							v-for="(i, idx) in picked"
							:key="i.name"
							class="grid grid-cols-[1fr_1fr_100px_28px] items-center gap-x-2 border-b border-outline-gray-1 px-2 py-2 last:border-b-0"
						>
							<span class="min-w-0 truncate text-p-sm font-medium text-ink-gray-8">{{ i.name }}</span>
							<span class="min-w-0 truncate text-p-sm text-ink-gray-6">{{ i.customer }}</span>
							<span class="tabular text-right text-p-sm text-ink-blue-3">{{ fmtMoney(i.grand_total) }}</span>
							<button
								class="grid h-7 w-7 shrink-0 place-items-center rounded-md text-ink-gray-4 transition-colors hover:bg-surface-red-2 hover:text-ink-red-3"
								:aria-label="`Remove ${i.name}`"
								@click="unpick(idx)"
							>
								<LucideX class="h-3.5 w-3.5" />
							</button>
						</div>
						<div
							class="grid grid-cols-[1fr_1fr_100px_28px] gap-x-2 border-t border-outline-gray-2 bg-surface-gray-1 px-2 py-1.5 text-p-sm font-semibold"
						>
							<span class="col-span-2 text-ink-gray-7">Total</span>
							<span class="tabular text-right text-ink-gray-9">{{ fmtMoney(total) }}</span>
							<span></span>
						</div>
					</div>
					<p v-else class="rounded-xl border border-dashed border-outline-gray-2 p-3 text-p-sm text-ink-gray-5">
						No invoices added yet — search below.
					</p>
				</div>

				<div class="relative">
					<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">Add an invoice</label>
					<div class="relative">
						<LucideSearch
							class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-gray-5"
						/>
						<input
							v-model="query"
							type="text"
							placeholder="Invoice number or customer…"
							class="h-11 w-full rounded-xl border border-outline-gray-2 bg-surface-gray-2 pl-9 pr-3 text-p-base text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none focus:ring-2 focus:ring-outline-gray-3"
						/>
					</div>
					<div
						v-if="searching || results.length"
						class="mt-1 max-h-56 overflow-y-auto rounded-xl border border-outline-gray-2 bg-surface-white p-1 shadow-sm"
					>
						<p v-if="searching" class="px-3 py-2 text-p-sm text-ink-gray-5">Searching…</p>
						<button
							v-for="r in results"
							:key="r.name"
							type="button"
							class="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left hover:bg-surface-gray-2"
							@click="pick(r)"
						>
							<span class="min-w-0 flex-1">
								<span class="block truncate text-p-sm font-medium text-ink-gray-8">{{ r.name }}</span>
								<span class="block truncate text-p-xs text-ink-gray-5">{{ r.customer }}</span>
							</span>
							<span class="tabular shrink-0 text-p-sm text-ink-blue-3">{{ fmtMoney(r.grand_total) }}</span>
						</button>
					</div>
				</div>
			</div>
		</template>

		<template #actions>
			<Button
				theme="gray"
				variant="solid"
				:loading="saving"
				:disabled="!!blocker"
				:label="blocker || 'Dispatch trip'"
				@click="save"
			/>
		</template>
	</Dialog>
</template>
