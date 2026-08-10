<script setup>
import { computed, ref, watch } from 'vue'
import { Button, Dialog, FormControl, Spinner } from 'frappe-ui'
import {
	createDocument,
	createLandedCostVoucher,
	createMaster,
	getDocumentForm,
	getDocumentLinkOptions,
	getExpenseAccounts,
} from '@/data/api'
import { fmtMoney } from '@/utils/format'
import LinkField from './LinkField.vue'
import LucidePlus from '~icons/lucide/plus'
import LucideX from '~icons/lucide/x'

/**
 * Link fields whose target can be created from typing a name alone — every
 * other field `master.py` exposes needs at least one more required value
 * (an Item's group, an Account's parent), so offering "Create" there would
 * fail on the very next line ERPNext validates. These four do not.
 */
const QUICK_CREATE_MASTER = {
	Supplier: 'supplier',
	Customer: 'customer',
	Warehouse: 'warehouse',
	'Item Group': 'item_group',
}

function onCreateFor(field) {
	const masterKey = QUICK_CREATE_MASTER[field.options]
	if (!masterKey) return null
	return async (typed) => {
		const res = await createMaster({ key: masterKey, values: { [`${masterKey}_name`]: typed } })
		return { label: res.title || typed, value: res.name }
	}
}

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
	/**
	 * Skip the draft step entirely — one button, and it submits.
	 *
	 * For a flow where the document only means anything once it is real: a
	 * bulk Purchase Receipt sitting as a draft is stock that has not actually
	 * landed yet, and "remember to come back and submit it" is exactly the
	 * step this exists to remove. Editing still happens first, in the same
	 * form — this only removes the *choice* to leave it a draft, not the
	 * chance to fix a line before it posts.
	 */
	forceSubmit: { type: Boolean, default: false },
	/**
	 * Off for the nested instance this sheet opens on itself to raise a
	 * vendor's invoice — that invoice is the *source* of a landed cost, not
	 * itself a place to start another one, and letting it offer its own
	 * checkbox would let a landed cost voucher nest inside a landed cost
	 * voucher's own vendor invoice.
	 */
	allowLandedCost: { type: Boolean, default: true },
})

const emit = defineEmits(['update:open', 'created', 'notify'])

const form = ref(null)
const values = ref({})
const lines = ref([])
const loading = ref(false)
const saving = ref('')

/**
 * Freight, customs, anything that lands on top of what the supplier billed
 * for the goods themselves — offered only for the two document types it
 * means anything for. See `create_landed_cost_voucher`.
 */
const LANDED_COST_KEYS = new Set(['purchase-receipt', 'purchase-invoice'])
const showsLandedCost = computed(
	() => props.allowLandedCost && LANDED_COST_KEYS.has(props.docKey),
)
const landedCost = ref({ enabled: false, distributeBasedOn: 'Qty', charges: [] })
/** The nested sheet a charge's "Create vendor invoice" button opens. */
const vendorInvoiceOpen = ref(false)
const vendorInvoiceCharge = ref(null)

function blankCharge() {
	return { description: '', amount: '', expense_account: '', vendorInvoice: null }
}

function addCharge() {
	landedCost.value.charges.push(blankCharge())
}

function removeCharge(i) {
	landedCost.value.charges.splice(i, 1)
}

function openVendorInvoice(charge) {
	vendorInvoiceCharge.value = charge
	vendorInvoiceOpen.value = true
}

