<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Button } from 'frappe-ui'
import { listParties } from '@/data/api'
import { fmtMoney } from '@/utils/format'
import PageHeader from '@/components/PageHeader.vue'
import StatementDialog from '@/components/StatementDialog.vue'
import MasterSheet from '@/components/MasterSheet.vue'
import LucideSearch from '~icons/lucide/search'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucidePlus from '~icons/lucide/plus'
import LucidePencil from '~icons/lucide/pencil'
import LucideChevronLeft from '~icons/lucide/chevron-left'
import LucideChevronRight from '~icons/lucide/chevron-right'

/**
 * Receivables and Payables — one screen, told which by the route.
 *
 * These were two routes onto the report view, which never noticed the route
 * changing, so Payables straight after Receivables kept showing customers. This
 * reads `partyType` from the route every time it changes and reloads, so the
 * two cannot bleed into each other.
 *
 * A row opens the party's statement. The pencil edits the record itself.
 */
const route = useRoute()
const partyType = computed(() => route.meta?.partyType || 'Customer')
const isCustomer = computed(() => partyType.value === 'Customer')

const PAGE_SIZES = [10, 20, 50, 100]

const rows = ref([])
const total = ref(0)
const totalOutstanding = ref(0)
const owing = ref(0)
const loading = ref(false)
const search = ref('')
const owingOnly = ref(false)
const start = ref(0)
const pageLength = ref(20)

const toast = ref(null)
function notify({ message, tone }) {
	toast.value = { message, tone }
	setTimeout(() => (toast.value = null), 3500)
}

let seq = 0
async function load() {
	const mine = ++seq
	loading.value = true
	try {
		const res = await listParties({
			partyType: partyType.value,
			search: search.value.trim(),
			owingOnly: owingOnly.value,
			start: start.value,
			pageLength: pageLength.value,
		})
		if (mine !== seq) return
		rows.value = res.rows
		total.value = res.total
		totalOutstanding.value = res.total_outstanding
		owing.value = res.owing
	} catch (e) {
		if (mine === seq) notify({ message: e.message || 'Could not load the list', tone: 'bad' })
	} finally {
		if (mine === seq) loading.value = false
	}
}

watch(
	partyType,
	() => {
		rows.value = []
		search.value = ''
		start.value = 0
		load()
	},
	{ immediate: true },
)

let timer = null
watch(search, () => {
	clearTimeout(timer)
	timer = setTimeout(() => {
		start.value = 0
		load()
	}, 250)
})
watch([owingOnly, pageLength], () => {
	start.value = 0
	load()
})

const lastIndex = computed(() => Math.min(start.value + pageLength.value, total.value))
function page(delta) {
	const next = start.value + delta * pageLength.value
	if (next < 0 || next >= total.value) return
	start.value = next
	load()
}

const copy = computed(() =>
	isCustomer.value
		? {
				title: 'Receivables',
				subtitle: 'Customers and what they owe — open one for the statement',
				noun: 'customer',
				owingLabel: 'owe you',
				searchHint: 'Search customers…',
				newLabel: 'New customer',
				outstanding: 'Outstanding',
			}
		: {
				title: 'Payables',
				subtitle: 'Suppliers and what you owe them — open one for the statement',
				noun: 'supplier',
				owingLabel: 'are owed',
				searchHint: 'Search suppliers…',
				newLabel: 'New supplier',
				outstanding: 'We owe',
			},
)

/* ---------- statement ---------- */

const statementOpen = ref(false)
const statementParty = ref('')
function openStatement(row) {
	statementParty.value = row.name
	statementOpen.value = true
}

/* ---------- create / edit ---------- */

const masterOpen = ref(false)
const masterEdit = ref(null)
function openNew() {
	masterEdit.value = null
	masterOpen.value = true
}
function openEdit(row) {
	masterEdit.value = row.name
	masterOpen.value = true
}
function onSaved() {
	load()
}

