<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Badge, Button, Dropdown, FormControl, TabButtons } from 'frappe-ui'
import {
	getDocumentInsights,
	getPrintUrl,
	listDocumentTypes,
	listDocuments,
	runDocumentAction,
	sendDocumentWhatsapp,
} from '@/data/api'
import PageHeader from '@/components/PageHeader.vue'
import StatTiles from '@/components/StatTiles.vue'
import DataTable from '@/components/DataTable.vue'
import DocumentModal from '@/components/DocumentModal.vue'
import DocumentFormSheet from '@/components/DocumentFormSheet.vue'
import Reports from '@/views/Reports.vue'
import { moduleFor } from '@/data/navigation'
import { resolveIcon } from '@/utils/icons'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideMore from '~icons/lucide/ellipsis'
import LucideCheck from '~icons/lucide/check'
import LucideBan from '~icons/lucide/ban'
import LucideCopy from '~icons/lucide/copy'
import LucideUndo from '~icons/lucide/undo-2'
import LucidePrinter from '~icons/lucide/printer'
import LucideSend from '~icons/lucide/send'
import LucidePlus from '~icons/lucide/plus'

/**
 * Every transactional document, in one screen.
 *
 * The document type is a route parameter and everything else — columns,
 * filters, actions, which reports are worth showing — arrives from
 * `documents.list_types`. Adding Journal Entry to the registry puts it in this
 * list with no change here.
 */
const route = useRoute()
const router = useRouter()

const types = ref([])
const data = ref({ columns: [], rows: [], statuses: [], totals: {}, actions_by_docstatus: {} })
const insights = ref(null)
const loading = ref(false)
const busyRow = ref('')

const tab = ref('list')
const TABS = [
	{ label: 'List', value: 'list' },
	{ label: 'Insights', value: 'insights' },
	{ label: 'Reports', value: 'reports' },
]

// Select silently drops options with a falsy value, so "all" needs a real token.
const ALL = '__all__'
const days = ref(30)
const status = ref(ALL)
const party = ref('')
const search = ref('')
const limit = ref(100)

const PERIODS = [
	{ label: 'Last 7 days', value: 7 },
	{ label: 'Last 30 days', value: 30 },
	{ label: 'Last 90 days', value: 90 },
	{ label: 'Last year', value: 365 },
	{ label: 'All time', value: 0 },
]

/** True when a module's tab strip is already showing above this screen. */
const inModule = computed(() => !!moduleFor(route.path))

const activeKey = computed(() => route.params.key || types.value[0]?.key || null)
const activeType = computed(() => types.value.find((t) => t.key === activeKey.value) || null)

/** Grouped exactly as the reports picker groups reports, for the same reason. */
const grouped = computed(() => {
	const m = {}
	for (const t of types.value) (m[t.group] ||= []).push(t)
	return m
})

/** A trailing menu column, appended here so DataTable stays generic. */
const columns = computed(() =>
	data.value.columns?.length ? [...data.value.columns, { label: '', key: '_actions', type: 'text' }] : [],
)

const statusOptions = computed(() => [
	{ label: 'Any status', value: ALL },
	...(data.value.statuses || []).map((s) => ({ label: s, value: s })),
])

const stats = computed(() => insights.value?.stats || [])

const subtitle = computed(() => {
	const p = data.value.period
	const shown = data.value.rows?.length || 0
	const total = data.value.total || 0
	const range = p?.from ? `${p.from} to ${p.to}` : 'All time'
	return `${range} · showing ${shown} of ${total}`
})

onMounted(async () => {
	types.value = await listDocumentTypes().catch(() => [])
	if (!route.params.key && types.value.length) {
		router.replace(`/documents/${types.value[0].key}`)
		return
	}
	load()
})

/**
 * Changing document type resets the filters — carrying a status of 'Overdue'
 * onto Stock Entry would show an empty list and look like a bug. The reset
 * moves four watched refs at once, so the filter watchers are muted across it;
 * otherwise switching type would fire two or three loads for one click.
 */
