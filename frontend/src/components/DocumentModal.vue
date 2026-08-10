<script setup>
import { computed, ref, watch } from 'vue'
import { Badge, Button, Dialog, FormControl, Spinner } from 'frappe-ui'
import DataTable from '@/components/DataTable.vue'
import {
	getDocument,
	getPrintUrl,
	getWhatsappSenders,
	runDocumentAction,
	sendDocumentWhatsapp,
} from '@/data/api'
import { fmtMoney } from '@/utils/format'
import { cellTone, statusTheme } from '@/utils/tone'
import { openPrintWindow } from '@/utils/printWindow'
import LucideCheck from '~icons/lucide/check'
import LucideBan from '~icons/lucide/ban'
import LucideCopy from '~icons/lucide/copy'
import LucideBanknote from '~icons/lucide/banknote'
import LucideReceiptText from '~icons/lucide/receipt-text'
import LucideTruck from '~icons/lucide/truck'
import LucidePackage from '~icons/lucide/package'
import LucideUndo from '~icons/lucide/undo-2'
import LucidePrinter from '~icons/lucide/printer'
import LucideSend from '~icons/lucide/send'

/**
 * The whole document, without leaving the screen.
 *
 * Everything it shows comes from `documents.get_document`, so a doctype added
 * to the registry appears here with no change to this file. The lines are
 * rendered through `DataTable`, which means they get the same colour rules,
 * numeric alignment and status badges as every other table in the app — a
 * negative number means here exactly what it means on the reports screen.
 */
const props = defineProps({
	open: { type: Boolean, default: false },
	/** Registry key, e.g. 'sales-invoice'. */
	docKey: { type: String, default: null },
	name: { type: String, default: null },
})

const emit = defineEmits(['update:open', 'changed', 'notify'])

const doc = ref(null)
const loading = ref(false)
const busy = ref('')
/** Cancel is not undoable, so it takes a second, deliberate click. */
const confirming = ref('')
const printFormat = ref('')
const whatsappTo = ref('')
const showWhatsapp = ref(false)
const whatsappSender = ref('')
const senders = ref([])
/** The PDF is the default: a customer sent an invoice should get the invoice. */
const sendPdf = ref(true)

watch(
	() => [props.open, props.docKey, props.name],
	([open]) => {
		if (open && props.docKey && props.name) load()
	},
	{ immediate: true },
)

async function load() {
	loading.value = true
	confirming.value = ''
	showWhatsapp.value = false
	try {
		doc.value = await getDocument({ key: props.docKey, name: props.name })
		printFormat.value = doc.value.print_formats?.[0] || ''
		whatsappTo.value = doc.value.whatsapp_to || ''
	} catch (e) {
		emit('notify', { message: e.message || 'Could not open this document', tone: 'bad' })
		close()
	} finally {
		loading.value = false
	}
}

function close() {
	emit('update:open', false)
}

const can = (action) => doc.value?.actions?.includes(action)

/**
 * What this document becomes next, as buttons rather than a hidden menu.
 *
 * The row menu already offers these, but the modal is where somebody has
 * actually *read* the document — and deciding to pay a bill or move the stock is
 * a decision you make having looked at it, not one you make from a list.
 *
 * Driven by the same `actions` the server sent, so the two can never come to
 * different conclusions about what is allowed. The labels are the shop's words;
 * `NEXT_LABELS` is the modal's copy of what the list uses.
 */
const NEXT_LABELS = {
	payment: { label: 'Record payment', icon: LucideBanknote },
	invoice: { label: 'Raise the invoice', icon: LucideReceiptText },
	deliver: { label: 'Deliver the goods', icon: LucideTruck },
	receive: { label: 'Receive the goods', icon: LucidePackage },
	stock_entry: { label: 'Move the stock', icon: LucideTruck },
}

const nextSteps = computed(() =>
	Object.keys(NEXT_LABELS)
		.filter((action) => can(action))
		.map((action) => ({ action, ...NEXT_LABELS[action] })),
)

