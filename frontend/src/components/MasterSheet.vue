<script setup>
import { computed, ref, watch } from 'vue'
import { Button, Dialog, FormControl, Spinner } from 'frappe-ui'
import { createMaster, getMasterOptions, getMasterRecord, listMasterTypes, updateMaster } from '@/data/api'
import { resolveIcon } from '@/utils/icons'
import LinkField from './LinkField.vue'
import LucidePlus from '~icons/lucide/plus'
import LucideExternalLink from '~icons/lucide/external-link'

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

async function loadRecord() {
	editing.value = await getMasterRecord({ key: activeKey.value, name: props.editName })
	// Nulls become empty strings so the controls are actually editable rather
	// than showing a placeholder that will not clear.
	values.value = Object.fromEntries(
		Object.entries(editing.value.values).map(([k, v]) => [k, v ?? '']),
	)
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
			emit('update:open', false)
			return
		}

		const res = await createMaster({ key: activeKey.value, values: values.value })
		created.value = res
		values.value = {}
		emit('created', res)
		emit('notify', { message: res.message, tone: 'good' })
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
		:options="{ title: editing ? `Edit ${editing.title}` : 'Add a record', size: '2xl' }"
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
				<div v-if="!editing" class="flex flex-wrap gap-2">
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
						<LinkField
							v-if="field.type === 'link'"
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
