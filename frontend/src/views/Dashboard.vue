<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { Button, FormControl, Spinner, TabButtons } from 'frappe-ui'
import { getDashboard, getDashboardFilters, getDashboardTab } from '@/data/api'
import PageHeader from '@/components/PageHeader.vue'
import StatTiles from '@/components/StatTiles.vue'
import DataTable from '@/components/DataTable.vue'
import AttentionList from '@/components/AttentionList.vue'
import ChartCard from '@/components/charts/ChartCard.vue'
import TrendChart from '@/components/charts/TrendChart.vue'
import BarList from '@/components/charts/BarList.vue'
import DonutChart from '@/components/charts/DonutChart.vue'
import PairedBars from '@/components/charts/PairedBars.vue'
import LucideRefreshCw from '~icons/lucide/refresh-cw'

/**
 * The first screen of the day.
 *
 * One period control at the top scopes everything below it — no per-chart
 * filters, so every number on the page is answering the same question about
 * the same window. Refreshing holds the previous render at reduced opacity
 * rather than collapsing to skeletons: the figures barely move between loads,
 * and a page that flashes empty reads as broken.
 */
const data = ref(null)
const days = ref(30)
const loading = ref(false)

const PERIODS = [
	{ label: 'Last 7 days', value: 7 },
	{ label: 'Last 30 days', value: 30 },
	{ label: 'Last 90 days', value: 90 },
	{ label: 'Last year', value: 365 },
]

/**
 * Overview is charts and needs its own layout; the other five are all
 * {stats, sections} and share one renderer. Adding a sixth department is a tab
 * entry and an endpoint, not another screen.
 */
const TABS = [
	{ label: 'Overview', value: 'overview' },
	{ label: 'Sales', value: 'sales' },
	{ label: 'Branches', value: 'branches' },
	{ label: 'Warehouses', value: 'warehouses' },
	{ label: 'Procurement', value: 'procurement' },
	{ label: 'Accounts', value: 'accounts' },
]

const tab = ref('overview')
const tabData = ref(null)

// Select drops options whose value is falsy, so "all" needs a real token.
const ALL = '__all__'
const branch = ref(ALL)
const warehouse = ref(ALL)
const filterOptions = ref({ branches: [], warehouses: [] })

const usesBranch = computed(() => tab.value === 'sales')
const usesWarehouse = computed(() => tab.value === 'warehouses')

const branchOptions = computed(() => [
	{ label: 'All branches', value: ALL },
	...filterOptions.value.branches,
])
const warehouseOptions = computed(() => [
	{ label: 'All warehouses', value: ALL },
	...filterOptions.value.warehouses,
])

onMounted(async () => {
	filterOptions.value = await getDashboardFilters().catch(() => ({ branches: [], warehouses: [] }))
	load()
})

watch([days, tab, branch, warehouse], load)

async function load() {
	loading.value = true
	try {
		if (tab.value === 'overview') {
			data.value = await getDashboard({ days: days.value })
		} else {
			tabData.value = await getDashboardTab({
				tab: tab.value,
				days: days.value,
				branch: usesBranch.value && branch.value !== ALL ? branch.value : null,
				warehouse: usesWarehouse.value && warehouse.value !== ALL ? warehouse.value : null,
			})
		}
	} catch (e) {
		console.error('[dashboard]', e)
		if (tab.value !== 'overview') tabData.value = null
	} finally {
		loading.value = false
	}
}

const period = computed(() => data.value?.period)

/**
 * The window in words, not in dates.
 *
 * It used to spell out both ranges — "2026-06-30 to 2026-07-29 · compared with
 * 2026-05-31 to 2026-06-29" — which is four dates to read before learning
 * anything, and the period control directly above already says which window is
 * selected. Every delta on the page is against the preceding window of equal
 * length, so that is stated once, in words.
 */
const subtitle = computed(() => {
	if (!period.value) return 'How the shop is doing'
	const days = period.value.days
	const label = PERIODS.find((p) => p.value === days)?.label || `Last ${days} days`
	const against = days === 365 ? 'the year before' : `the ${days} days before`
	return `${label}, against ${against}`
})

/* ---------- table twins ---------- */