const DESTRUCTIVE = new Set(['cancel'])

async function act(action) {
	if (DESTRUCTIVE.has(action) && confirming.value !== action) {
		confirming.value = action
		return
	}
	confirming.value = ''
	busy.value = action
	try {
		const res = await runDocumentAction({ key: props.docKey, name: props.name, action })
		emit('notify', { message: res.message, tone: 'good' })
		emit('changed', res)
		// Amend and duplicate produce a new draft; the old document is unchanged,
		// so there is nothing left to show here.
		if (res.created) close()
		else await load()
	} catch (e) {
		emit('notify', { message: e.message || `Could not ${action} this document`, tone: 'bad' })
	} finally {
		busy.value = ''
	}
}

async function print() {
	busy.value = 'print'
	try {
		await openPrintWindow(
			async () =>
				(
					await getPrintUrl({
						key: props.docKey,
						name: props.name,
						printFormat: printFormat.value || null,
					})
				).url,
		)
	} catch (e) {
		emit('notify', { message: e.message || 'Could not build a print view', tone: 'bad' })
	} finally {
		busy.value = ''
	}
}

async function sendWhatsapp() {
	if (!showWhatsapp.value) {
		showWhatsapp.value = true
		// Only fetched when someone actually wants to send: most opens of this
		// modal never touch WhatsApp.
		if (!senders.value.length) {
			senders.value = await getWhatsappSenders().catch(() => [])
			whatsappSender.value = senders.value.find((s) => s.is_default)?.value || ''
		}
		return
	}
	busy.value = 'whatsapp'
	try {
		const res = await sendDocumentWhatsapp({
			key: props.docKey,
			name: props.name,
			to: whatsappTo.value,
			sender: whatsappSender.value || null,
			asPdf: sendPdf.value,
		})
		emit('notify', { message: res.message, tone: res.sent ? 'good' : 'bad' })
		if (res.sent) showWhatsapp.value = false
	} catch (e) {
		emit('notify', { message: e.message || 'Could not send', tone: 'bad' })
	} finally {
		busy.value = ''
	}
}

function render(field) {
	if (field.value === null || field.value === undefined || field.value === '') return '—'
	if (field.type === 'currency') return fmtMoney(field.value)
	if (field.type === 'number') return Number(field.value).toLocaleString()
	return String(field.value)
}

const printFormatOptions = computed(() =>
	(doc.value?.print_formats || []).map((f) => ({ label: f, value: f })),
)
</script>

