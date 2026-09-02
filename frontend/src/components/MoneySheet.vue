<script setup>
import { computed, ref, watch } from 'vue'
import { Button, Dialog, FormControl } from 'frappe-ui'
import {
	getPayAccounts,
	getSupplierOwed,
	payCustomer,
	payPurchaseInvoice,
	paySupplier,
	transferFunds,
	getSettingsLinkOptions,
} from '@/data/api'
import { fmtMoney } from '@/utils/format'
import LinkField from './LinkField.vue'
import LucideArrowDown from '~icons/lucide/arrow-down'

/**
 * Money moving, in one dialog with four jobs.
 *
 * Transferring between the shop's own accounts, paying one supplier bill,
 * paying a supplier a lump sum, and taking money from a customer are four
 * different documents underneath — but on screen they are the same short form:
 * how much, out of or into which account, and what to write on it. Four
 * dialogs would drift apart in wording and validation the first time one
 * changed.
 *
 * Every mode picks a **real account** from the same list the Accounts screen
 * shows, so money never lands somewhere the shop cannot see it.
 */
const props = defineProps({
	modelValue: { type: Boolean, default: false },
	/** 'transfer' | 'pay-invoice' | 'pay-supplier' | 'receive' */
	mode: { type: String, default: 'transfer' },
	/** For 'pay-invoice': { name, supplier_name, grand_total, outstanding }. */
	invoice: { type: Object, default: null },
	/** For 'pay-supplier': the supplier id. */
	supplier: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'done', 'notify'])

const accounts = ref([])
const busy = ref(false)
const owed = ref(null)

const from = ref('')
const to = ref('')
const amount = ref('')
const reference = ref('')
const party = ref('')
const date = ref(new Date().toISOString().slice(0, 10))

const TITLES = {
	transfer: { title: 'Transfer funds', hint: 'Move money between your accounts' },
	'pay-invoice': { title: 'Record payment', hint: '' },
	'pay-supplier': { title: 'Pay supplier', hint: 'Settles the oldest bills first' },
	receive: { title: 'Receive payment', hint: 'Settles the oldest sales first' },
}
const heading = computed(() => TITLES[props.mode] || TITLES.transfer)

/** The account money comes out of — or, when receiving, lands in. */
const accountLabel = computed(() => (props.mode === 'receive' ? 'Into' : 'Mode of payment'))

const sourceBalance = computed(
	() => accounts.value.find((a) => a.account === from.value)?.balance ?? null,
)

/**
 * The ceiling on this payment, and why there is one.
 *
 * A transfer cannot exceed what is in the source account; a bill payment
 * cannot exceed what is still owed on it. Both are enforced on the server too —
 * this is so the cashier finds out while typing rather than after pressing the
 * button.
 */
const cap = computed(() => {
	if (props.mode === 'transfer') return sourceBalance.value
	if (props.mode === 'pay-invoice') return props.invoice?.outstanding ?? null
	if (props.mode === 'pay-supplier') return owed.value?.total ?? null
	return null
})

const overCap = computed(
	() => cap.value !== null && Number(amount.value || 0) > Number(cap.value) + 0.001,
)

const blocker = computed(() => {
	if (!Number(amount.value)) return 'Enter an amount'
	if (overCap.value) return `That is more than the ${fmtMoney(cap.value)} available`
	if (props.mode === 'transfer') {
		if (!from.value || !to.value) return 'Choose both accounts'
		if (from.value === to.value) return 'Choose two different accounts'
	} else if (!from.value) {
		return 'Choose an account'
	}
	if (props.mode === 'pay-supplier' && !party.value) return 'Choose a supplier'
	if (props.mode === 'receive' && !party.value) return 'Choose a customer'
	return null
})

watch(
	() => props.modelValue,
	async (open) => {
		if (!open) return
		reference.value = ''
		date.value = new Date().toISOString().slice(0, 10)
		from.value = ''
		to.value = ''
		party.value = props.supplier || ''
		owed.value = null
		// Pre-filled with what is owed: the commonest payment is the whole bill,
		// and a cashier paying it in full should not have to retype the figure.
		amount.value = props.mode === 'pay-invoice' ? props.invoice?.outstanding || '' : ''
		try {
			accounts.value = await getPayAccounts()
		} catch (e) {
			emit('notify', { message: e.message || 'Could not load accounts', tone: 'bad' })
		}
		if (props.mode === 'pay-supplier' && props.supplier) await loadOwed(props.supplier)
	},
)

async function loadOwed(supplier) {
	try {
		owed.value = await getSupplierOwed({ supplier })
		amount.value = owed.value.total || ''
	} catch {
		owed.value = null
	}
}

watch(party, (v) => {
	if (props.mode === 'pay-supplier' && v) loadOwed(v)
})

const partyFetcher = (doctype) => async (search) => {
	const rows = await getSettingsLinkOptions({ doctype, search })
	return (rows || []).map((r) => ({ label: r.name || r, value: r.name || r }))
}