const trendTable = computed(() => ({
	columns: [
		{ label: 'Date', key: 'day', type: 'text' },
		{ label: 'Sales', key: 'invoices', type: 'number' },
		{ label: 'Revenue', key: 'revenue', type: 'currency' },
	],
	rows: data.value?.trend || [],
}))

const paymentTable = computed(() => ({
	columns: [
		{ label: 'Mode', key: 'mode', type: 'text' },
		{ label: 'Share %', key: 'share', type: 'number' },
		{ label: 'Collected', key: 'amount', type: 'currency' },
	],
	rows: data.value?.payment_mix || [],
}))

const itemsTable = computed(() => ({
	columns: [
		{ label: 'Item', key: 'item_name', type: 'text' },
		{ label: 'Code', key: 'item_code', type: 'text' },
		{ label: 'Qty sold', key: 'qty', type: 'number' },
		{ label: 'Revenue', key: 'revenue', type: 'currency' },
	],
	rows: data.value?.top_items || [],
}))

const itemBars = computed(() =>
	(data.value?.top_items || []).map((i) => ({
		label: i.item_name || i.item_code,
		hint: `${Number(i.qty || 0).toLocaleString()} sold`,
		value: i.revenue,
	})),
)

/**
 * Which sections are showing figures instead of their chart.
 *
 * Per section rather than one page-wide switch: a manager reading a bar chart
 * of spend still wants the exact receivable, and a single toggle would make
 * them give up the one to see the other.
 */
const asTable = ref({})

function toggleTable(key) {
	asTable.value = { ...asTable.value, [key]: !asTable.value[key] }
}

// Cleared when the tab changes: section keys repeat across tabs, and a toggle
// left on would show the wrong section as a table.
watch(tab, () => (asTable.value = {}))

/**
 * A section's rows in the shape BarList wants.
 *
 * The server names which column is the label and which is the magnitude; this
 * only reshapes. The hint is the secondary figure — "12 sales" under a revenue
 * bar — which is what stops a bar chart being less informative than the table
 * it replaced.
 */
function barRows(section) {
	const c = section.chart
	const hintCol = c.hint ? section.columns.find((col) => col.key === c.hint) : null
	return (section.rows || []).map((row) => ({
		label: row[c.label] ?? '—',
		value: Number(row[c.value]) || 0,
		hint: hintCol
			? `${Number(row[c.hint] ?? 0).toLocaleString()} ${hintCol.label.toLowerCase()}`
			: null,
	}))
}

/** Two measures per row, for the relationship charts. */
function pairedRows(section) {
	const c = section.chart
	return (section.rows || []).map((row) => ({
		label: row[c.label] ?? '—',
		a: Number(row[c.a]) || 0,
		b: Number(row[c.b]) || 0,
	}))
}

/** Oldest first: a line over time drawn newest-first runs backwards. */
function trendPoints(section) {
	const c = section.chart
	return [...(section.rows || [])]
		.reverse()
		.map((row) => ({ ...row, day: row[c.label] }))
}

/** Payment mix in the shape the ring wants: a label and a magnitude. */
const paymentSlices = computed(() =>
	(data.value?.payment_mix || []).map((p) => ({ label: p.mode, value: p.amount })),
)

const collected = computed(() =>
	(data.value?.payment_mix || []).reduce((sum, p) => sum + Number(p.amount || 0), 0),
)

/** By key, not by position — the tile order is the server's to change. */
const stat = (key) => data.value?.stats.find((s) => s.key === key)