<template>
	<Dialog
		:model-value="open"
		:options="{ title: doc?.title || 'Document', size: '5xl' }"
		@update:model-value="close"
	>
		<template #body-content>
			<div v-if="loading" class="grid h-40 place-items-center"><Spinner class="h-5 w-5" /></div>

			<div v-else-if="doc" class="flex flex-col gap-4">
				<div class="flex flex-wrap items-center gap-2">
					<Badge :theme="statusTheme(doc.status)" variant="subtle" :label="doc.status || '—'" />
					<span class="text-p-xs text-ink-gray-5">{{ doc.name }}</span>
				</div>

				<!-- Header fields. Two columns on a phone, four on a desk: these are
				     short label/value pairs and a single column wastes the width. -->
				<dl class="grid grid-cols-2 gap-x-4 gap-y-2 rounded-lg bg-surface-gray-1 px-3 py-2.5 sm:grid-cols-4">
					<div v-for="field in doc.header" :key="field.key" class="min-w-0">
						<dt class="truncate text-p-xs text-ink-gray-5">{{ field.label }}</dt>
						<dd
							class="truncate text-p-sm text-ink-gray-8"
							:class="[
								field.type === 'currency' || field.type === 'number' ? 'tabular' : '',
								cellTone(field.key, field.value),
							]"
						>
							{{ render(field) }}
						</dd>
					</div>
				</dl>

				<section v-for="table in doc.tables" :key="table.fieldname" class="flex flex-col gap-1">
					<h3 class="text-p-xs font-medium uppercase tracking-wide text-ink-gray-5">
						{{ table.label }}
					</h3>
					<div class="max-h-[300px] overflow-auto rounded-lg border border-outline-gray-2">
						<DataTable :columns="table.columns" :rows="table.rows" empty-text="No lines." />
					</div>
				</section>

				<dl v-if="doc.totals.length" class="ml-auto flex w-full max-w-xs flex-col gap-1">
					<div
						v-for="total in doc.totals"
						:key="total.key"
						class="flex items-baseline justify-between gap-4"
					>
						<dt class="text-p-sm text-ink-gray-6">{{ total.label }}</dt>
						<dd class="tabular text-p-sm font-medium" :class="cellTone(total.key, total.value) || 'text-ink-gray-9'">
							{{ render(total) }}
						</dd>
					</div>
				</dl>

				<!-- The number is editable because the one on file is often a landline
				     or missing, and the alternative is giving up on sending. -->
				<div v-if="showWhatsapp" class="flex flex-wrap items-end gap-2 rounded-lg bg-surface-gray-1 p-3">
					<div class="min-w-[200px] flex-1">
						<FormControl
							v-model="whatsappTo"
							type="text"
							label="Send to"
							placeholder="Phone number or group JID"
						/>
					</div>
					<div v-if="senders.length > 1" class="w-[180px]">
						<FormControl
							type="select"
							v-model="whatsappSender"
							label="From"
							:options="senders.map((s) => ({ label: s.label, value: s.value }))"
						/>
					</div>
					<FormControl v-model="sendPdf" type="checkbox" label="Attach the PDF" />
					<Button
						theme="green"
						variant="solid"
						:icon-left="LucideSend"
						label="Send"
						:loading="busy === 'whatsapp'"
						:disabled="!whatsappTo"
						@click="sendWhatsapp"
					/>
				</div>
			</div>
		</template>

		<template #actions>
			<div v-if="doc" class="flex flex-wrap items-center gap-2">
				<Button
					v-if="can('submit')"
					theme="gray"
					variant="solid"
					:icon-left="LucideCheck"
					label="Submit"
					:loading="busy === 'submit'"
					@click="act('submit')"
				/>
				<Button
					v-if="can('cancel')"
					:theme="confirming === 'cancel' ? 'red' : 'gray'"
					:variant="confirming === 'cancel' ? 'solid' : 'subtle'"
					:icon-left="LucideBan"
					:label="confirming === 'cancel' ? 'Confirm cancel' : 'Cancel'"
					:loading="busy === 'cancel'"
					@click="act('cancel')"
				/>
				<Button
					v-if="can('amend')"
					variant="subtle"
					:icon-left="LucideUndo"
					label="Amend"
					:loading="busy === 'amend'"
					@click="act('amend')"
				/>
				<Button
					v-if="can('duplicate')"
					variant="subtle"
					:icon-left="LucideCopy"
					label="Duplicate"
					:loading="busy === 'duplicate'"
					@click="act('duplicate')"
				/>

				<!-- The next document. Solid rather than subtle: having read the
				     thing, this is usually why you opened it. -->
				<Button
					v-for="step in nextSteps"
					:key="step.action"
					theme="gray"
					variant="solid"
					:icon-left="step.icon"
					:label="step.label"
					:loading="busy === step.action"
					@click="act(step.action)"
				/>

				<div v-if="printFormatOptions.length > 1" class="w-[170px]">
					<FormControl type="select" v-model="printFormat" :options="printFormatOptions" />
				</div>
				<Button
					variant="subtle"
					:icon-left="LucidePrinter"
					label="Print"
					:loading="busy === 'print'"
					@click="print"
				/>
				<Button
					variant="subtle"
					:icon-left="LucideSend"
					label="WhatsApp"
					@click="sendWhatsapp"
				/>
			</div>
		</template>
	</Dialog>
</template>