function onVendorInvoiceCreated(res) {
	const charge = vendorInvoiceCharge.value
	if (!charge) return
	charge.vendorInvoice = { name: res.name, grandTotal: res.grand_total }
	// A default, not a lock: the amount actually allocated can differ from
	// what the freight company billed in total, so it stays editable.
	if (!charge.amount) charge.amount = res.grand_total || ''
	if (!charge.description) charge.description = `Freight/customs — ${res.name}`
}

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
	try {
		form.value = await getDocumentForm({ key: props.docKey })

		values.value = Object.fromEntries(
			form.value.fields.map((f) => [f.fieldname, f.default ?? '']),
		)
		lines.value = [blankLine()]
		landedCost.value = { enabled: false, distributeBasedOn: 'Qty', charges: [] }
		// Link and item fields search the server themselves as the cashier
		// types (`LinkField`) rather than choosing from a list pre-fetched
		// here — a fixed twenty rows meant the supplier or item actually
		// wanted was often simply never in it.
	} catch (e) {
		emit('notify', { message: e.message || 'Could not open the form', tone: 'bad' })
		close()
	} finally {
		loading.value = false
	}
}

function linkFetcher(fieldname) {
	return (search) => getDocumentLinkOptions({ key: props.docKey, fieldname, search })
}

const expenseAccountFetcher = (search) => getExpenseAccounts(search)

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

/**
 * Purchase Invoice / Purchase Receipt only: the per-line field that lets a
 * bulk entry span more than one supplier. Its presence, not the doc key
 * itself, is what switches the lines below from a flat list to sections
 * grouped by supplier — the same field spec drives the `LinkField` this
 * component already renders for it in the flat view.
 */
const supplierField = computed(() => form.value?.items?.find((f) => f.fieldname === 'supplier') || null)

/**
 * Runs of consecutive lines sharing a supplier, in the order they were
 * added — not a lookup by supplier name. Deriving groups from array order
 * rather than from a separate group id is what makes "add supplier, add its
 * items, add another supplier" work with no bookkeeping beyond the lines
 * array `save()` already sends: appending a line with a different supplier
 * starts a new section purely because it no longer matches the run before
 * it.
 */
const supplierGroups = computed(() => {
	if (!supplierField.value) return null
	const groups = []
	for (const line of lines.value) {
		const supplier = line.supplier || ''
		const last = groups[groups.length - 1]
		if (last && last.supplier === supplier) last.lines.push(line)
		else groups.push({ supplier, lines: [line] })
	}
	return groups
})

function addSupplierGroup() {
	lines.value.push(blankLine())
}

/**
 * Carry the header's "Default supplier" onto the lines that have none.
 *
 * The server already falls back to it when a line names nobody, so a receipt
 * saved this way was always correct — but the group above the items stayed
 * blank, which reads as the field having done nothing. Filling it in makes the
 * form show what is actually going to happen.
 *
 * Only empty groups are touched: a line that names its own supplier is a
 * deliberate exception in a bulk entry, and overwriting it would silently
 * re-bill somebody else's goods.
 */
watch(
	() => values.value?.supplier,
	(supplier) => {
		if (!supplier || !supplierField.value) return
		for (const line of lines.value) {
			if (!line.supplier) line.supplier = supplier
		}
	},
)

function addItemToGroup(group) {
	const line = blankLine()
	// The group's own supplier, falling back to the header default so a new row
	// under an unnamed group is not the one line that ends up blank.
	line.supplier = group.supplier || values.value?.supplier || ''
	lines.value.push(line)
}

function setGroupSupplier(group, value) {
	for (const line of group.lines) line.supplier = value
}

function removeGroup(group) {
	lines.value = lines.value.filter((l) => !group.lines.includes(l))
	if (!lines.value.length) addLine()
}

function close() {
	emit('update:open', false)
}

const filled = computed(() =>
	lines.value.filter((l) => l.item_code && Number(l.qty) > 0),
)

/** Charges with an amount above zero — the rest are unfinished rows, dropped
 *  rather than sent as zero-cost lines nobody meant to add. */
const filledCharges = computed(() =>
	landedCost.value.charges.filter((c) => Number(c.amount) > 0 && c.expense_account),
)

