<script setup>
import { computed, ref, watch } from 'vue'
import { Button, Dialog, FormControl, Spinner } from 'frappe-ui'
import {
	createMaster,
	findSimilarMasters,
	getMasterOptions,
	getMasterRecord,
	listMasterTypes,
	updateMaster,
} from '@/data/api'
import { fmtMoney } from '@/utils/format'
import { resolveIcon } from '@/utils/icons'
import { useCatalogStore } from '@/stores/catalog'
import LinkField from './LinkField.vue'
import ImageField from './ImageField.vue'
import LucidePlus from '~icons/lucide/plus'
import LucideExternalLink from '~icons/lucide/external-link'
import LucideSearchCheck from '~icons/lucide/search-check'

/**
 * Quick-add for the records a shop creates itself.
 *
 * The form is built from what the server says the type needs, so adding a field
 * — or a whole new type — is a change to `api/master.py` and nothing here. Only
 * the fields a shop actually fills in are offered; everything else is left to
 * ERPNext's defaults, and the link to the desk covers the rest.
 */
const props = defineProps({
	open: { type: Boolean, default: false },
	/** Preselect a type, e.g. 'supplier' from the neighbour empty state. */
	initialKey: { type: String, default: null },
	/**
	 * An existing record to edit. The same form either way — a phone number
	 * typed wrong at the counter is corrected in the place it was entered, not
	 * by sending someone to the desk to find the record again.
	 */
	editName: { type: String, default: null },
	/** Hide the type picker — the caller already knows what it is adding. */
	lockType: { type: Boolean, default: false },
	/** Values to start a new record with, e.g. the name typed into a search. */
	initialValues: { type: Object, default: null },
	/** Close after one record is created, for a caller waiting on that record. */
	closeOnCreate: { type: Boolean, default: false },
})

const emit = defineEmits(['update:open', 'created', 'notify'])

const types = ref([])
const activeKey = ref(null)
const values = ref({})
const saving = ref(false)
const loading = ref(false)
const created = ref(null)
/**
 * Editing an existing record rather than adding one. Declared above the watcher
 * because that watcher is `immediate` and runs during setup — a `const` read
 * before its own line is a temporal-dead-zone throw, not an undefined.
 */
const editing = ref(null)

const active = computed(() => types.value.find((t) => t.key === activeKey.value) || null)

/* ---------- is this already on the system? ---------- */

/**
 * Records that already look like the one being typed.
 *
 * A shop adds the same product twice because the person filling in this form
 * cannot see the shelf list while they are in it — so one product ends up
 * under two codes and its stock never adds up again. Asked while they type
 * rather than refused on save: two products genuinely can share words, and the
 * shop is the one who knows which.
 */
const similar = ref([])
const similarChecking = ref(false)

/** The box that names the record — the one worth checking for duplicates. */
const probeText = computed(() => {
	if (!active.value || editing.value) return ''
	const title = active.value.title_field
	const typed = String(values.value[title] ?? '').trim()
	// The code is the other thing somebody types that already exists.
	return typed || String(values.value[active.value.fields[0]?.fieldname] ?? '').trim()
})

let probeTimer = null
let probeSeq = 0
watch(probeText, (text) => {
	clearTimeout(probeTimer)
	if (text.length < 3) {
		similar.value = []
		similarChecking.value = false
		return
	}
	similarChecking.value = true
	// Typing speed, not network speed: a lookup per keystroke would run a
	// dozen queries to answer a question asked once.
	probeTimer = setTimeout(async () => {
		const mine = ++probeSeq
		try {
			const found = await findSimilarMasters({ key: activeKey.value, text })
			if (mine !== probeSeq) return
			similar.value = found
		} catch {
			if (mine === probeSeq) similar.value = []
		} finally {
			if (mine === probeSeq) similarChecking.value = false
		}
	}, 350)
})

/** Open the one that already exists instead of adding another. */
async function openExisting(row) {
	clearTimeout(probeTimer)
	similar.value = []
	loading.value = true
	try {
		await loadRecord(row.name)
	} catch (e) {
		emit('notify', { message: e.message || 'Could not open that record', tone: 'bad' })
	} finally {
		loading.value = false
	}
}

watch(
	() => props.open,
	async (open) => {
		if (!open) return
		created.value = null
		loading.value = true
		try {
			if (!types.value.length) types.value = await listMasterTypes()
			await pick(props.initialKey || activeKey.value || types.value[0]?.key)
			if (props.editName) await loadRecord()
			else if (props.initialValues) values.value = { ...props.initialValues }
		} catch (e) {
			emit('notify', { message: e.message || 'Could not load the form', tone: 'bad' })
		} finally {
			loading.value = false
		}
	},
	{ immediate: true },
)

