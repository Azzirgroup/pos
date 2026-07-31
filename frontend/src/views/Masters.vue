<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button, FormControl } from 'frappe-ui'
import { listMasterRecords, listMasterTypes } from '@/data/api'
import PageHeader from '@/components/PageHeader.vue'
import DataTable from '@/components/DataTable.vue'
import ShareSheet from '@/components/ShareSheet.vue'
import { useRowActions } from '@/composables/useRowActions'
import MasterSheet from '@/components/MasterSheet.vue'
import { resolveIcon } from '@/utils/icons'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideSend from '~icons/lucide/send'
import LucidePlus from '~icons/lucide/plus'

/**
 * Where the records a shop maintains itself live: customers, suppliers, items,
 * warehouses, accounts.
 *
 * Deliberately a list *and* a create button rather than a create button alone.
 * A form on its own makes people add duplicates, because nobody can see that
 * the customer they are about to type in is already on file.
 *
 * Built from `master.list_types`, so the same registry that describes the form
 * describes this screen — a sixth type appears here with no change to this file.
 */
const route = useRoute()
const router = useRouter()

const types = ref([])
const data = ref({ columns: [], rows: [], total: 0 })
const search = ref('')
const loading = ref(false)
const newOpen = ref(false)
const editName = ref(null)

function edit(name) {
	editName.value = name
	newOpen.value = true
}

// Cleared on close so the next "New" is a create, not another edit.
watch(newOpen, (open) => {
	if (!open) editName.value = null
})

/**
 * Whether this is one record type rather than the Records index.
 *
 * Set by the route, so the same component serves both: `/masters` browses every
 * type and needs the picker, while a module tab that already chose one does
 * not. Guessing from the presence of a `:key` would be wrong — somebody
 * arriving at `/masters/item` from the index still wants the way back.
 */
const focused = computed(() => Boolean(route.meta?.focusedMaster))

const activeKey = computed(
	() => route.meta?.masterKey || route.params.key || types.value[0]?.key || null,
)
const activeType = computed(() => types.value.find((t) => t.key === activeKey.value) || null)

/**
 * Master records are documents, but not ones anybody wants as a PDF — a
 * supplier's contact details are read in the message, not opened as an
 * attachment. So this shares text, and the columns follow the type on screen.
 */
const { shareOpen, sharePayload, shareList, actionsFor } = useRowActions({
	columns: () => data.value.columns || [],
	title: (row) => row.name,
})

const subtitle = computed(() => {
	if (!data.value.total) return 'Nothing here yet'
	const shown = data.value.rows.length
	return `showing ${shown} of ${data.value.total}`
})

onMounted(async () => {
	types.value = await listMasterTypes().catch(() => [])
	if (!route.params.key && types.value.length) {
		router.replace(`/masters/${types.value[0].key}`)
		return
	}
	load()
})

watch(activeKey, () => {
	search.value = ''
	load()
})

let timer = null
watch(search, () => {
	clearTimeout(timer)
	timer = setTimeout(load, 250)
})

async function load() {
	if (!activeKey.value) return
	loading.value = true
	try {
		data.value = await listMasterRecords({ key: activeKey.value, search: search.value })
	} catch (e) {
		notify(e.message || 'Could not load these records', 'bad')
		data.value = { columns: [], rows: [], total: 0 }
	} finally {
		loading.value = false
	}
}

const toast = ref(null)
let toastTimer = null
function notify(message, tone = 'good') {
	toast.value = { message, tone }
	clearTimeout(toastTimer)
	toastTimer = setTimeout(() => (toast.value = null), 2800)
}
</script>

<template>
	<div class="flex min-h-0 flex-1 overflow-hidden">
		<div class="flex min-w-0 flex-1 flex-col overflow-hidden">
			<PageHeader :title="activeType?.label || 'Records'" :subtitle="subtitle">
				<!-- Creating sits on the title line, away from the controls that
				     only narrow what is already listed. -->
				<template v-if="data.can_create !== false" #primary>
					<Button
						theme="gray"
						variant="solid"
						:icon-left="LucidePlus"
						:label="`New ${activeType?.label || 'record'}`"
						@click="newOpen = true"
					/>
				</template>

				<template #actions>
					<div class="w-[190px]">
						<FormControl v-model="search" type="text" placeholder="Search…" />
					</div>
					<Button
						variant="subtle"
						:icon-left="LucideSend"
						:disabled="!data.rows.length"
						label="Share"
						@click="shareList(data.rows, activeType?.label || 'Records')"
					/>
					<Button
						variant="subtle"
						:icon-left="LucideRefreshCw"
						:loading="loading"
						@click="load"
					/>
				</template>
			</PageHeader>

			<!-- The type picker, horizontal. It was a 200px rail; a row of chips
			     costs one line, and on a route that already chose its type there
			     is nothing to pick, so it is absent entirely. -->
			<div
				v-if="!focused && types.length > 1"
				class="flex shrink-0 flex-wrap items-center gap-1 border-b border-outline-gray-2 bg-surface-white px-4 py-2"
			>
				<button
					v-for="t in types"
					:key="t.key"
					class="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-p-sm transition-colors"
					:class="
						activeKey === t.key
							? 'bg-surface-gray-3 font-medium text-ink-gray-9'
							: 'text-ink-gray-6 hover:bg-surface-gray-2 hover:text-ink-gray-8'
					"
					@click="router.push(`/masters/${t.key}`)"
				>
					<component
						:is="resolveIcon(t.icon)"
						v-if="resolveIcon(t.icon)"
						class="h-4 w-4 shrink-0"
						aria-hidden="true"
					/>
					{{ t.label }}
				</button>
			</div>

			<p v-if="activeType?.hint" class="shrink-0 bg-surface-amber-1 px-4 py-2 text-p-xs text-ink-amber-3">
				{{ activeType.hint }}
			</p>

			<DataTable
				:columns="data.columns"
				:rows="data.rows"
				row-key="name"
				:loading="loading"
				:actions="actionsFor"
				empty-text="Nothing here yet. Use the button above to add the first one."
			>
				<!-- The ID opens the record for editing: a phone number typed wrong
				     is corrected where it was entered, not by hunting it down in the
				     desk. -->
				<template #cell-name="{ row }">
					<button
						class="text-left font-medium text-ink-gray-8 underline decoration-outline-gray-3 underline-offset-2 hover:decoration-ink-gray-8"
						@click="edit(row.name)"
					>
						{{ row.name }}
					</button>
				</template>
			</DataTable>
		</div>

		<MasterSheet
			v-model:open="newOpen"
			:initial-key="activeKey"
			:edit-name="editName"
			@created="load"
			@notify="notify($event.message, $event.tone)"
		/>

		<ShareSheet v-model="shareOpen" :payload="sharePayload" />

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
