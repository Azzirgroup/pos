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
	getItemStock,
	getMasterOptions,
} from '@/data/api'
import { fmtMoney, fmtQty } from '@/utils/format'
import LinkField from './LinkField.vue'
import LucidePlus from '~icons/lucide/plus'
import LucideX from '~icons/lucide/x'

/**
 * Link fields whose target can be created from typing a name alone — every
 * other field `master.py` exposes needs at least one more required value
 * (an Account's parent), so offering "Create" there would fail on the very
 * next line ERPNext validates. These four do not.
 */
const QUICK_CREATE_MASTER = {
	Supplier: 'supplier',
	Customer: 'customer',
	Warehouse: 'warehouse',
	'Item Group': 'item_group',
}

/**
 * "Add item", offered as the last option when a search finds nothing.
 *
 * An item cannot be made from a typed name alone — ERPNext wants a group as
 * well — which is why it was left out of the one-line creates above and why the
 * field simply said "No matches". That is the wrong place to stop: buying
 * something the shop has never stocked before is the *ordinary* reason to be
 * filling in a purchase invoice, and the answer was to abandon the form, go to
 * Records, make the item, and start again.
 *
 * So the offer opens a quick entry instead — ERPNext's own two-step shape, the
 * same one the rider field uses. `LinkField` awaits whatever `on-create`
 * returns and selects it, so this hands back a promise that settles when the
 * dialog does: with the new item, or with null if it was dismissed, which
 * leaves the field as it was.
 */
const itemOpen = ref(false)
const itemSaving = ref(false)
const itemDraft = ref(blankItem())
let itemResolve = null

function blankItem() {
	return { item_code: '', item_name: '', item_group: '', stock_uom: '' }
}

function createItem(typed) {
	itemDraft.value = { ...blankItem(), item_code: typed || '', item_name: typed || '' }
	itemOpen.value = true
	return new Promise((resolve) => {
		itemResolve = resolve
	})
}

/** Hand the waiting `LinkField` its answer, exactly once. */
function settleItem(row) {
	const resolve = itemResolve
	itemResolve = null
	// Dismissing resolves with null rather than rejecting: cancelling a quick
	// entry is an ordinary thing to do, not an error to report.
	if (resolve) resolve(row || null)
}

// Covers the dismissals that never reach `saveItem` — the backdrop, the close
// button, Escape. Without it the field would wait on a promise that never
// settles and its "Creating…" spinner would never stop.
watch(itemOpen, (open) => {
	if (!open) settleItem(null)
})

const itemBlocker = computed(() => {
	const d = itemDraft.value
	if (!d.item_name.trim()) return 'Name the item'
	if (!d.item_group) return 'Choose a group'
	return null
})

async function saveItem() {
	if (itemBlocker.value) return
	itemSaving.value = true
	try {
		const values = {
			// Falls back to the name, which is what a shop types on the packet.
			// ERPNext names the record after the code, so leaving it blank would
			// refuse the save for a field most shops do not distinguish anyway.
			item_code: itemDraft.value.item_code.trim() || itemDraft.value.item_name.trim(),
			item_name: itemDraft.value.item_name.trim(),
			item_group: itemDraft.value.item_group,
			stock_uom: itemDraft.value.stock_uom || undefined,
		}
		const res = await createMaster({ key: 'item', values })
		const option = { label: `${res.title || values.item_name} · ${res.name}`, value: res.name }
		itemOpen.value = false
		settleItem(option)
		emit('notify', { message: `${res.name} added`, tone: 'good' })
	} catch (e) {
		emit('notify', { message: e.message || 'Could not add that item', tone: 'bad' })
	} finally {
		itemSaving.value = false
	}
}

const itemMasterFetcher = (fieldname) => (search) =>
	getMasterOptions({ key: 'item', fieldname, search })