async function submit() {
	if (blocker.value || busy.value) return
	busy.value = true
	try {
		let res
		if (props.mode === 'transfer') {
			res = await transferFunds({
				fromAccount: from.value,
				toAccount: to.value,
				amount: Number(amount.value),
				postingDate: date.value,
				reference: reference.value,
			})
		} else if (props.mode === 'pay-invoice') {
			res = await payPurchaseInvoice({
				invoice: props.invoice.name,
				amount: Number(amount.value),
				paidFrom: from.value,
				reference: reference.value,
				postingDate: date.value,
			})
		} else if (props.mode === 'pay-supplier') {
			res = await paySupplier({
				supplier: party.value,
				amount: Number(amount.value),
				paidFrom: from.value,
				reference: reference.value,
				postingDate: date.value,
			})
		} else {
			res = await payCustomer({
				customer: party.value,
				amount: Number(amount.value),
				reference: reference.value,
			})
		}
		emit('notify', { message: res.message, tone: 'good' })
		emit('done', res)
		emit('update:modelValue', false)
	} catch (e) {
		emit('notify', { message: e.message || 'Could not post that', tone: 'bad' })
	} finally {
		busy.value = false
	}
}
</script>

<template>
	<Dialog
		:model-value="modelValue"
		:options="{ title: heading.title, size: 'lg' }"
		@update:model-value="emit('update:modelValue', $event)"
	>
		<template #body-content>
			<div class="flex flex-col gap-3">
				<p v-if="heading.hint" class="-mt-1 text-p-xs text-ink-gray-5">{{ heading.hint }}</p>

				<!-- What is being paid, before anything is typed. A payment form that
				     does not show the bill leaves the cashier checking the amount
				     against a screen they have already left. -->
				<div
					v-if="mode === 'pay-invoice' && invoice"
					class="grid grid-cols-2 gap-3 rounded-lg border border-outline-gray-2 bg-surface-gray-1 p-3"
				>
					<div>
						<div class="text-p-xs text-ink-gray-5">Invoice total</div>
						<div class="tabular text-p-base font-semibold text-ink-gray-9">
							{{ fmtMoney(invoice.grand_total) }}
						</div>
					</div>
					<div>
						<div class="text-p-xs text-ink-gray-5">Still owed</div>
						<div class="tabular text-p-base font-semibold text-ink-red-3">
							{{ fmtMoney(invoice.outstanding) }}
						</div>
					</div>
				</div>

				<LinkField
					v-if="mode === 'pay-supplier'"
					v-model="party"
					:fetcher="partyFetcher('Supplier')"
					label="Supplier"
					required
				/>
				<LinkField
					v-if="mode === 'receive'"
					v-model="party"
					:fetcher="partyFetcher('Customer')"
					label="Customer"
					required
				/>

				<p v-if="mode === 'pay-supplier' && owed" class="text-p-xs text-ink-gray-5">
					Owed {{ fmtMoney(owed.total) }} across {{ owed.invoices.length }} bill(s)
				</p>

				<!-- From / To, for a transfer. The arrow between them is the whole
				     point of the layout: it says which way the money goes without a
				     word of explanation. -->
				<div v-if="mode === 'transfer'" class="flex flex-col gap-1">
					<label class="text-p-xs text-ink-gray-5">From</label>
					<select
						v-model="from"
						class="h-10 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 focus:bg-surface-white focus:outline-none"
					>
						<option value="">Select an account</option>
						<option v-for="a in accounts" :key="a.account" :value="a.account">
							{{ a.label }} — {{ fmtMoney(a.balance) }}
						</option>
					</select>
					<div class="grid place-items-center py-0.5 text-ink-gray-5">
						<LucideArrowDown class="h-4 w-4" />
					</div>
					<label class="text-p-xs text-ink-gray-5">To</label>
					<select
						v-model="to"
						class="h-10 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 focus:bg-surface-white focus:outline-none"
					>
						<option value="">Select an account</option>
						<option
							v-for="a in accounts"
							:key="a.account"
							:value="a.account"
							:disabled="a.account === from"
						>
							{{ a.label }} — {{ fmtMoney(a.balance) }}
						</option>
					</select>
				</div>

				<FormControl v-model="amount" type="number" label="Amount" placeholder="0" />
				<p v-if="cap !== null" class="-mt-1 text-p-xs" :class="overCap ? 'text-ink-red-3' : 'text-ink-gray-5'">
					{{ overCap ? `Only ${fmtMoney(cap)} is available` : `Up to ${fmtMoney(cap)}` }}
				</p>
				<p v-else-if="mode === 'transfer'" class="-mt-1 text-p-xs text-ink-gray-5">
					Available balance shows once a source is selected.
				</p>

				<div v-if="mode !== 'transfer' && mode !== 'receive'" class="flex flex-col gap-1">
					<label class="text-p-xs text-ink-gray-5">{{ accountLabel }}</label>
					<select
						v-model="from"
						class="h-10 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 focus:bg-surface-white focus:outline-none"
					>
						<option value="">Select an account</option>
						<option v-for="a in accounts" :key="a.account" :value="a.account">
							{{ a.label }} — {{ fmtMoney(a.balance) }}
						</option>
					</select>
				</div>

				<div class="grid grid-cols-2 gap-3">
					<FormControl v-model="reference" type="text" label="Reference" placeholder="Txn ID" />
					<FormControl v-model="date" type="date" label="Date" />
				</div>
			</div>
		</template>

		<template #actions>
			<div class="flex justify-end gap-2">
				<Button label="Cancel" @click="emit('update:modelValue', false)" />
				<Button
					variant="solid"
					theme="gray"
					:loading="busy"
					:disabled="!!blocker"
					:label="blocker || heading.title"
					@click="submit"
				/>
			</div>
		</template>
	</Dialog>
</template>
