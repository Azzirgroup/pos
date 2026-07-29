<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Button, FormControl, Badge, Spinner, Dialog } from 'frappe-ui'
import { getReorderItems, getItemReorder, saveReorderRules } from '@/data/api'
import PageHeader from '@/components/PageHeader.vue'
import ShareSheet from '@/components/ShareSheet.vue'
import { useRowActions } from '@/composables/useRowActions'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideSettings from '~icons/lucide/settings-2'
import LucideSave from '~icons/lucide/save'
import LucideSend from '~icons/lucide/send'

const items = ref([])
const search = ref('')
const onlyUnconfigured = ref(false)
const loading = ref(false)
const toast = ref(null)

/* ---------- per-item modal ---------- */

const open = ref(false)
const detail = ref(null)
const detailLoading = ref(false)
const saving = ref(false)
const parent = ref(null)
/** warehouse -> { reorder_level, reorder_qty, material_request_type } */
const edits = ref({})

/**
 * This screen keeps its own table, so it does not get the generic actions
 * column — but the list itself is a buying list, which is the single most
 * useful thing in the app to send to somebody. Shared as the items that are
 * actually below their level, not everything on screen: a colleague asked
 * "what do we need?" wants the answer, not the register.
 */
const REORDER_COLUMNS = [
	{ label: 'Item', key: 'item_name', type: 'text' },
	{ label: 'Code', key: 'item_code', type: 'text' },
	{ label: 'In stock', key: 'total_stock', type: 'number' },
	{ label: 'Locations below level', key: 'below_count', type: 'number' },
]

const { shareOpen, sharePayload, shareList } = useRowActions({
	columns: REORDER_COLUMNS,
	title: (row) => row.item_name || row.item_code,
})

const belowLevel = computed(() => items.value.filter((i) => i.below_count > 0))

const REQUEST_TYPES = [
	{ label: 'Purchase', value: 'Purchase' },
	{ label: 'Transfer', value: 'Transfer' },
	{ label: 'Material Issue', value: 'Material Issue' },
	{ label: 'Manufacture', value: 'Manufacture' },
]

onMounted(load)

let timer = null
watch([search, onlyUnconfigured], () => {
	clearTimeout(timer)
	timer = setTimeout(load, 250)
})

async function load() {
	loading.value = true
	try {
		items.value = await getReorderItems({
			search: search.value,
			onlyUnconfigured: onlyUnconfigured.value,
		})
	} catch (e) {
		notify(e.message || 'Could not load items', 'bad')
		items.value = []
	} finally {
		loading.value = false
	}
}

async function configure(item) {
	open.value = true
	detail.value = null
	edits.value = {}
	detailLoading.value = true
	try {
		detail.value = await getItemReorder({ itemCode: item.item_code })
		parent.value = detail.value.parent
	} catch (e) {
		notify(e.message || 'Could not load item', 'bad')
		open.value = false
	} finally {
		detailLoading.value = false
	}
}

// The cascade inside the modal: choosing a parent reloads its sub-warehouses.
// Edits are dropped — carrying them across would write levels against
// warehouses the user never saw.
watch(parent, async (p) => {
	if (!p || !detail.value || p === detail.value.parent) return
	detailLoading.value = true
	edits.value = {}
	try {
		detail.value = await getItemReorder({ itemCode: detail.value.item_code, parentWarehouse: p })
	} catch (e) {
		notify(e.message || 'Could not switch warehouse', 'bad')
	} finally {
		detailLoading.value = false
	}
})

const parentOptions = computed(() =>
	(detail.value?.parents || []).map((p) => ({
		label: `${p.label} · ${p.child_count} ${p.child_count === 1 ? 'location' : 'locations'}`,
		value: p.name,
	})),
)

function valueOf(row, field) {
	const e = edits.value[row.warehouse]
	if (e && e[field] !== undefined) return e[field]
	return row[field] ?? ''
}

function edit(row, field, value) {
	edits.value = {
		...edits.value,
		[row.warehouse]: { ...(edits.value[row.warehouse] || {}), [field]: value },
	}
}