function onCreateFor(field) {
	// An item is the one target with a form of its own rather than a one-liner.
	if (field.type === 'item') return createItem

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

/* ---------- stock beside the lines ---------- */

/**
 * What the shop already holds of each item on the form.
 *
 * Only for the document types whose registry entry asks for it — `show_stock`
 * comes from the server, so nothing here knows that Material Request is the
 * type that wants it. See `documents.DOCUMENTS`.
 *
 * The point is the comparison, not the number: somebody raising a request
 * cannot see the shelf they are asking about, which is exactly why they are
 * asking. Without a balance beside the line the only way to check is to leave
 * the form, which nobody does under a queue — so requests get raised for stock
 * that is already in the back.
 */
const stock = ref({})
const stockLoading = ref(false)

/** Which header field says where "here" is, per the registry. Often blank —
 *  a Purchase request has no source warehouse, and the total still means
 *  something. */
const stockWarehouse = computed(() => {
	const field = form.value?.show_stock?.warehouse_field
	return (field && values.value[field]) || null
})

const wantedCodes = computed(() =>
	[...new Set(lines.value.map((l) => l.item_code).filter(Boolean))],
)

let stockTimer = null
watch(
	// Both, because the answer changes with either: adding a line asks about a
	// new item, and changing the source branch re-asks about all of them.
	() => [form.value?.show_stock ? 1 : 0, wantedCodes.value.join('|'), stockWarehouse.value],
	([enabled, codes]) => {
		clearTimeout(stockTimer)
		if (!enabled || !codes) {
			stock.value = {}
			return
		}
		// Debounced: a cashier picking an item fires this on every keystroke of
		// the search behind it, and the answer is only interesting once they
		// have settled on one.
		stockTimer = setTimeout(loadStock, 300)
	},
)

async function loadStock() {
	if (!wantedCodes.value.length) {
		stock.value = {}
		return
	}
	stockLoading.value = true
	try {
		stock.value = await getItemStock({
			itemCodes: wantedCodes.value,
			warehouse: stockWarehouse.value,
		})
	} catch (e) {
		// Silent. A balance is context, and losing it must not read as the form
		// itself having failed — the request can still be raised without it.
		console.warn('[pos] stock lookup failed', e)
		stock.value = {}
	} finally {
		stockLoading.value = false
	}
}

/**
 * The balance to show for one line, and whether it covers what is being asked
 * for.
 *
 * `here` is the named branch's own count where one was chosen, and the total
 * across every warehouse otherwise. Both are labelled, because "none here but
 * forty in the back" and "none anywhere" call for different actions and a
 * single number cannot tell them apart.
 */
function stockFor(line) {
	const row = line.item_code ? stock.value[line.item_code] : null
	if (!row) return null

	const named = stockWarehouse.value && row.here !== null && row.here !== undefined
	const available = named ? row.here : row.total
	const asked = Number(line.qty) || 0

	return {
		available,
		total: row.total,
		named,
		uom: row.uom,
		// Short only once a quantity has been typed — an untouched line is not
		// yet a claim about anything.
		short: asked > 0 && available < asked,
		none: available <= 0,
	}
}

function stockLabel(line) {
	const s = stockFor(line)
	if (!s) return ''
	const where = s.named ? 'there' : 'in stock'
	const unit = s.uom ? ` ${s.uom}` : ''
	const text = `${fmtQty(s.available)}${unit} ${where}`
	// The elsewhere figure only when it adds something — repeating the same
	// number twice is noise on a line that already has six controls.
	return s.named && s.total !== s.available ? `${text} · ${fmtQty(s.total)} in total` : text
}

function stockTone(line) {
	const s = stockFor(line)
	if (!s) return ''
	if (s.none) return 'bg-surface-red-2 text-ink-red-3'
	if (s.short) return 'bg-surface-amber-2 text-ink-amber-3'
	return 'bg-surface-green-2 text-ink-green-3'
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

/**
 * Fields that only become required once another one is ticked.
 *
 * Just the one so far, and it earns the mechanism: `is_paid` without an account
 * is refused by ERPNext deep inside `validate_cash`, in a sentence naming
 * neither the box that was ticked nor the field to fill in. Said here instead,
 * on the button, before the save.
 */
const CONDITIONAL_REQUIRED = [{ when: 'is_paid', needs: 'cash_bank_account' }]

/** What is stopping the save, or null. Named so the button can say it. */
const blocker = computed(() => {
	if (!form.value) return 'Loading'
	const declared = new Set(form.value.fields.map((f) => f.fieldname))
	const missing = form.value.fields
		.filter((f) => f.required && f.type !== 'check' && !String(values.value[f.fieldname] ?? '').trim())
		.map((f) => f.label)

	for (const rule of CONDITIONAL_REQUIRED) {
		if (!declared.has(rule.when) || !declared.has(rule.needs)) continue
		if (values.value[rule.when] && !values.value[rule.needs]) {
			missing.push(form.value.fields.find((f) => f.fieldname === rule.needs).label)
		}
	}

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
	if (field.type === 'check') return 'checkbox'
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
					<!-- Wrapped so a field can carry its own note. Some of them need
					     one — an optional source warehouse means nothing to a cashier
					     until it says which requests it is for — and a form-level hint
					     cannot explain one field among eight. -->
					<div v-for="field in form.fields" :key="field.fieldname" class="flex flex-col gap-1">
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
						<p v-if="field.help" class="text-p-xs leading-snug text-ink-gray-5">
							{{ field.help }}
						</p>
					</div>
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
							class="flex flex-col gap-1.5 rounded-lg border border-outline-gray-2 p-2.5"
						>
							<div class="flex flex-wrap items-end gap-2">
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

							<!-- What the shop already holds of this item, right beside the
							     quantity being asked for. Only for the types whose registry
							     entry asks for it, and only once an item is chosen — an
							     empty line has nothing to compare against. -->
							<div
								v-if="form.show_stock && line.item_code"
								class="flex flex-wrap items-center gap-2"
							>
								<span
									v-if="stockFor(line)"
									class="tabular rounded-full px-2 py-0.5 text-p-xs font-medium"
									:class="stockTone(line)"
								>
									{{ stockLabel(line) }}
								</span>
								<span v-else-if="stockLoading" class="text-p-xs text-ink-gray-5">
									Checking stock…
								</span>
								<!-- Named rather than left to be worked out from two numbers
								     under a queue: the shortfall is the reason the line is
								     on the form at all. -->
								<span
									v-if="stockFor(line)?.short"
									class="tabular text-p-xs font-medium text-ink-amber-3"
								>
									Short by {{ fmtQty(Number(line.qty || 0) - stockFor(line).available) }}
								</span>
								<span
									v-if="stockWarehouse"
									class="truncate text-p-xs text-ink-gray-5"
								>
									at {{ stockWarehouse }}
								</span>
							</div>
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

	<!-- "Add item", from the last option in any item field. A Dialog over the
	     form being filled in, so the invoice is still there underneath when this
	     closes — the whole point is not having to abandon it. -->
	<Dialog v-model="itemOpen" :options="{ title: 'Add item', size: 'sm' }">
		<template #body-content>
			<div class="flex flex-col gap-2.5">
				<FormControl v-model="itemDraft.item_name" type="text" label="Name *" @keyup.enter="saveItem" />
				<FormControl
					v-model="itemDraft.item_code"
					type="text"
					label="Code"
					placeholder="Same as the name unless you use codes"
				/>
				<LinkField
					v-model="itemDraft.item_group"
					:fetcher="itemMasterFetcher('item_group')"
					label="Group"
					required
				/>
				<LinkField v-model="itemDraft.stock_uom" :fetcher="itemMasterFetcher('stock_uom')" label="Unit" />
				<!-- Says what this does and does not do. An item created mid-purchase
				     has no selling price, and a shop that discovers that at the till
				     discovers it with a customer waiting. -->
				<p class="text-p-xs leading-snug text-ink-gray-5">
					Saved to Records and chosen for this line. Set a selling price under
					Records → Items before it can be sold at the till.
				</p>
			</div>
		</template>
		<template #actions>
			<div class="flex gap-2">
				<Button
					theme="gray"
					variant="solid"
					class="flex-1"
					:loading="itemSaving"
					:disabled="!!itemBlocker"
					:label="itemBlocker || 'Add item'"
					@click="saveItem"
				/>
				<Button variant="subtle" label="Cancel" @click="itemOpen = false" />
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
