<script setup>
import { computed, ref, watch } from 'vue'
import { Button, Dialog, Spinner } from 'frappe-ui'
import { getPartyStatement, setCreditLimit } from '@/data/api'
import { fmtMoney } from '@/utils/format'
import { printHtml } from '@/utils/silentPrint'
import DateField from './DateField.vue'
import MoneySheet from './MoneySheet.vue'
import LucideShield from '~icons/lucide/shield'
import LucideCircleAlert from '~icons/lucide/circle-alert'
import LucideCircleCheck from '~icons/lucide/circle-check'
import LucideCreditCard from '~icons/lucide/credit-card'
import LucidePrinter from '~icons/lucide/printer'
import LucideFileText from '~icons/lucide/file-text'
import LucideExternalLink from '~icons/lucide/external-link'
import LucidePencil from '~icons/lucide/pencil'

/**
 * A customer's or supplier's account, opened from the balances list.
 *
 * The three figures across the top and the statement beneath them come from one
 * call (`parties.statement`), so they cannot disagree. The date range only moves
 * the statement: the tiles are always today's position, which is what someone
 * deciding whether to give more credit is asking about.
 */
const props = defineProps({
	open: { type: Boolean, default: false },
	/** 'Customer' | 'Supplier' */
	partyType: { type: String, default: 'Customer' },
	party: { type: String, default: '' },
})

const emit = defineEmits(['update:open', 'changed', 'notify'])

const isCustomer = computed(() => props.partyType === 'Customer')

function iso(d) {
	const shifted = new Date(d.getTime() - d.getTimezoneOffset() * 60000)
	return shifted.toISOString().slice(0, 10)
}
function monthStart() {
	const d = new Date()
	return iso(new Date(d.getFullYear(), d.getMonth(), 1))
}

const fromDate = ref(monthStart())
const toDate = ref(iso(new Date()))
const data = ref(null)
const loading = ref(false)

const editingLimit = ref(false)
const limitInput = ref('')
const savingLimit = ref(false)
const payOpen = ref(false)

watch(
	() => [props.open, props.party],
	([open]) => {
		if (!open || !props.party) return
		data.value = null
		editingLimit.value = false
		fromDate.value = monthStart()
		toDate.value = iso(new Date())
		load()
	},
	{ immediate: true },
)
watch([fromDate, toDate], () => {
	if (props.open && props.party) load()
})

async function load() {
	loading.value = true
	try {
		data.value = await getPartyStatement({
			partyType: props.partyType,
			party: props.party,
			fromDate: fromDate.value,
			toDate: toDate.value,
		})
	} catch (e) {
		emit('notify', { message: e.message || 'Could not load the statement', tone: 'bad' })
	} finally {
		loading.value = false
	}
}

const tiles = computed(() => {
	const d = data.value
	if (!d) return []
	if (isCustomer.value) {
		return [
			{
				label: 'Credit limit',
				value: d.credit_limit != null ? fmtMoney(d.credit_limit) : 'No limit',
				hint: d.credit_limit != null ? '' : 'Not set',
				icon: LucideShield,
				tone: 'blue',
				editable: d.can_set_credit_limit,
			},
			{
				label: 'Running balance',
				value: fmtMoney(d.outstanding),
				hint: d.advance > 0 ? `${fmtMoney(d.advance)} held for them` : 'Total outstanding',
				icon: LucideCircleAlert,
				tone: d.outstanding > 0 ? 'red' : 'gray',
			},
			{
				label: 'Available credit',
				value: d.available_credit != null ? fmtMoney(d.available_credit) : '—',
				hint: d.available_credit != null && d.available_credit < 0 ? 'Over the limit' : '',
				icon: LucideCircleCheck,
				tone: d.available_credit != null && d.available_credit < 0 ? 'red' : 'green',
			},
		]
	}
	return [
		{
			label: 'We owe',
			value: fmtMoney(d.outstanding),
			hint: 'Total outstanding',
			icon: LucideCircleAlert,
			tone: d.outstanding > 0 ? 'red' : 'gray',
		},
		{
			label: 'Paid in advance',
			value: fmtMoney(d.advance),
			hint: 'Not yet set against a bill',
			icon: LucideCircleCheck,
			tone: 'green',
		},
		{
			label: 'In this range',
			value: fmtMoney(d.rows.reduce((s, r) => s + r.charged, 0)),
			hint: 'Billed between the dates',
			icon: LucideFileText,
			tone: 'blue',
		},
	]
})

