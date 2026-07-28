<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { Button, FormControl, Spinner, TabButtons } from 'frappe-ui'
import { getDashboard, getDashboardFilters, getDashboardTab } from '@/data/api'
import PageHeader from '@/components/PageHeader.vue'
import StatTiles from '@/components/StatTiles.vue'
import DataTable from '@/components/DataTable.vue'
import ChartCard from '@/components/charts/ChartCard.vue'
import TrendChart from '@/components/charts/TrendChart.vue'
import BarList from '@/components/charts/BarList.vue'
import ShareBar from '@/components/charts/ShareBar.vue'
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
const previous = computed(() => data.value?.previous)

const subtitle = computed(() => {
	if (!period.value) return 'How the shop is doing'
	return `${period.value.from} to ${period.value.to} · compared with ${previous.value.from} to ${previous.value.to}`
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
			key: 'negative_stock',
			title: 'Negative stock',
			subtitle: 'Sold but never received — a ledger problem, not a shelf one',
			...a.negative_stock,
		},
	].filter((section) => section.rows?.length)
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
				<div class="grid gap-3 px-4 lg:grid-cols-2">
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
						<div class="max-h-[320px] overflow-auto">
							<DataTable
								:columns="section.columns"
								:rows="section.rows"
								empty-text="Nothing in this period."
							/>
						</div>
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
					<ShareBar :segments="data.payment_mix" />
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

			<div v-if="attention.length" class="mt-3 grid gap-3 px-4 lg:grid-cols-3">
				<section
					v-for="section in attention"
					:key="section.key"
					class="flex min-w-0 flex-col overflow-hidden rounded-lg border border-outline-gray-2 bg-surface-white"
				>
					<header class="border-b border-outline-gray-2 px-3 py-2">
						<h2 class="text-p-sm font-semibold text-ink-gray-8">{{ section.title }}</h2>
						<p class="truncate text-p-xs text-ink-gray-5">{{ section.subtitle }}</p>
					</header>
					<div class="max-h-[260px] overflow-auto">
						<DataTable :columns="section.columns" :rows="section.rows" />
					</div>
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
					/>
				</section>
			</div>
		</div>
	</div>
</template>