let resetting = false
watch(activeKey, async () => {
	resetting = true
	status.value = ALL
	party.value = ''
	search.value = ''
	limit.value = 100
	insights.value = null
	await nextTick()
	resetting = false
	load()
})

watch([days, status, limit], () => {
	if (!resetting) load()
})
watch(tab, () => {
	if (tab.value === 'insights' && !insights.value) loadInsights()
})

let timer = null
watch([party, search], () => {
	if (resetting) return
	clearTimeout(timer)
	timer = setTimeout(load, 250)
})

async function load() {
	if (!activeKey.value) return
	loading.value = true
	try {
		data.value = await listDocuments({
			key: activeKey.value,
			days: days.value,
			status: status.value === ALL ? null : status.value,
			party: party.value,
			search: search.value,
			limit: limit.value,
		})
		if (tab.value === 'insights') loadInsights()
	} catch (e) {
		notify(e.message || 'Could not load documents', 'bad')
		data.value = { columns: [], rows: [], statuses: [], totals: {}, actions_by_docstatus: {} }
	} finally {
		loading.value = false
	}
}

async function loadInsights() {
	try {
		insights.value = await getDocumentInsights({ key: activeKey.value, days: days.value })
	} catch (e) {
		notify(e.message || 'Could not load insights', 'bad')
		insights.value = null
	}
}

/* ---------- row actions ---------- */

const open = ref(false)
const selected = ref(null)
/** Raising a new document of the type currently on screen. */
const newOpen = ref(false)

function openRow(row) {
	selected.value = row.name
	open.value = true
}

const ACTION_LABELS = {
	submit: { label: 'Submit', icon: LucideCheck },
	cancel: { label: 'Cancel', icon: LucideBan, theme: 'red' },
	amend: { label: 'Amend', icon: LucideUndo },
	duplicate: { label: 'Duplicate', icon: LucideCopy },
	print: { label: 'Print', icon: LucidePrinter },
	whatsapp: { label: 'Send on WhatsApp', icon: LucideSend },
}

/**
 * The server decides what is allowed; this only draws it. Cancelling from the
 * row menu goes through the modal instead of acting immediately — it is not
 * undoable, and a menu item one pixel from "Duplicate" is the wrong place to
 * make that decision.
 */
function rowActions(row) {
	const allowed = data.value.actions_by_docstatus?.[String(row.docstatus)] || []
	return allowed.map((action) => ({
		...ACTION_LABELS[action],
		onClick: () => rowAction(row, action),
	}))
}

async function rowAction(row, action) {
	if (action === 'cancel' || action === 'whatsapp') {
		openRow(row)
		return
	}

	if (action === 'print') {
		try {
			const { url } = await getPrintUrl({ key: activeKey.value, name: row.name })
			window.open(url, '_blank', 'noopener')
		} catch (e) {
			notify(e.message || 'Could not build a print view', 'bad')
		}
		return
	}

	busyRow.value = row.name
	try {
		const res = await runDocumentAction({ key: activeKey.value, name: row.name, action })
		notify(res.message, 'good')
		await load()
		if (tab.value === 'insights') loadInsights()
	} catch (e) {
		notify(e.message || `Could not ${action} ${row.name}`, 'bad')
	} finally {
		busyRow.value = ''
	}
}

/* ---------- toast ---------- */

const toast = ref(null)
let toastTimer = null
function notify(message, tone = 'good') {
	toast.value = { message, tone }
	clearTimeout(toastTimer)
	toastTimer = setTimeout(() => (toast.value = null), 2600)
}
</script>