/** What is stopping the save, or null. Named so the button can say it. */
const blocker = computed(() => {
	if (!form.value) return 'Loading'
	const missing = form.value.fields
		.filter((f) => f.required && !String(values.value[f.fieldname] ?? '').trim())
		.map((f) => f.label)
	if (missing.length) return `Fill in ${missing.join(', ')}`
	if (!filled.value.length) return 'Add at least one line'
	if (landedCost.value.enabled && !filledCharges.value.length) {
		return 'Add a charge with an amount and an expense account, or turn off landed cost'
	}
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

		// The receipt/invoice is real and submitted at this point regardless of
		// what happens next — a failed landed cost voucher must not read as a
		// failed purchase. Reported as its own notification either way.
		if (res.created?.length > 1) {
			// A multi-supplier bulk entry became several documents, and a
			// landed cost voucher can only point at one — applying it to just
			// the first would silently drop the charge from the rest, which
			// is worse than not applying it and saying so.
			if (landedCost.value.enabled && filledCharges.value.length) {
				emit('notify', {
					message: `${res.created.length} documents were raised (one per supplier) — add landed cost to each from its own page, it cannot be split across them here.`,
					tone: 'warn',
				})
			}
		} else if (landedCost.value.enabled && filledCharges.value.length) {
			try {
				const lcv = await createLandedCostVoucher({
					receiptKey: props.docKey,
					receiptName: res.name,
					charges: filledCharges.value.map((c) => ({
						description: c.description,
						amount: c.amount,
						expense_account: c.expense_account,
					})),
					vendorInvoices: filledCharges.value
						.filter((c) => c.vendorInvoice)
						.map((c) => ({ name: c.vendorInvoice.name, amount: c.vendorInvoice.grandTotal })),
					distributeBasedOn: landedCost.value.distributeBasedOn,
				})
				emit('notify', { message: lcv.message, tone: 'good' })
			} catch (e) {
				emit('notify', {
					message: `${res.name} is fine, but the landed cost voucher failed: ${e.message || 'server error'}`,
					tone: 'bad',
				})
			}
		}

		close()
	} catch (e) {
		emit('notify', { message: e.message || 'Could not create the document', tone: 'bad' })
	} finally {
		saving.value = ''
	}
}

function controlType(field) {
	if (field.type === 'select') return 'select'
	if (field.type === 'date') return 'date'
	if (field.type === 'number' || field.type === 'currency') return 'number'
	return 'text'
}