const TONES = {
	blue: { bar: 'bg-surface-blue-2', icon: 'bg-surface-blue-1 text-ink-blue-3', value: 'text-ink-gray-9' },
	red: { bar: 'bg-surface-red-5', icon: 'bg-surface-red-1 text-ink-red-3', value: 'text-ink-red-3' },
	green: { bar: 'bg-surface-green-3', icon: 'bg-surface-green-1 text-ink-green-3', value: 'text-ink-green-3' },
	gray: { bar: 'bg-surface-gray-4', icon: 'bg-surface-gray-2 text-ink-gray-6', value: 'text-ink-gray-9' },
}

function startEditLimit() {
	limitInput.value = data.value?.credit_limit ?? ''
	editingLimit.value = true
}

async function saveLimit() {
	savingLimit.value = true
	try {
		const res = await setCreditLimit({ customer: props.party, creditLimit: Number(limitInput.value) || 0 })
		emit('notify', { message: res.message, tone: 'good' })
		editingLimit.value = false
		await load()
		emit('changed')
	} catch (e) {
		emit('notify', { message: e.message || 'Could not set the credit limit', tone: 'bad' })
	} finally {
		savingLimit.value = false
	}
}

function onPaid() {
	load()
	emit('changed')
}

const labels = computed(() =>
	isCustomer.value
		? { charged: 'Billed', settled: 'Paid' }
		: { charged: 'Billed to us', settled: 'Paid' },
)

const esc = (v) =>
	String(v ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c])

/** A plain printable statement, drawn here so it matches the screen exactly. */
function print() {
	const d = data.value
	if (!d) return
	const body = d.rows
		.map(
			(r) => `<tr><td>${esc(r.posting_date)}</td><td>${esc(r.voucher_type)}</td><td>${esc(r.voucher_no)}</td>
			<td class="n">${r.charged ? esc(fmtMoney(r.charged)) : ''}</td><td class="n">${r.settled ? esc(fmtMoney(r.settled)) : ''}</td>
			<td class="n">${esc(fmtMoney(r.balance))}</td></tr>`,
		)
		.join('')
	const html = `<!doctype html><html><head><meta charset="utf-8"><title>Statement — ${esc(d.title)}</title>
	<style>
		body{font-family:system-ui,sans-serif;font-size:12px;color:#111;margin:24px}
		h1{font-size:18px;margin:0 0 2px} .muted{color:#666}
		table{width:100%;border-collapse:collapse;margin-top:14px}
		th,td{padding:5px 6px;border-bottom:1px solid #ddd;text-align:left}
		th{background:#f3f3f3} .n{text-align:right;font-variant-numeric:tabular-nums}
		.sum{display:flex;gap:24px;margin-top:12px} .sum b{display:block;font-size:14px}
	</style></head><body>
	<h1>${esc(d.title)}</h1>
	<div class="muted">${esc(d.party_type)} statement · ${esc(d.from_date)} to ${esc(d.to_date)}${d.company ? ' · ' + esc(d.company) : ''}</div>
	<div class="muted">${[d.mobile_no, d.email_id, d.location].filter(Boolean).map(esc).join(' · ')}</div>
	<div class="sum">
		<div>Opening<b>${esc(fmtMoney(d.opening))}</b></div>
		<div>Closing<b>${esc(fmtMoney(d.closing))}</b></div>
		${d.credit_limit != null ? `<div>Credit limit<b>${esc(fmtMoney(d.credit_limit))}</b></div>` : ''}
	</div>
	<table><thead><tr><th>Date</th><th>Type</th><th>Document</th><th class="n">${labels.value.charged}</th><th class="n">${labels.value.settled}</th><th class="n">Balance</th></tr></thead>
	<tbody><tr><td colspan="5">Balance brought forward</td><td class="n">${esc(fmtMoney(d.opening))}</td></tr>${body}</tbody></table>
	</body></html>`
	printHtml(html, () => emit('notify', { message: 'Could not reach the printer', tone: 'bad' }))
}
</script>