function pick(key) {
	if (!key) return
	activeKey.value = key
	editing.value = null
	values.value = {}
	created.value = null
	similar.value = []
	// Link fields (`LinkField`) search the server themselves as the cashier
	// types, rather than choosing from a list pre-fetched here — see that
	// component for why. Only plain `select` fields still read from
	// `field.options`, fixed choices the server already sent with the type.
}

const canSave = computed(
	() =>
		active.value?.fields
			.filter((f) => f.required)
			.every((f) => String(values.value[f.fieldname] ?? '').trim()) ?? false,
)

async function loadRecord(name = props.editName) {
	editing.value = await getMasterRecord({ key: activeKey.value, name })
	// Nulls become empty strings so the controls are actually editable rather
	// than showing a placeholder that will not clear.
	values.value = Object.fromEntries(
		Object.entries(editing.value.values).map(([k, v]) => [k, v ?? '']),
	)
}

/**
 * The till holds its own copy of the catalogue, loaded once.
 *
 * So an item edited here — a renamed product, a new photo, a changed price —
 * stayed as it was on the counter until somebody reloaded the page. Refreshed
 * for items only: nothing else on this form is on the grid.
 */
function refreshTillCatalog() {
	if (activeKey.value === 'item') useCatalogStore().refresh()
}

async function save() {
	if (!canSave.value) return
	saving.value = true
	try {
		if (editing.value) {
			const res = await updateMaster({
				key: activeKey.value,
				name: editing.value.name,
				values: values.value,
			})
			emit('created', res)
			emit('notify', { message: res.message, tone: res.changed ? 'good' : 'bad' })
			refreshTillCatalog()
			emit('update:open', false)
			return
		}

		const res = await createMaster({ key: activeKey.value, values: values.value })
		created.value = res
		values.value = {}
		similar.value = []
		emit('created', res)
		emit('notify', { message: res.message, tone: 'good' })
		refreshTillCatalog()
		if (props.closeOnCreate) emit('update:open', false)
	} catch (e) {
		emit('notify', { message: e.message || 'Could not save', tone: 'bad' })
	} finally {
		saving.value = false
	}
}

function optionsFor(field) {
	return (field.options || []).map((o) => ({ label: o || '—', value: o }))
}
</script>

