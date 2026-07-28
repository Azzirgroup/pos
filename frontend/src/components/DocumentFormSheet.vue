<script setup>
import { computed, ref, watch } from 'vue'
import { Button, Dialog, FormControl, Spinner } from 'frappe-ui'
import { createDocument, getDocumentForm, getDocumentLinkOptions } from '@/data/api'
import { fmtMoney } from '@/utils/format'
import LucidePlus from '~icons/lucide/plus'
import LucideX from '~icons/lucide/x'

/**
 * Raising a document with its lines, without leaving the app.
 *
 * The whole form — header fields, line fields, which are required, what the
 * dates default to — comes from `documents.new_document_form`. Nothing about
 * Sales Order or Material Request is written here, so making a fourth type
 * creatable is a `create` block in the registry and no change to this file.
 *
 * Rates are left blank by default on purpose: the server runs ERPNext's own
 * `set_missing_values`, which prices the line from the price list. Typing a rate
 * here overrides that, which is what you want when a supplier quotes you
 * something different — and not what you want by accident.
 */
const props = defineProps({
	open: { type: Boolean, default: false },
	docKey: { type: String, default: null },
})

const emit = defineEmits(['update:open', 'created', 'notify'])

const form = ref(null)
const values = ref({})
const lines = ref([])
const options = ref({})
const loading = ref(false)
const saving = ref('')

watch(
	() => [props.open, props.docKey],
	([open]) => {
		if (open && props.docKey) load()
	},
	{ immediate: true },
)

async function load() {
	loading.value = true
	form.value = null
	options.value = {}
	try {
		form.value = await getDocumentForm({ key: props.docKey })

		values.value = Object.fromEntries(
			form.value.fields.map((f) => [f.fieldname, f.default ?? '']),
		)
		lines.value = [blankLine()]

		await Promise.all(
			[...form.value.fields, ...form.value.items]
				.filter((f) => f.type === 'link' || f.type === 'item')
				.map(async (f) => {
					options.value[f.fieldname] = await getDocumentLinkOptions({
						key: props.docKey,
						fieldname: f.fieldname,
					}).catch(() => [])
				}),
		)
	} catch (e) {
		emit('notify', { message: e.message || 'Could not open the form', tone: 'bad' })
		close()
	} finally {
		loading.value = false
	}
}

function blankLine() {
	return Object.fromEntries((form.value?.items || []).map((f) => [f.fieldname, f.default ?? '']))
}

function addLine() {
	lines.value.push(blankLine())
}

function removeLine(i) {
	lines.value.splice(i, 1)
	if (!lines.value.length) addLine()
}

function close() {
	emit('update:open', false)
}

const filled = computed(() =>
	lines.value.filter((l) => l.item_code && Number(l.qty) > 0),
)

/** What is stopping the save, or null. Named so the button can say it. */
const blocker = computed(() => {
	if (!form.value) return 'Loading'
	const missing = form.value.fields
		.filter((f) => f.required && !String(values.value[f.fieldname] ?? '').trim())
		.map((f) => f.label)
	if (missing.length) return `Fill in ${missing.join(', ')}`
	if (!filled.value.length) return 'Add at least one line'
	return null
})

/** Indicative only — the server prices the lines, so this is not the total. */
const estimate = computed(() =>
	filled.value.reduce((sum, l) => sum + Number(l.qty || 0) * Number(l.rate || 0), 0),
)

async function save(submit) {
	if (blocker.value) return
	saving.value = submit ? 'submit' : 'draft'
	try {
		const res = await createDocument({
			key: props.docKey,
			values: values.value,
			items: filled.value,
			submit,
		})
		emit('notify', { message: res.message, tone: 'good' })
		emit('created', res)
		close()
	} catch (e) {
		emit('notify', { message: e.message || 'Could not create the document', tone: 'bad' })
	} finally {
		saving.value = ''
	}
}

function controlType(field) {
	if (field.type === 'link' || field.type === 'item' || field.type === 'select') return 'select'
	if (field.type === 'date') return 'date'
	if (field.type === 'number' || field.type === 'currency') return 'number'
	return 'text'
}

function optionsFor(field) {
	if (field.type === 'select') return (field.options || []).map((o) => ({ label: o, value: o }))
	return options.value[field.fieldname] || []
}
</script>

<template>
	<Dialog
		:model-value="open"
		:options="{ title: form ? `New ${form.label}` : 'New document', size: '4xl' }"
		@update:model-value="close"
	>
		<template #body-content>
			<div v-if="loading" class="grid h-40 place-items-center"><Spinner class="h-5 w-5" /></div>

			<div v-else-if="form" class="flex flex-col gap-4">
				<div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
					<FormControl
						v-for="field in form.fields"
						:key="field.fieldname"
						v-model="values[field.fieldname]"
						:type="controlType(field)"
						:label="field.required ? `${field.label} *` : field.label"
						:options="controlType(field) === 'select' ? optionsFor(field) : undefined"
					/>
				</div>

				<div class="flex flex-col gap-2">
					<div class="flex items-center justify-between">
						<h3 class="text-p-xs font-medium uppercase tracking-wide text-ink-gray-5">Lines</h3>
						<span class="text-p-xs text-ink-gray-5">
							Leave the rate blank to use the price list
						</span>
					</div>

					<div
						v-for="(line, i) in lines"
						:key="i"
						class="flex flex-wrap items-end gap-2 rounded-lg border border-outline-gray-2 p-2.5"
					>
						<div
							v-for="field in form.items"
							:key="field.fieldname"
							:class="field.type === 'item' ? 'min-w-[200px] flex-1' : 'w-[120px]'"
						>
							<FormControl
								v-model="line[field.fieldname]"
								:type="controlType(field)"
								:label="field.label"
								:options="controlType(field) === 'select' ? optionsFor(field) : undefined"
							/>
						</div>
						<button
							class="grid h-8 w-8 shrink-0 place-items-center rounded-md text-ink-gray-5 transition-colors hover:bg-surface-gray-2 hover:text-ink-red-3"
							:aria-label="`Remove line ${i + 1}`"
							@click="removeLine(i)"
						>
							<LucideX class="h-4 w-4" />
						</button>
					</div>

					<div class="flex items-center gap-3">
						<Button variant="subtle" :icon-left="LucidePlus" label="Add line" @click="addLine" />
						<span v-if="estimate" class="tabular ml-auto text-p-sm text-ink-gray-6">
							Roughly {{ fmtMoney(estimate) }}
							<span class="text-ink-gray-5">· priced properly on save</span>
						</span>
					</div>
				</div>
			</div>
		</template>

		<template #actions>
			<div v-if="form" class="flex flex-wrap items-center gap-2">
				<Button
					theme="gray"
					variant="solid"
					:loading="saving === 'draft'"
					:disabled="!!blocker"
					:label="blocker || 'Save as draft'"
					@click="save(false)"
				/>
				<!-- Submitting is the irreversible one, so it is the secondary button
				     and never the default. -->
				<Button
					v-if="form.can_submit"
					variant="subtle"
					:loading="saving === 'submit'"
					:disabled="!!blocker"
					label="Save and submit"
					@click="save(true)"
				/>
			</div>
		</template>
	</Dialog>
</template>