<template>
	<Dialog
		:model-value="open"
		:options="{ title: data?.title || party || 'Statement', size: '3xl' }"
		@update:model-value="emit('update:open', $event)"
	>
		<template #body-content>
			<div v-if="loading && !data" class="grid h-48 place-items-center">
				<Spinner class="h-5 w-5" />
			</div>

			<div v-else-if="data" class="flex flex-col gap-4">
				<div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
					<div v-for="f in [
						['Mobile number', data.mobile_no],
						['Email address', data.email_id],
						['Location', data.location],
						[isCustomer ? 'Customer type' : 'Supplier type', data.party_kind],
					]" :key="f[0]" class="min-w-0">
						<div class="text-p-xs uppercase tracking-wide text-ink-gray-5">{{ f[0] }}</div>
						<div class="truncate text-p-sm text-ink-gray-9">{{ f[1] || '—' }}</div>
					</div>
				</div>

				<div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
					<div
						v-for="t in tiles"
						:key="t.label"
						class="relative overflow-hidden rounded-xl border border-outline-gray-2 bg-surface-white p-3"
					>
						<div class="absolute inset-x-0 top-0 h-1" :class="TONES[t.tone].bar" />
						<div class="flex items-start justify-between gap-2">
							<span class="grid h-7 w-7 place-items-center rounded-full" :class="TONES[t.tone].icon">
								<component :is="t.icon" class="h-4 w-4" />
							</span>
							<span class="flex items-center gap-1 text-p-xs uppercase tracking-wide text-ink-gray-5">
								{{ t.label }}
								<button
									v-if="t.editable && !editingLimit"
									class="grid h-6 w-6 place-items-center rounded text-ink-gray-5 hover:bg-surface-gray-2"
									aria-label="Change credit limit"
									title="Change credit limit"
									@click="startEditLimit"
								>
									<LucidePencil class="h-3.5 w-3.5" />
								</button>
							</span>
						</div>
						<div v-if="t.editable && editingLimit" class="mt-2 flex items-center gap-1.5">
							<input
								v-model="limitInput"
								type="number"
								min="0"
								inputmode="decimal"
								placeholder="0 = no limit"
								class="tabular h-8 w-full min-w-0 rounded border border-outline-gray-3 bg-surface-white px-2 text-p-sm text-ink-gray-9 focus:border-outline-gray-5 focus:outline-none"
								@keydown.enter="saveLimit"
							/>
							<Button size="sm" variant="solid" :loading="savingLimit" label="Save" @click="saveLimit" />
							<Button size="sm" variant="ghost" label="Cancel" @click="editingLimit = false" />
						</div>
						<template v-else>
							<div class="tabular mt-2 text-xl font-semibold" :class="TONES[t.tone].value">{{ t.value }}</div>
							<div v-if="t.hint" class="text-p-xs text-ink-gray-5">{{ t.hint }}</div>
						</template>
					</div>
				</div>

				<div class="flex justify-end">
					<button
						class="flex h-8 items-center gap-1.5 rounded-lg bg-surface-green-2 px-3 text-p-sm font-medium text-ink-green-3 transition-colors hover:opacity-90"
						@click="payOpen = true"
					>
						<LucideCreditCard class="h-4 w-4" />
						{{ isCustomer ? 'Receive payment' : 'Pay supplier' }}
					</button>
				</div>

				<div class="rounded-xl border border-outline-gray-2">
					<div class="flex flex-wrap items-end gap-3 border-b border-outline-gray-2 p-3">
						<div class="mr-auto text-p-base font-semibold text-ink-gray-9">Statement</div>
						<DateField v-model="fromDate" label="From" :max="toDate" class="w-[170px]" />
						<DateField v-model="toDate" label="To" :min="fromDate" class="w-[170px]" />
						<Button :icon-left="LucidePrinter" label="Print" :disabled="!data" @click="print" />
					</div>

					<div v-if="loading" class="grid h-32 place-items-center">
						<Spinner class="h-5 w-5" />
					</div>
					<div v-else-if="!data.rows.length" class="flex flex-col items-center gap-2 py-10 text-center">
						<span class="grid h-10 w-10 place-items-center rounded-full bg-surface-gray-2 text-ink-gray-5">
							<LucideFileText class="h-5 w-5" />
						</span>
						<p class="text-p-sm text-ink-gray-6">No transactions in this range</p>
						<p class="tabular text-p-xs text-ink-gray-5">Balance on {{ data.to_date }}: {{ fmtMoney(data.closing) }}</p>
					</div>
					<div v-else class="max-h-[40vh] overflow-auto">
						<table class="w-full border-collapse text-p-sm">
							<thead class="sticky top-0 bg-surface-gray-2">
								<tr class="text-p-xs text-ink-gray-6">
									<th class="px-3 py-2 text-left font-medium">Date</th>
									<th class="px-3 py-2 text-left font-medium">Document</th>
									<th class="px-3 py-2 text-right font-medium">{{ labels.charged }}</th>
									<th class="px-3 py-2 text-right font-medium">{{ labels.settled }}</th>
									<th class="px-3 py-2 text-right font-medium">Balance</th>
								</tr>
							</thead>
							<tbody>
								<tr class="bg-surface-gray-1 text-ink-gray-6">
									<td class="px-3 py-2" colspan="4">Balance brought forward</td>
									<td class="tabular px-3 py-2 text-right">{{ fmtMoney(data.opening) }}</td>
								</tr>
								<tr v-for="r in data.rows" :key="r.voucher_no + r.posting_date" class="border-t border-outline-gray-1">
									<td class="whitespace-nowrap px-3 py-2 text-ink-gray-7">{{ r.posting_date }}</td>
									<td class="px-3 py-2">
										<div class="text-ink-gray-9">{{ r.voucher_no }}</div>
										<div class="text-p-xs text-ink-gray-5">{{ r.voucher_type }}</div>
									</td>
									<td class="tabular px-3 py-2 text-right text-ink-gray-8">{{ r.charged ? fmtMoney(r.charged) : '' }}</td>
									<td class="tabular px-3 py-2 text-right text-ink-green-3">{{ r.settled ? fmtMoney(r.settled) : '' }}</td>
									<td class="tabular px-3 py-2 text-right font-medium text-ink-gray-9">{{ fmtMoney(r.balance) }}</td>
								</tr>
							</tbody>
						</table>
					</div>
				</div>
			</div>
		</template>

		<template #actions>
			<div class="flex items-center justify-between gap-2">
				<a
					v-if="data"
					:href="data.desk_url"
					target="_blank"
					rel="noopener"
					class="inline-flex items-center gap-1.5 rounded-lg border border-outline-gray-2 px-3 py-1.5 text-p-sm text-ink-gray-7 hover:bg-surface-gray-2"
				>
					<LucideExternalLink class="h-4 w-4" />
					Edit in desk
				</a>
				<span v-else />
				<Button theme="red" variant="subtle" label="Close" @click="emit('update:open', false)" />
			</div>
		</template>
	</Dialog>

	<MoneySheet
		v-model="payOpen"
		:mode="isCustomer ? 'receive' : 'pay-supplier'"
		:party="party"
		@done="onPaid"
		@notify="emit('notify', $event)"
	/>
</template>