function optionsFor(field) {
	return (field.options || []).map((o) => ({ label: o, value: o }))
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
				<!-- What this document is for, where it is not obvious. A stock
				     reconciliation setting the balance rather than adding to it is
				     the kind of thing worth saying before, not after. -->
				<p v-if="form.hint" class="rounded-lg bg-surface-amber-1 px-3 py-2 text-p-xs text-ink-amber-3">
					{{ form.hint }}
				</p>

				<div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
					<template v-for="field in form.fields" :key="field.fieldname">
						<LinkField
							v-if="field.type === 'link' || field.type === 'item'"
							v-model="values[field.fieldname]"
							:fetcher="linkFetcher(field.fieldname)"
							:on-create="onCreateFor(field)"
							:label="field.label"
							:required="field.required"
						/>
						<FormControl
							v-else
							v-model="values[field.fieldname]"
							:type="controlType(field)"
							:label="field.required ? `${field.label} *` : field.label"
							:options="controlType(field) === 'select' ? optionsFor(field) : undefined"
						/>
					</template>
				</div>

				<div class="flex flex-col gap-2">
					<div class="flex items-center justify-between">
						<h3 class="text-p-xs font-medium uppercase tracking-wide text-ink-gray-5">Lines</h3>
						<span class="text-p-xs text-ink-gray-5">
							Leave the rate blank to use the price list
						</span>
					</div>

					<!-- Purchase Invoice / Purchase Receipt: grouped by supplier rather
					     than one flat list with a supplier dropdown repeated on every
					     row — pick a supplier once per section, add its items under it,
					     then start the next section for the next supplier. `save()`
					     still just sees a flat list of lines; the grouping is a way of
					     filling it in, not a different shape sent to the server. -->
					<template v-if="supplierField">
						<div
							v-for="(group, gi) in supplierGroups"
							:key="gi"
							class="flex flex-col gap-2 rounded-lg border border-outline-gray-2 p-2.5"
						>
							<div class="flex items-end gap-2">
								<LinkField
									:model-value="group.supplier"
									@update:model-value="(v) => setGroupSupplier(group, v)"
									:fetcher="linkFetcher('supplier')"
									:on-create="onCreateFor(supplierField)"
									:label="`Supplier ${gi + 1}`"
									class="min-w-[200px] flex-1"
								/>
								<button
									class="grid h-8 w-8 shrink-0 place-items-center rounded-md text-ink-gray-5 transition-colors hover:bg-surface-gray-2 hover:text-ink-red-3"
									:aria-label="`Remove supplier ${gi + 1} and its items`"
									@click="removeGroup(group)"
								>
									<LucideX class="h-4 w-4" />
								</button>
							</div>

							<div
								v-for="line in group.lines"
								:key="lines.indexOf(line)"
								class="flex flex-wrap items-end gap-2 rounded-lg bg-surface-gray-1 p-2"
							>
								<template v-for="field in form.items" :key="field.fieldname">
									<div
										v-if="field.fieldname !== 'supplier'"
										:class="field.type === 'item' ? 'min-w-[200px] flex-1' : 'w-[120px]'"
									>
										<LinkField
											v-if="field.type === 'link' || field.type === 'item'"
											v-model="line[field.fieldname]"
											:fetcher="linkFetcher(field.fieldname)"
											:on-create="onCreateFor(field)"
											:label="field.label"
										/>
										<FormControl
											v-else
											v-model="line[field.fieldname]"
											:type="controlType(field)"
											:label="field.label"
											:options="controlType(field) === 'select' ? optionsFor(field) : undefined"
										/>
									</div>
								</template>
								<button
									class="grid h-8 w-8 shrink-0 place-items-center rounded-md text-ink-gray-5 transition-colors hover:bg-surface-gray-2 hover:text-ink-red-3"
									:aria-label="`Remove line`"
									@click="removeLine(lines.indexOf(line))"
								>
									<LucideX class="h-4 w-4" />
								</button>
							</div>

							<Button
								variant="subtle"
								:icon-left="LucidePlus"
								label="Add item"
								class="self-start"
								@click="addItemToGroup(group)"
							/>
						</div>

						<div class="flex items-center gap-3">
							<Button
								variant="subtle"
								:icon-left="LucidePlus"
								label="Add supplier"
								@click="addSupplierGroup"
							/>
							<span v-if="estimate" class="tabular ml-auto text-p-sm text-ink-gray-6">
								Roughly {{ fmtMoney(estimate) }}
								<span class="text-ink-gray-5">· priced properly on save</span>
							</span>
						</div>
					</template>

					<!-- Every other document type: the flat list this always was. -->
					<template v-else>
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
								<LinkField
									v-if="field.type === 'link' || field.type === 'item'"
									v-model="line[field.fieldname]"
									:fetcher="linkFetcher(field.fieldname)"
									:on-create="onCreateFor(field)"
									:label="field.label"
								/>
								<FormControl
									v-else
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
					</template>
				</div>

				<!-- Freight, customs -- cost that lands on top of what the supplier
				     billed for the goods. Offered here because this is the moment
				     it is actually known, not a reason to come back and open a
				     second form once the receipt already exists. -->
				<div v-if="showsLandedCost" class="flex flex-col gap-2 rounded-lg border border-outline-gray-2 p-3">
					<label class="flex min-h-touch cursor-pointer items-center gap-3">
						<input
							v-model="landedCost.enabled"
							type="checkbox"
							class="h-5 w-5 shrink-0 rounded border-outline-gray-3 text-ink-gray-8 focus:ring-outline-gray-3"
						/>
						<span class="min-w-0 flex-1">
							<span class="block text-p-base font-medium text-ink-gray-9">Add landed cost</span>
							<span class="block text-p-xs text-ink-gray-5">
								Allocate freight, customs or other charges across these items
							</span>
						</span>
					</label>

					<template v-if="landedCost.enabled">
						<div
							v-for="(charge, i) in landedCost.charges"
							:key="i"
							class="flex flex-col gap-2 rounded-lg border border-outline-gray-2 p-2.5"
						>
							<div class="flex flex-wrap items-end gap-2">
								<FormControl
									v-model="charge.description"
									type="text"
									label="Charge"
									placeholder="Freight, customs..."
									class="min-w-[160px] flex-1"
								/>
								<FormControl v-model="charge.amount" type="number" label="Amount" class="w-[120px]" />
								<LinkField
									v-model="charge.expense_account"
									:fetcher="expenseAccountFetcher"
									label="Expense account"
									class="min-w-[160px] flex-1"
								/>
								<button
									class="grid h-8 w-8 shrink-0 place-items-center rounded-md text-ink-gray-5 transition-colors hover:bg-surface-gray-2 hover:text-ink-red-3"
									:aria-label="`Remove charge ${i + 1}`"
									@click="removeCharge(i)"
								>
									<LucideX class="h-4 w-4" />
								</button>
							</div>

							<!-- Optional: the real bill this charge came from, created
							     without leaving this form. Reference only -- the amount
							     above is what actually gets allocated, and stays
							     editable even once this is attached. -->
							<div
								v-if="charge.vendorInvoice"
								class="flex items-center gap-2 rounded-md bg-surface-green-2 px-2.5 py-1.5 text-p-xs text-ink-green-3"
							>
								<span class="min-w-0 flex-1 truncate font-medium">
									Backed by {{ charge.vendorInvoice.name }}
									<span v-if="charge.vendorInvoice.grandTotal" class="font-normal">
										({{ fmtMoney(charge.vendorInvoice.grandTotal) }})
									</span>
								</span>
								<button class="shrink-0 font-medium underline" @click="charge.vendorInvoice = null">
									Unlink
								</button>
							</div>
							<Button
								v-else
								variant="subtle"
								:icon-left="LucidePlus"
								label="Create vendor invoice"
								class="self-start"
								@click="openVendorInvoice(charge)"
							/>
						</div>

						<div class="flex items-center gap-3">
							<Button variant="subtle" :icon-left="LucidePlus" label="Add charge" @click="addCharge" />
							<div class="ml-auto w-[180px]">
								<FormControl
									v-model="landedCost.distributeBasedOn"
									type="select"
									label="Distribute by"
									:options="['Qty', 'Amount', 'Distribute Manually']"
								/>
							</div>
						</div>
					</template>
				</div>
			</div>
		</template>

		<template #actions>
			<div v-if="form && forceSubmit" class="flex flex-wrap items-center gap-2">
				<Button
					theme="gray"
					variant="solid"
					:loading="saving === 'submit'"
					:disabled="!!blocker || !form.can_submit"
					:label="blocker || (form.can_submit ? 'Create & submit' : 'You cannot submit this document')"
					@click="save(true)"
				/>
			</div>
			<div v-else-if="form" class="flex flex-wrap items-center gap-2">
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

	<!-- Recursive on purpose: raising the freight/customs company's own
	     invoice is the same form this component already is. Gated on
	     `allowLandedCost` — not just the checkbox section above, but this
	     element itself — because an unconditionally-rendered self-reference
	     mounts its own nested copy at *mount* time regardless of whether its
	     dialog is open, and that copy mounts another: infinite recursion
	     before any of them are ever shown. `allow-landed-cost="false"` on the
	     nested instance means its own copy of this same element does not
	     render at all, which is what actually breaks the chain. -->
	<DocumentFormSheet
		v-if="allowLandedCost"
		v-model:open="vendorInvoiceOpen"
		doc-key="purchase-invoice"
		force-submit
		:allow-landed-cost="false"
		@created="onVendorInvoiceCreated"
		@notify="emit('notify', $event)"
	/>
</template>
