<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Button, FormControl, TabButtons } from 'frappe-ui'
import { listMasterRecords } from '@/data/api'
import PageHeader from '@/components/PageHeader.vue'
import DataTable from '@/components/DataTable.vue'
import ShareSheet from '@/components/ShareSheet.vue'
import MasterSheet from '@/components/MasterSheet.vue'
import Reports from '@/views/Reports.vue'
import { useRowActions } from '@/composables/useRowActions'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucidePlus from '~icons/lucide/plus'
import LucideSend from '~icons/lucide/send'

/**
 * Suppliers, and the money side of them.
 *
 * They were reachable only through the generic records screen, which put a
 * column of every master type beside them — a list of nouns costing 200px on a
 * page about one of them. Here the space goes to the supplier's own question
 * instead: what do we owe, and what have we been buying.
 *
 * The accounting tabs are the existing reports embedded rather than
 * reimplemented, so a figure here and the same figure under Reports cannot
 * drift apart.
 */
const TABS = [
	{ label: 'Suppliers', value: 'list' },
	{ label: 'Balances owed', value: 'payables' },
	{ label: 'Spend', value: 'spend' },
]
const tab = ref('list')

const data = ref({ columns: [], rows: [], total: 0 })
const search = ref('')
const loading = ref(false)
const newOpen = ref(false)
const editName = ref(null)

const rows = computed(() => data.value.rows || [])

const { shareOpen, sharePayload, shareList, actionsFor } = useRowActions({
	columns: () => data.value.columns || [],
	title: (row) => row.name,
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
		data.value = await listMasterRecords({ key: 'supplier', search: search.value || null })
	} catch (e) {
		console.error('[suppliers]', e)
		data.value = { columns: [], rows: [], total: 0 }
	} finally {
		loading.value = false
	}
}

function edit(name) {
	editName.value = name
	newOpen.value = true
}

function createNew() {
	editName.value = null
	newOpen.value = true
}
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col overflow-hidden">
		<PageHeader title="Suppliers" subtitle="Who you buy from, and what you owe them">
			<template #actions>
				<div v-if="tab === 'list'" class="w-[190px]">
					<FormControl v-model="search" type="text" placeholder="Search suppliers…" />
				</div>
				<Button
					v-if="tab === 'list'"
					variant="subtle"
					:icon-left="LucideSend"
					:disabled="!rows.length"
					label="Share"
					@click="shareList(rows, 'Suppliers')"
				/>
				<Button
					v-if="tab === 'list'"
					variant="subtle"
					:icon-left="LucideRefreshCw"
					:loading="loading"
					@click="load"
				/>
			</template>

			<!-- On the title line, away from search and refresh: the control a
			     mis-tap reaches should not be the one that opens a form. -->
			<template v-if="tab === 'list'" #primary>
				<Button
					theme="gray"
					variant="solid"
					:icon-left="LucidePlus"
					label="New supplier"
					@click="createNew"
				/>
			</template>
		</PageHeader>

		<div class="shrink-0 overflow-x-auto px-4 pt-3">
			<TabButtons v-model="tab" :buttons="TABS" />
		</div>

		<DataTable
			v-if="tab === 'list'"
			:columns="data.columns"
			:rows="rows"
			row-key="name"
			:loading="loading"
			:actions="actionsFor"
			empty-text="No suppliers yet. Add the shops and wholesalers you buy from."
		>
			<!-- The name opens the record: a phone number typed wrong is corrected
			     where it is read, not by hunting it down in the desk. -->
			<template #cell-name="{ row }">
				<button
					class="text-left font-medium text-ink-gray-8 underline decoration-outline-gray-3 underline-offset-2 hover:decoration-ink-gray-8"
					@click="edit(row.name)"
				>
					{{ row.name }}
				</button>
			</template>
		</DataTable>

		<!-- The existing reports, embedded. Reimplementing either would give the
		     shop two places to read the same number from. -->
		<Reports v-else-if="tab === 'payables'" embedded report="payables" />
		<Reports v-else embedded report="top_items" />

		<MasterSheet
			v-model:open="newOpen"
			initial-key="supplier"
			:edit-name="editName"
			@created="load"
		/>
		<ShareSheet v-model="shareOpen" :payload="sharePayload" />
	</div>
</template>
