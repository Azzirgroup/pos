<script setup>
import { ref, watch } from 'vue'
import { Dialog, FormControl, Spinner } from 'frappe-ui'
import DataTable from '@/components/DataTable.vue'
import { getCustomerLedger } from '@/data/api'
import { fmtMoney } from '@/utils/format'

/**
 * A customer's account, opened from wherever their name appears.
 *
 * Built from GL Entry rather than from invoices, so payments, credit notes and
 * journal adjustments all show up. A statement assembled from Sales Invoices
 * alone omits every payment and then disagrees with the outstanding figure
 * printed beside it, which is worse than having no statement at all.
 */
const props = defineProps({
	open: { type: Boolean, default: false },
	customer: { type: String, default: null },
})

const emit = defineEmits(['update:open', 'notify'])

const data = ref(null)
const loading = ref(false)
const days = ref(365)

const PERIODS = [
	{ label: 'Last 30 days', value: 30 },
	{ label: 'Last 90 days', value: 90 },
	{ label: 'Last year', value: 365 },
	{ label: 'Everything', value: 0 },
]

watch(
	() => [props.open, props.customer],
	([open]) => {
		if (open && props.customer) load()
	},
	{ immediate: true },
)
watch(days, () => {
	if (props.open && props.customer) load()
})

async function load() {
	loading.value = true
	try {
		data.value = await getCustomerLedger({ customer: props.customer, days: days.value })
	} catch (e) {
		emit('notify', { message: e.message || 'Could not load the ledger', tone: 'bad' })
		emit('update:open', false)
	} finally {
		loading.value = false
	}
}
</script>

<template>
	<Dialog
		:model-value="open"
		:options="{ title: data ? `${data.customer_name} · account` : 'Account', size: '4xl' }"
		@update:model-value="emit('update:open', $event)"
	>
		<template #body-content>
			<div v-if="loading && !data" class="grid h-40 place-items-center">
				<Spinner class="h-5 w-5" />
			</div>

			<div v-else-if="data" class="flex flex-col gap-3">
				<div class="flex flex-wrap items-end gap-3">
					<div class="rounded-lg bg-surface-gray-2 px-3 py-2">
						<div class="text-p-xs text-ink-gray-5">Balance</div>
						<!-- A debit balance means they owe us; a credit means we hold
						     their money. Both happen, so the label follows the sign. -->
						<div
							class="tabular text-p-lg font-semibold"
							:class="data.closing > 0 ? 'text-ink-red-3' : 'text-ink-gray-9'"
						>
							{{ fmtMoney(Math.abs(data.closing)) }}
							<span class="text-p-xs font-normal text-ink-gray-5">
								{{ data.closing > 0 ? 'owed to us' : data.closing < 0 ? 'in credit' : 'settled' }}
							</span>
						</div>
					</div>
					<div v-if="data.opening" class="rounded-lg bg-surface-gray-2 px-3 py-2">
						<div class="text-p-xs text-ink-gray-5">Brought forward</div>
						<div class="tabular text-p-lg font-semibold text-ink-gray-7">
							{{ fmtMoney(data.opening) }}
						</div>
					</div>
					<div v-if="data.mobile_no" class="text-p-sm text-ink-gray-6">{{ data.mobile_no }}</div>
					<div class="ml-auto w-[170px]">
						<FormControl type="select" v-model="days" :options="PERIODS" />
					</div>
				</div>

				<div class="max-h-[55vh] overflow-auto rounded-lg border border-outline-gray-2">
					<DataTable
						:columns="data.columns"
						:rows="data.rows"
						empty-text="Nothing on this account in this period."
					/>
				</div>
			</div>
		</template>
	</Dialog>
</template>