<template>
	<div class="flex min-h-0 flex-1 overflow-hidden">
		<!-- Eleven document types is too many for a tab strip and too few for a
		     search box, so they live in a grouped rail like the reports picker. -->
		<!-- The full index, shown only when this screen is not already reached from
		     a module's tab strip. Two navigations for the same thing, one above the
		     other, is what made the old layout feel cluttered. -->
		<aside
			v-if="!inModule"
			class="hidden w-[210px] shrink-0 overflow-y-auto border-r border-outline-gray-2 bg-surface-white py-2 lg:block"
		>
			<div v-for="(items, group) in grouped" :key="group" class="mb-3">
				<div class="px-3 pb-1 text-p-xs font-medium uppercase tracking-wide text-ink-gray-5">
					{{ group }}
				</div>
				<button
					v-for="t in items"
					:key="t.key"
					class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-p-sm transition-colors"
					:class="
						activeKey === t.key
							? 'bg-surface-gray-3 font-medium text-ink-gray-9'
							: 'text-ink-gray-7 hover:bg-surface-gray-2'
					"
					@click="router.push(`/documents/${t.key}`)"
				>
					<component
						:is="resolveIcon(t.icon)"
						v-if="resolveIcon(t.icon)"
						class="h-4 w-4 shrink-0 text-ink-gray-5"
						aria-hidden="true"
					/>
					<span class="truncate">{{ t.label }}</span>
				</button>
			</div>
		</aside>

		<div class="flex min-w-0 flex-1 flex-col overflow-hidden">
			<PageHeader :title="activeType?.label || 'Documents'" :subtitle="subtitle">
				<!-- Only for types that declare a form and that this user may
				     create; the server decides both. On the title line rather than
				     among the filters, so the one control that raises a document is
				     not a mis-tap away from a period picker. -->
				<template v-if="activeType?.creatable" #primary>
					<Button
						theme="gray"
						variant="solid"
						:icon-left="LucidePlus"
						:label="`New ${activeType.label}`"
						@click="newOpen = true"
					/>
				</template>

				<template #actions>
					<!-- No button, and the reason why. A missing control with no
					     explanation reads as something broken. -->
					<span
						v-else-if="activeType?.create_hint"
						class="max-w-[320px] text-p-xs text-ink-gray-5"
						:title="activeType.create_hint"
					>
						{{ activeType.create_hint }}
					</span>
					<div v-if="!inModule" class="w-[190px] lg:hidden">
						<FormControl
							type="select"
							:model-value="activeKey"
							:options="types.map((t) => ({ label: t.label, value: t.key }))"
							@update:model-value="router.push(`/documents/${$event}`)"
						/>
					</div>
					<div v-if="tab === 'list'" class="w-[160px]">
						<FormControl type="select" v-model="status" :options="statusOptions" />
					</div>
					<div v-if="tab === 'list' && activeType?.has_party" class="w-[160px]">
						<FormControl
							v-model="party"
							type="text"
							:placeholder="`${activeType.party_label}…`"
						/>
					</div>
					<div v-if="tab === 'list'" class="w-[160px]">
						<FormControl v-model="search" type="text" placeholder="Search…" />
					</div>
					<div v-if="tab !== 'reports'" class="w-[150px]">
						<FormControl type="select" v-model="days" :options="PERIODS" />
					</div>
					<Button
						v-if="tab !== 'reports'"
						variant="subtle"
						:icon-left="LucideRefreshCw"
						:loading="loading"
						@click="load"
					/>
				</template>
			</PageHeader>

			<div class="shrink-0 px-4 pt-3">
				<TabButtons v-model="tab" :buttons="TABS" />
			</div>

			<!-- List -->
			<template v-if="tab === 'list'">
				<StatTiles
					:stats="[
						{ key: 'count', label: 'On screen', value: data.totals.count, type: 'number', icon: 'file' },
						{ key: 'value', label: 'Value', value: data.totals.amount, type: 'currency', icon: 'money' },
						{
							key: 'outstanding',
							label: 'Outstanding',
							value: data.totals.outstanding,
							type: 'currency',
							icon: 'hourglass',
							tone: data.totals.outstanding > 0 ? 'warn' : 'good',
						},
					]"
				/>

				<DataTable
					:columns="columns"
					:rows="data.rows"
					row-key="name"
					:loading="loading"
					empty-text="No documents match these filters."
				>
					<template #cell-name="{ row }">
						<button
							class="text-left font-medium text-ink-gray-8 underline decoration-outline-gray-3 underline-offset-2 hover:decoration-ink-gray-8"
							@click="openRow(row)"
						>
							{{ row.name }}
						</button>
					</template>
					<template #cell-is_pos="{ value }">
						<Badge :theme="value ? 'green' : 'gray'" variant="subtle" :label="value ? 'Till' : 'Invoice'" />
					</template>
					<template #cell-_actions="{ row }">
						<div class="flex justify-end">
							<!-- Right-aligned: the menu column is the last one, and a
							     left-aligned popover would run off the table. -->
							<Dropdown :options="rowActions(row)" placement="right">
								<Button
									variant="ghost"
									:icon-left="LucideMore"
									:loading="busyRow === row.name"
									:aria-label="`Actions for ${row.name}`"
								/>
							</Dropdown>
						</div>
					</template>
				</DataTable>

				<div
					v-if="data.rows.length < data.total"
					class="flex shrink-0 items-center justify-end border-t border-outline-gray-2 bg-surface-white px-4 py-2"
				>
					<Button
						variant="subtle"
						:loading="loading"
						:disabled="limit >= 500"
						:label="
							limit >= 500
								? `Showing the first 500 of ${data.total} — narrow the filters`
								: `Show more (${data.total - data.rows.length} left)`
						"
						@click="limit = Math.min(limit + 100, 500)"
					/>
				</div>
			</template>

			<!-- Insights -->
			<template v-else-if="tab === 'insights'">
				<div class="min-h-0 flex-1 overflow-auto">
					<StatTiles :stats="stats" dense />
					<div class="grid gap-3 px-4 pb-4 lg:grid-cols-2">
						<section class="overflow-hidden rounded-lg border border-outline-gray-2 bg-surface-white">
							<h2 class="border-b border-outline-gray-2 px-3 py-2 text-p-sm font-semibold text-ink-gray-8">
								By status
							</h2>
							<DataTable
								:columns="insights?.by_status.columns || []"
								:rows="insights?.by_status.rows || []"
								empty-text="Nothing in this period."
							/>
						</section>
						<section
							v-if="insights?.ageing.columns.length"
							class="overflow-hidden rounded-lg border border-outline-gray-2 bg-surface-white"
						>
							<h2 class="border-b border-outline-gray-2 px-3 py-2 text-p-sm font-semibold text-ink-gray-8">
								Ageing
								<span class="font-normal text-ink-gray-5">· everything still owed, not just this period</span>
							</h2>
							<DataTable
								:columns="insights.ageing.columns"
								:rows="insights.ageing.rows"
								empty-text="Nothing outstanding."
							/>
						</section>
					</div>
				</div>
			</template>

			<!-- Reports: the reports screen itself, narrowed to this document type. -->
			<Reports v-else embedded :only="activeType?.reports || []" />
		</div>

		<DocumentFormSheet
			v-model:open="newOpen"
			:doc-key="activeKey"
			@created="load"
			@notify="notify($event.message, $event.tone)"
		/>

		<DocumentModal
			v-model:open="open"
			:doc-key="activeKey"
			:name="selected"
			@changed="load"
			@notify="notify($event.message, $event.tone)"
		/>

		<Transition
			enter-active-class="transition-all duration-200"
			leave-active-class="transition-all duration-200"
			enter-from-class="opacity-0 translate-y-2"
			leave-to-class="opacity-0"
		>
			<div
				v-if="toast"
				class="pointer-events-none pos-toast absolute bottom-5 left-1/2 -translate-x-1/2 rounded-lg px-4 py-2.5 text-p-sm font-medium text-ink-white shadow-lg"
				:class="toast.tone === 'bad' ? 'bg-surface-red-5' : 'bg-surface-green-3'"
			>
				{{ toast.message }}
			</div>
		</Transition>
	</div>
</template>
