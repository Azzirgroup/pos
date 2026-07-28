<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Button, FormControl } from 'frappe-ui'
import { searchCustomers } from '@/data/api'
import PageHeader from '@/components/PageHeader.vue'
import StatTiles from '@/components/StatTiles.vue'
import DataTable from '@/components/DataTable.vue'
import LucideRefreshCw from '~icons/lucide/refresh-cw'

const rows = ref([])
const search = ref('')
const loading = ref(false)

const COLUMNS = [
	{ label: 'Customer', key: 'customer_name', type: 'text' },
	{ label: 'Phone', key: 'mobile_no', type: 'text' },
	{ label: 'Owes', key: 'outstanding', type: 'currency' },
]

const stats = computed(() => {
	const owing = rows.value.filter((r) => Number(r.outstanding) > 0)
	return [
		{ label: 'Customers', value: rows.value.length, type: 'number' },
		{
			label: 'Owing money',
			value: owing.length,
			type: 'number',
			tone: owing.length ? 'warn' : 'good',
		},
		{
			label: 'Total owed',
			value: owing.reduce((s, r) => s + Number(r.outstanding || 0), 0),
			type: 'currency',
			tone: owing.length ? 'warn' : 'good',
		},
	]
})

onMounted(load)

let timer = null
watch(search, () => {
	clearTimeout(timer)
	timer = setTimeout(load, 250)
})

async function load() {
	loading.value = true
	try {
		rows.value = (await searchCustomers(search.value)) || []
	} catch (e) {
		console.error('[customers]', e)
		rows.value = []
	} finally {
		loading.value = false
	}
}
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col overflow-hidden">
		<PageHeader title="Customers" subtitle="Who buys, and who still owes">
			<template #actions>
				<div class="w-[220px]">
					<FormControl v-model="search" type="text" placeholder="Search name or phone…" />
				</div>
				<Button variant="subtle" :icon-left="LucideRefreshCw" :loading="loading" @click="load" />
			</template>
		</PageHeader>

		<StatTiles :stats="stats" />
		<DataTable
			:columns="COLUMNS"
			:rows="rows"
			row-key="name"
			:loading="loading"
			empty-text="No customers yet. They are created at the till on a credit sale."
		/>
	</div>
</template>