const kindTone = (kind) =>
	kind === 'Company'
		? 'bg-surface-green-2 text-ink-green-3'
		: kind === 'Individual'
			? 'bg-surface-blue-1 text-ink-blue-3'
			: 'bg-surface-gray-2 text-ink-gray-6'
</script>

<template>
	<div class="relative flex min-h-0 flex-1 flex-col overflow-hidden">
		<PageHeader :title="copy.title" :subtitle="copy.subtitle">
			<template #primary>
				<Button variant="solid" :icon-left="LucidePlus" :label="copy.newLabel" @click="openNew" />
			</template>
			<template #actions>
				<div class="relative w-full sm:w-72">
					<LucideSearch class="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-gray-4" />
					<input
						v-model="search"
						type="search"
						:placeholder="copy.searchHint"
						class="h-8 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 pl-8 pr-2 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
					/>
				</div>
				<label class="flex cursor-pointer items-center gap-2 text-p-sm text-ink-gray-7">
					<input v-model="owingOnly" type="checkbox" class="rounded border-outline-gray-3" />
					Only with a balance
				</label>
				<div class="ml-auto flex items-center gap-2">
					<span class="tabular text-p-sm text-ink-gray-6">
						{{ owing }} {{ copy.owingLabel }} ·
						<span class="font-semibold text-ink-red-3">{{ fmtMoney(totalOutstanding) }}</span>
					</span>
					<Button variant="subtle" :icon-left="LucideRefreshCw" :loading="loading" label="Refresh" @click="load" />
					<span class="text-p-xs text-ink-gray-5">{{ total }} {{ copy.noun }}{{ total === 1 ? '' : 's' }}</span>
				</div>
			</template>
		</PageHeader>

		<div class="min-h-0 flex-1 overflow-auto bg-surface-white">
			<table class="w-full min-w-[900px] border-collapse text-p-sm">
				<thead class="sticky top-0 z-10 bg-surface-gray-2">
					<tr class="text-p-xs uppercase tracking-wide text-ink-gray-5">
						<th class="w-10 px-3 py-2 text-left font-medium">#</th>
						<th class="px-3 py-2 text-left font-medium">{{ isCustomer ? 'Customer name' : 'Supplier name' }}</th>
						<th class="px-3 py-2 text-left font-medium">Mobile number</th>
						<th class="px-3 py-2 text-left font-medium">Email address</th>
						<th class="px-3 py-2 text-left font-medium">Location</th>
						<th class="px-3 py-2 text-left font-medium">{{ isCustomer ? 'Customer type' : 'Supplier type' }}</th>
						<th v-if="isCustomer" class="px-3 py-2 text-right font-medium">Credit limit</th>
						<th v-else class="px-3 py-2 text-right font-medium">Unpaid bills</th>
						<th class="px-3 py-2 text-right font-medium">{{ copy.outstanding }}</th>
						<th class="px-3 py-2 text-right font-medium">{{ isCustomer ? 'Credit balance' : 'Paid in advance' }}</th>
						<th class="w-10 px-3 py-2" />
					</tr>
				</thead>
				<tbody>
					<tr v-if="loading && !rows.length">
						<td colspan="10" class="px-3 py-10 text-center text-ink-gray-5">Loading…</td>
					</tr>
					<tr v-else-if="!rows.length">
						<td colspan="10" class="px-3 py-10 text-center text-ink-gray-5">
							{{ search || owingOnly ? 'Nothing matches.' : `No ${copy.noun}s yet.` }}
						</td>
					</tr>
					<tr
						v-for="(row, i) in rows"
						:key="row.name"
						class="cursor-pointer border-t border-outline-gray-1 transition-colors hover:bg-surface-gray-1"
						@click="openStatement(row)"
					>
						<td class="tabular px-3 py-2.5 text-ink-gray-5">{{ start + i + 1 }}</td>
						<td class="px-3 py-2.5 font-medium text-ink-gray-9">{{ row.title }}</td>
						<td class="px-3 py-2.5 text-ink-gray-7">{{ row.mobile_no || '—' }}</td>
						<td class="max-w-[200px] truncate px-3 py-2.5 text-ink-gray-7">{{ row.email_id || '—' }}</td>
						<td class="px-3 py-2.5 text-ink-gray-7">{{ row.location || '—' }}</td>
						<td class="px-3 py-2.5">
							<span v-if="row.party_kind" class="rounded-full px-2 py-0.5 text-p-xs font-medium" :class="kindTone(row.party_kind)">
								{{ row.party_kind }}
							</span>
							<span v-else class="text-ink-gray-5">—</span>
						</td>
						<td v-if="isCustomer" class="tabular px-3 py-2.5 text-right text-ink-gray-7">
							{{ row.credit_limit != null ? fmtMoney(row.credit_limit) : '—' }}
						</td>
						<td v-else class="tabular px-3 py-2.5 text-right text-ink-gray-7">{{ row.invoices || '—' }}</td>
						<td
							class="tabular px-3 py-2.5 text-right font-medium"
							:class="row.outstanding > 0 ? 'text-ink-red-3' : 'text-ink-gray-5'"
						>
							{{ row.outstanding > 0 ? fmtMoney(row.outstanding) : '—' }}
						</td>
						<td v-if="isCustomer" class="tabular px-3 py-2.5 text-right"
							:class="row.available_credit != null && row.available_credit < 0 ? 'text-ink-red-3' : 'text-ink-gray-7'">
							{{ row.available_credit != null ? fmtMoney(row.available_credit) : row.advance > 0 ? fmtMoney(row.advance) : '—' }}
						</td>
						<td v-else class="tabular px-3 py-2.5 text-right text-ink-gray-7">
							{{ row.advance > 0 ? fmtMoney(row.advance) : '—' }}
						</td>
						<td class="px-3 py-2.5 text-right">
							<button
								class="grid h-8 w-8 place-items-center rounded-md text-ink-gray-5 hover:bg-surface-gray-2 hover:text-ink-gray-8"
								:aria-label="`Edit ${row.title}`"
								title="Edit"
								@click.stop="openEdit(row)"
							>
								<LucidePencil class="h-4 w-4" />
							</button>
						</td>
					</tr>
				</tbody>
			</table>
		</div>

		<footer class="flex shrink-0 flex-wrap items-center gap-3 border-t border-outline-gray-2 bg-surface-white px-4 py-2 text-p-sm text-ink-gray-6">
			<span class="tabular">{{ total ? start + 1 : 0 }}–{{ lastIndex }} of {{ total }}</span>
			<select
				v-model.number="pageLength"
				class="h-8 rounded border border-outline-gray-2 bg-surface-gray-2 pl-2 pr-7 text-p-sm text-ink-gray-8"
				aria-label="Rows per page"
			>
				<option v-for="n in PAGE_SIZES" :key="n" :value="n">{{ n }}</option>
			</select>
			<div class="ml-auto flex items-center gap-1">
				<Button variant="ghost" :icon-left="LucideChevronLeft" label="Previous" :disabled="start === 0" @click="page(-1)" />
				<Button variant="ghost" :icon-right="LucideChevronRight" label="Next" :disabled="lastIndex >= total" @click="page(1)" />
			</div>
		</footer>

		<StatementDialog
			v-model:open="statementOpen"
			:party-type="partyType"
			:party="statementParty"
			@changed="load"
			@notify="notify"
		/>

		<MasterSheet
			v-model:open="masterOpen"
			:initial-key="isCustomer ? 'customer' : 'supplier'"
			:edit-name="masterEdit"
			lock-type
			@created="onSaved"
			@notify="notify"
		/>

		<div
			v-if="toast"
			class="pos-toast pointer-events-none absolute bottom-16 left-1/2 -translate-x-1/2 rounded-lg px-4 py-2.5 text-p-sm font-medium text-ink-white shadow-lg"
			:class="toast.tone === 'bad' ? 'bg-surface-red-5' : 'bg-surface-green-3'"
		>
			{{ toast.message }}
		</div>
	</div>
</template>