<template>
	<Dialog
		:model-value="open"
		:options="{
			title: editing ? `Edit ${editing.title}` : lockType && active ? `New ${active.label.toLowerCase()}` : 'Add a record',
			size: '2xl',
		}"
		@update:model-value="emit('update:open', $event)"
	>
		<template #body-content>
			<div v-if="loading && !types.length" class="grid h-32 place-items-center">
				<Spinner class="h-5 w-5" />
			</div>

			<div v-else-if="!types.length" class="grid h-32 place-items-center px-6 text-center">
				<p class="text-p-sm text-ink-gray-5">
					You do not have permission to create any of these records.
				</p>
			</div>

			<div v-else class="flex flex-col gap-4">
				<!-- Type picker. Icons repeat the label rather than replacing it. -->
				<div v-if="!editing && !lockType" class="flex flex-wrap gap-2">
					<button
						v-for="t in types"
						:key="t.key"
						class="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-p-sm transition-colors"
						:class="
							activeKey === t.key
								? 'border-outline-gray-4 bg-surface-gray-3 font-medium text-ink-gray-9'
								: 'border-outline-gray-2 text-ink-gray-6 hover:bg-surface-gray-2'
						"
						@click="pick(t.key)"
					>
						<component
							:is="resolveIcon(t.icon)"
							v-if="resolveIcon(t.icon)"
							class="h-4 w-4"
							aria-hidden="true"
						/>
						{{ t.label }}
					</button>
				</div>

				<p v-if="active?.hint" class="rounded-lg bg-surface-amber-1 px-3 py-2 text-p-xs text-ink-amber-3">
					{{ active.hint }}
				</p>

				<div v-if="active" class="grid gap-3 sm:grid-cols-2">
					<template v-for="field in active.fields" :key="field.fieldname">
						<!-- A photo needs its own control: the value is a URL the
						     server hands back after an upload, not something anybody
						     types. Spans both columns because the preview beside the
						     buttons does not fit in half a row. -->
						<ImageField
							v-if="field.type === 'image'"
							v-model="values[field.fieldname]"
							:label="field.label"
							:doctype="editing?.doctype || ''"
							:docname="editing?.name || ''"
							class="sm:col-span-2"
							@error="emit('notify', { message: $event, tone: 'bad' })"
						/>
						<LinkField
							v-else-if="field.type === 'link'"
							v-model="values[field.fieldname]"
							:fetcher="(search) => getMasterOptions({ key: activeKey, fieldname: field.fieldname, search })"
							:label="field.label"
							:required="field.required"
						/>
						<!-- Own branch: FormControl renders a checkbox as label-beside-box,
						     not label-above-control like every other field type, and needs
						     no options/number coercion. -->
						<FormControl
							v-else-if="field.type === 'checkbox'"
							v-model="values[field.fieldname]"
							type="checkbox"
							:label="field.label"
							class="self-center"
						/>
						<FormControl
							v-else
							v-model="values[field.fieldname]"
							:type="field.type === 'select' ? 'select' : field.type === 'currency' ? 'number' : 'text'"
							:label="field.required ? `${field.label} *` : field.label"
							:options="field.type === 'select' ? optionsFor(field) : undefined"
						/>
					</template>
				</div>

				<!-- What is already there, while they are still typing. Advisory on
				     purpose: it offers the existing record and never blocks the new
				     one, because two products can share a word and only the shop
				     knows which case this is. -->
				<div
					v-if="!editing && (similar.length || similarChecking)"
					class="rounded-lg border border-outline-amber-2 bg-surface-amber-1 px-3 py-2.5"
				>
					<div class="flex items-center gap-2 text-p-sm font-medium text-ink-amber-3">
						<LucideSearchCheck class="h-4 w-4 shrink-0" />
						<span v-if="similar.length">
							Already on the system — {{ similar.length }} like this
						</span>
						<span v-else>Checking what is already there…</span>
					</div>
					<ul v-if="similar.length" class="mt-2 flex flex-col gap-1">
						<li
							v-for="row in similar"
							:key="row.name"
							class="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md bg-surface-white px-2.5 py-2"
						>
							<span class="min-w-0 flex-1 truncate text-p-sm font-medium text-ink-gray-9">
								{{ row.title }}
								<span v-if="row.code" class="ml-1 font-normal text-ink-gray-5">{{ row.code }}</span>
								<span v-if="row.retired" class="ml-1 rounded bg-surface-gray-3 px-1 py-0.5 text-p-xs font-normal text-ink-gray-6">
									retired
								</span>
							</span>
							<span v-if="row.group" class="shrink-0 text-p-xs text-ink-gray-5">{{ row.group }}</span>
							<span v-if="row.stock !== undefined" class="tabular shrink-0 text-p-xs text-ink-gray-6">
								{{ Number(row.stock) }} {{ row.uom || '' }} · {{ fmtMoney(row.price) }}
							</span>
							<button
								type="button"
								class="shrink-0 rounded-md border border-outline-gray-2 bg-surface-white px-2 py-1 text-p-xs font-semibold text-ink-gray-8 hover:bg-surface-gray-2"
								@click="openExisting(row)"
							>
								Open this one
							</button>
						</li>
					</ul>
					<p v-if="similar.length" class="mt-2 text-p-xs text-ink-amber-3">
						Carry on if yours is a different product — this only says what is there.
					</p>
				</div>

				<!-- Confirmation stays on screen so several can be added in a row,
				     and links to the desk for the fields this form leaves out. -->
				<div
					v-if="created"
					class="flex flex-wrap items-center gap-2 rounded-lg bg-surface-green-2 px-3 py-2 text-p-sm text-ink-green-3"
				>
					<span class="font-medium">{{ created.title }} created</span>
					<a
						class="ml-auto flex items-center gap-1 text-p-xs font-medium underline"
						:href="created.desk_url"
						target="_blank"
						rel="noopener"
					>
						Open in the desk to finish the details
						<LucideExternalLink class="h-3 w-3" />
					</a>
				</div>
			</div>
		</template>

		<template #actions>
			<Button
				v-if="types.length"
				theme="gray"
				variant="solid"
				class="w-full"
				:icon-left="LucidePlus"
				:loading="saving"
				:disabled="!canSave"
				:label="
					canSave
						? editing
							? 'Save changes'
							: `Create ${active?.label}`
						: 'Fill in the required fields'
				"
				@click="save"
			/>
		</template>
	</Dialog>
</template>