/** Only the lists that have something in them; empty cards are noise. */
const attention = computed(() => {
	const a = data.value?.attention
	if (!a) return []
	return [
		{
			key: 'below_reorder',
			title: 'Below reorder level',
			subtitle: 'What to buy next',
			...a.below_reorder,
		},
		{ key: 'overdue', title: 'Overdue invoices', subtitle: 'Oldest first', ...a.overdue },
		{
			key: 'slow_moving',
			title: 'Slow moving',
			subtitle: 'Has not sold this period',
			...a.slow_moving,
		},
	].filter((section) => section?.rows?.length)
})
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col overflow-hidden">
		<PageHeader title="Dashboard" :subtitle="subtitle">
			<template #actions>
				<!-- One filter row above everything it scopes: every figure on the
				     tab answers the same question about the same slice. -->
				<div v-if="usesBranch" class="w-[180px]">
					<FormControl type="select" v-model="branch" :options="branchOptions" />
				</div>
				<div v-if="usesWarehouse" class="w-[190px]">
					<FormControl type="select" v-model="warehouse" :options="warehouseOptions" />
				</div>
				<div class="w-[160px]">
					<FormControl type="select" v-model="days" :options="PERIODS" />
				</div>
				<Button variant="subtle" :icon-left="LucideRefreshCw" :loading="loading" @click="load" />
			</template>
		</PageHeader>

		<div class="shrink-0 overflow-x-auto px-4 pt-3">
			<TabButtons v-model="tab" :buttons="TABS" />
		</div>

		<!-- The five department tabs: same shape, one renderer. -->
		<div
			v-if="tab !== 'overview'"
			class="min-h-0 flex-1 overflow-auto pb-4 transition-opacity"
			:class="loading ? 'opacity-60' : ''"
		>
			<div v-if="!tabData && loading" class="grid h-40 place-items-center">
				<Spinner class="h-5 w-5" />
			</div>
			<template v-else-if="tabData">
				<StatTiles :stats="tabData.stats" dense />
				<!-- `items-start` stops the grid stretching a three-row card to match
				     a twelve-row one beside it. Each card is as tall as what it
				     holds, and the page is the only thing that scrolls. -->
				<div class="grid items-start gap-3 px-4 lg:grid-cols-2">
					<section
						v-for="section in tabData.sections"
						:key="section.key"
						class="flex min-w-0 flex-col overflow-hidden rounded-lg border border-outline-gray-2 bg-surface-white"
					>
						<header class="border-b border-outline-gray-2 px-3 py-2">
							<h2 class="text-p-sm font-semibold text-ink-gray-8">{{ section.title }}</h2>
							<p v-if="section.subtitle" class="truncate text-p-xs text-ink-gray-5">
								{{ section.subtitle }}
							</p>
						</header>
						<!-- Drawn where the server named a magnitude column, listed
						     otherwise. A bar is faster to compare down than a column
						     of figures, and the exact numbers stay one tap away. The
						     sections with no chart are the ones where every row
						     matters equally and there is nothing to rank. -->
						<template v-if="section.chart && section.rows?.length">
							<div class="flex justify-end px-3 pt-2">
								<button
									class="text-p-xs font-medium text-ink-gray-5 transition-colors hover:text-ink-gray-8"
									@click="toggleTable(section.key)"
								>
									{{ asTable[section.key] ? 'Show chart' : 'Show figures' }}
								</button>
							</div>
							<AttentionList
								v-if="asTable[section.key]"
								:columns="section.columns"
								:rows="section.rows"
							/>
							<BarList
								v-else-if="section.chart.kind === 'bar'"
								class="px-3 pb-3 pt-1"
								:rows="barRows(section)"
								:type="section.chart.type || 'currency'"
							/>
							<DonutChart
								v-else-if="section.chart.kind === 'donut'"
								class="px-3 pb-3 pt-2"
								:rows="barRows(section)"
								:type="section.chart.type || 'currency'"
							/>
							<PairedBars
								v-else-if="section.chart.kind === 'paired'"
								class="px-3 pb-3 pt-2"
								:rows="pairedRows(section)"
								:a-label="section.chart.a_label"
								:b-label="section.chart.b_label"
								:type="section.chart.type || 'number'"
							/>
							<TrendChart
								v-else
								class="px-3 pb-3 pt-1"
								:points="trendPoints(section)"
								:value-key="section.chart.value"
							/>
						</template>
						<AttentionList
							v-else
							:columns="section.columns"
							:rows="section.rows"
							empty-text="Nothing in this period."
						/>
					</section>
				</div>
			</template>
			<div v-else class="grid h-40 place-items-center px-6 text-center">
				<p class="text-p-sm text-ink-gray-5">Could not load this tab.</p>
			</div>
		</div>

		<div v-else-if="!data && loading" class="grid flex-1 place-items-center">
			<Spinner class="h-5 w-5" />
		</div>

		<div
			v-else-if="data"
			class="min-h-0 flex-1 overflow-auto pb-4 transition-opacity"
			:class="loading ? 'opacity-60' : ''"
		>
			<StatTiles :stats="data.stats" dense />

			<div class="grid gap-3 px-4 lg:grid-cols-3">
				<ChartCard
					class="lg:col-span-2"
					title="Revenue"
					:subtitle="`Daily, ${period.days} days`"
					:columns="trendTable.columns"
					:rows="trendTable.rows"
					empty-text="No sales in this period."
				>
					<TrendChart :points="data.trend" value-key="revenue" />
				</ChartCard>

				<ChartCard
					title="Payments collected"
					subtitle="Money in the drawer, credit excluded"
					:columns="paymentTable.columns"
					:rows="paymentTable.rows"
					empty-text="Nothing collected in this period."
				>
					<!-- A ring rather than a stacked bar. The question here is "how
					     did the money come in" — a composition — and a ring says that
					     directly, where a single stacked bar makes small tenders into
					     slivers too thin to label or compare. The legend carries the
					     figures either way, so nothing depends on reading a colour. -->
					<DonutChart :rows="paymentSlices" type="currency" />
					<!-- Spelled out because the gap between the two is the thing worth
					     noticing, and a chart of collections alone does not show it. -->
					<p class="mt-3 border-t border-outline-gray-2 pt-2 text-p-xs text-ink-gray-5">
						Collected
						<span class="tabular font-medium text-ink-gray-8">{{ collected.toLocaleString() }}</span>
						of
						<span class="tabular font-medium text-ink-gray-8">
							{{ Number(stat('revenue')?.value || 0).toLocaleString() }}
						</span>
						billed — the rest is on credit.
					</p>
				</ChartCard>

				<ChartCard
					class="lg:col-span-3"
					title="Best sellers"
					subtitle="By revenue, net of tax"
					:columns="itemsTable.columns"
					:rows="itemsTable.rows"
					empty-text="Nothing sold in this period."
				>
					<BarList :rows="itemBars" type="currency" />
				</ChartCard>
			</div>

			<!-- Columns follow the count, so the row always fills the width. At a
			     fixed three columns a period with two attention lists left a third
			     of the page empty and the two cards needlessly narrow — which is
			     what forced their contents to wrap. -->
			<div
				v-if="attention.length"
				class="mt-3 grid items-start gap-3 px-4"
				:class="
					attention.length === 1
						? 'grid-cols-1'
						: attention.length === 2
							? 'lg:grid-cols-2'
							: 'lg:grid-cols-3'
				"
			>
				<section
					v-for="section in attention"
					:key="section.key"
					class="flex min-w-0 flex-col overflow-hidden rounded-lg border border-outline-gray-2 bg-surface-white"
				>
					<header class="border-b border-outline-gray-2 px-3 py-2">
						<h2 class="text-p-sm font-semibold text-ink-gray-8">{{ section.title }}</h2>
						<p class="truncate text-p-xs text-ink-gray-5">{{ section.subtitle }}</p>
					</header>
					<!-- A list, not a table: these sit three across, and five columns in
					     a third of the page scrolled sideways — which hid the figure the
					     shortlist exists to show. -->
					<AttentionList :columns="section.columns" :rows="section.rows" />
				</section>
			</div>

			<div v-if="data.tills.count" class="mt-3 px-4">
				<section class="overflow-hidden rounded-lg border border-outline-gray-2 bg-surface-white">
					<header class="border-b border-outline-gray-2 px-3 py-2">
						<h2 class="text-p-sm font-semibold text-ink-gray-8">
							{{ data.tills.count }} till{{ data.tills.count === 1 ? '' : 's' }} open now
						</h2>
					</header>
					<DataTable
						:columns="[
							{ label: 'Opening', key: 'name', type: 'text' },
							{ label: 'Cashier', key: 'user', type: 'text' },
							{ label: 'Till', key: 'pos_profile', type: 'text' },
							{ label: 'Since', key: 'period_start_date', type: 'text' },
						]"
						:rows="data.tills.rows"
						:scroll="false"
					/>
				</section>
			</div>
		</div>
	</div>
</template>