const dirty = computed(() => Object.keys(edits.value).length)

async function save() {
	if (!dirty.value || !detail.value) return
	saving.value = true
	try {
		const payload = Object.entries(edits.value).map(([warehouse, e]) => {
			const row = detail.value.rows.find((r) => r.warehouse === warehouse) || {}
			return {
				item_code: detail.value.item_code,
				warehouse,
				reorder_level: e.reorder_level ?? row.reorder_level,
				reorder_qty: e.reorder_qty ?? row.reorder_qty,
				material_request_type:
					e.material_request_type ?? row.material_request_type ?? 'Purchase',
			}
		})
		await saveReorderRules(payload)
		open.value = false
		await load()
		notify(`${detail.value.item_name} — reorder levels saved`, 'good')
	} catch (e) {
		notify(e.message || 'Could not save', 'bad')
	} finally {
		saving.value = false
	}
}

let toastTimer = null
function notify(message, tone = 'good') {
	toast.value = { message, tone }
	clearTimeout(toastTimer)
	toastTimer = setTimeout(() => (toast.value = null), 2600)
}
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col overflow-hidden">
		<PageHeader
			title="Reorder levels"
			:subtitle="`${items.length} items · configure each item's locations`"
		>
			<template #actions>
				<div class="w-[200px]">
					<FormControl v-model="search" type="text" placeholder="Search item…" />
				</div>
				<FormControl
					v-model="onlyUnconfigured"
					type="checkbox"
					label="Not yet configured"
				/>
				<Button
					variant="subtle"
					:icon-left="LucideSend"
					:disabled="!belowLevel.length"
					:label="belowLevel.length ? `Share ${belowLevel.length} to buy` : 'Nothing to buy'"
					@click="shareList(belowLevel, 'Below reorder level')"
				/>
				<Button variant="subtle" :icon-left="LucideRefreshCw" :loading="loading" @click="load" />
			</template>
		</PageHeader>

		<div class="min-h-0 flex-1 overflow-auto">
			<div v-if="loading" class="grid h-40 place-items-center"><Spinner class="h-5 w-5" /></div>
			<div v-else-if="!items.length" class="grid h-40 place-items-center px-6 text-center">
				<p class="text-p-sm text-ink-gray-5">No stock items match.</p>
			</div>

			<table v-else class="w-full border-collapse text-p-sm">
				<thead class="sticky top-0 z-10 bg-surface-gray-2">
					<tr>
						<th class="border-b border-outline-gray-2 px-3 py-2 text-left text-p-xs font-medium text-ink-gray-6">Item</th>
						<th class="border-b border-outline-gray-2 px-3 py-2 text-left text-p-xs font-medium text-ink-gray-6">Group</th>
						<th class="border-b border-outline-gray-2 px-3 py-2 text-right text-p-xs font-medium text-ink-gray-6">Total stock</th>
						<th class="border-b border-outline-gray-2 px-3 py-2 text-left text-p-xs font-medium text-ink-gray-6">Reorder setup</th>
						<th class="w-[130px] border-b border-outline-gray-2 px-3 py-2"></th>
					</tr>
				</thead>
				<tbody>
					<!-- An item with a location below its level is the row worth
					     finding, so it keeps the attention tint; the rest band. -->
					<tr
						v-for="(it, i) in items"
						:key="it.item_code"
						class="cursor-pointer transition-colors"
						:class="
							it.below_count
								? 'bg-surface-red-1 hover:bg-surface-red-2'
								: i % 2
									? 'bg-surface-gray-1 hover:bg-surface-gray-2'
									: 'bg-surface-white hover:bg-surface-gray-2'
						"
						@click="configure(it)"
					>
						<td class="px-3 py-1.5">
							<div class="truncate font-medium text-ink-gray-8">{{ it.item_name }}</div>
							<div class="text-p-xs text-ink-gray-5">{{ it.item_code }}</div>
						</td>
						<td class="px-3 py-1.5 text-ink-gray-6">{{ it.item_group }}</td>
						<td class="tabular px-3 py-1.5 text-right text-ink-gray-8">
							{{ Number(it.total_stock).toLocaleString() }}
							<span class="text-p-xs text-ink-gray-5">{{ it.uom }}</span>
						</td>
						<td class="px-3 py-1.5">
							<!-- Colour carries the state: red needs buying now, green is
							     configured and fine, grey is not managed at all. -->
							<Badge
								v-if="it.below_count"
								theme="red"
								variant="subtle"
								:label="`${it.below_count} below level`"
							/>
							<Badge
								v-else-if="it.configured_count"
								theme="green"
								variant="subtle"
								:label="`${it.configured_count} configured`"
							/>
							<Badge v-else theme="gray" variant="subtle" label="Not configured" />
						</td>
						<td class="px-3 py-1.5 text-right" @click.stop>
							<Button
								variant="subtle"
								:icon-left="LucideSettings"
								label="Configure"
								@click="configure(it)"
							/>
						</td>
					</tr>
				</tbody>
			</table>
		</div>

		<!-- Per-item modal: parent at the top, its locations configured below. -->
		<Dialog v-model="open" :options="{ title: detail?.item_name || 'Reorder levels', size: '3xl' }">
			<template #body-content>
				<div v-if="detailLoading" class="grid h-32 place-items-center"><Spinner class="h-5 w-5" /></div>

				<div v-else-if="detail" class="flex flex-col gap-3">
					<div class="text-p-xs text-ink-gray-5">{{ detail.item_code }}</div>

					<FormControl
						type="select"
						v-model="parent"
						:options="parentOptions"
						label="Parent warehouse"
					/>

					<div v-if="!detail.rows.length" class="rounded-lg bg-surface-gray-2 px-3 py-4 text-center text-p-sm text-ink-gray-5">
						This parent has no stocking locations.
					</div>

					<div v-else class="flex flex-col gap-2">
						<div class="text-p-xs font-medium uppercase tracking-wide text-ink-gray-5">
							Locations under this parent
						</div>

						<div
							v-for="row in detail.rows"
							:key="row.warehouse"
							class="rounded-lg border p-3"
							:class="row.below ? 'border-outline-red-2 bg-surface-red-1' : 'border-outline-gray-2'"
						>
							<div class="mb-2 flex items-center justify-between gap-2">
								<span class="text-p-base font-medium text-ink-gray-9">
									{{ row.warehouse_label }}
								</span>
								<span class="tabular text-p-sm" :class="row.below ? 'font-semibold text-ink-red-3' : 'text-ink-gray-6'">
									{{ Number(row.actual_qty).toLocaleString() }} {{ detail.uom }} on hand
								</span>
							</div>

							<div class="grid grid-cols-3 gap-2">
								<FormControl
									:model-value="valueOf(row, 'reorder_level')"
									type="number"
									label="Reorder at"
									placeholder="—"
									@update:model-value="edit(row, 'reorder_level', $event)"
								/>
								<FormControl
									:model-value="valueOf(row, 'reorder_qty')"
									type="number"
									label="Order qty"
									placeholder="—"
									@update:model-value="edit(row, 'reorder_qty', $event)"
								/>
								<FormControl
									type="select"
									:model-value="valueOf(row, 'material_request_type')"
									:options="REQUEST_TYPES"
									label="Via"
									@update:model-value="edit(row, 'material_request_type', $event)"
								/>
							</div>
							<p v-if="!row.configured" class="mt-1.5 text-p-xs text-ink-gray-5">
								Not auto-reordered. Leave blank to keep it that way.
							</p>
						</div>
					</div>
				</div>
			</template>

			<template #actions>
				<Button
					theme="gray"
					variant="solid"
					class="w-full"
					:icon-left="LucideSave"
					:loading="saving"
					:disabled="!dirty"
					:label="dirty ? `Save ${dirty} location${dirty === 1 ? '' : 's'}` : 'No changes'"
					@click="save"
				/>
			</template>
		</Dialog>

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

		<ShareSheet v-model="shareOpen" :payload="sharePayload" />
	</div>
</template>
