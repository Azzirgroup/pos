import { frappeRequest } from 'frappe-ui'

/**
 * Thin wrapper over the POS endpoints.
 *
 * Kept deliberately dumb: no caching, no retry policy. The outbox that makes
 * checkout feel instant belongs in the cart flow, not here.
 */
function call(method, args) {
	return frappeRequest({
		url: `/api/method/${method}`,
		method: 'POST',
		params: args,
	})
}

/** Submit a completed sale. Resolves with {invoice, grand_total, change, …}. */
export function submitSale({ items, payment, customer }) {
	return call('cosmestics.api.pos.submit_sale', {
		items: items.map((l) => ({
			item_code: l.item_code,
			qty: l.qty,
			rate: l.rate,
			discount_pct: l.discountPct,
			sourced: l.sourced
				? {
						supplier: l.sourced.supplier,
						buy_rate: l.sourced.buyRate,
						paid: l.sourced.paidNow ? 1 : 0,
					}
				: null,
		})),
		payment,
		customer: customer || null,
	})
}

/* ---------- catalog ---------- */

/** Whole sellable catalog in one call; searched locally thereafter. */
export const getCatalog = () => call('cosmestics.api.catalog.get_catalog')

/** Tenders this till accepts, and the M-Pesa channels behind the M-Pesa button. */
export const getPaymentMethods = () => call('cosmestics.api.pos.get_payment_methods')

/** Printable receipt for a completed sale. */
export const getReceiptUrl = ({ invoice, printFormat } = {}) =>
	call('cosmestics.api.pos.receipt_url', { invoice, print_format: printFormat || null })

/* ---------- shift ---------- */

export const getProfiles = () => call('cosmestics.api.shift.get_profiles')
export const getOpenShift = () => call('cosmestics.api.shift.get_open_shift')
export const getClosingSummary = () => call('cosmestics.api.shift.get_closing_summary')

export const openShift = ({ posProfile, balances }) =>
	call('cosmestics.api.shift.open_shift', { pos_profile: posProfile, balances })

export const closeShift = ({ counted, shorts }) =>
	call('cosmestics.api.shift.close_shift', { counted, shorts: shorts || null })

/* ---------- money out of the till ---------- */

/* ---------- returns ---------- */

export const getReturnableSale = ({ invoice }) =>
	call('cosmestics.api.returns.returnable_sale', { invoice })

export const createSalesReturn = ({ invoice, lines, refundMethod, reason }) =>
	call('cosmestics.api.returns.create_sales_return', {
		invoice,
		lines: lines || null,
		refund_method: refundMethod || 'cash',
		reason: reason || null,
	})

export const listReturns = ({ days, limit } = {}) =>
	call('cosmestics.api.returns.list_returns', { days: days || 30, limit: limit || 50 })

/** Send neighbour-sourced stock back to the shop it came from. */
export const getReturnablePurchase = ({ invoice }) =>
	call('cosmestics.api.sourcing.returnable', { invoice })

export const returnToNeighbour = ({ invoice, lines, reason }) =>
	call('cosmestics.api.sourcing.return_to_neighbour', {
		invoice,
		lines: lines || null,
		reason: reason || null,
	})

/* ---------- quotations ---------- */

export const createQuotation = ({ items, customer, validDays, notes }) =>
	call('cosmestics.api.quotations.create', {
		items: items.map((l) => ({
			item_code: l.item_code,
			qty: l.qty,
			rate: l.rate,
			discount_pct: l.discountPct,
		})),
		customer: customer || null,
		valid_days: validDays || 14,
		notes: notes || null,
	})

export const listQuotations = ({ days, status, search, limit } = {}) =>
	call('cosmestics.api.quotations.list_quotations', {
		days: days || 30,
		status: status || null,
		search: search || null,
		limit: limit || 50,
	})

export const getQuotation = ({ name }) => call('cosmestics.api.quotations.get', { name })

export const getQuotationPrintUrl = ({ name, printFormat } = {}) =>
	call('cosmestics.api.quotations.print_url', { name, print_format: printFormat || null })

export const sendQuotationWhatsapp = ({ name, to, sender }) =>
	call('cosmestics.api.quotations.send_whatsapp', { name, to, sender: sender || null })

/** Stock bought from neighbouring shops, and what is still owed for it. */
export const listNeighbourPurchases = ({ days, status, limit } = {}) =>
	call('cosmestics.api.sourcing.list_purchases', {
		days: days || 30,
		status: status || null,
		limit: limit || 200,
	})

/** Shifts already closed, newest first. */
export const listRecentShifts = ({ limit, mine } = {}) =>
	call('cosmestics.api.shift.list_recent_shifts', {
		limit: limit || 10,
		mine: mine === false ? 0 : 1,
	})

/** Expense accounts, modes and neighbours the money-out form needs. */
export const getMovementOptions = () => call('cosmestics.api.shift.get_movement_options')

export const listMovements = ({ shift } = {}) =>
	call('cosmestics.api.shift.list_movements', { shift_name: shift || null })

export const recordMovement = ({
	movementType,
	amount,
	modeOfPayment,
	reason,
	person,
	party,
	expenseAccount,
}) =>
	call('cosmestics.api.shift.record_movement', {
		movement_type: movementType,
		amount,
		mode_of_payment: modeOfPayment || null,
		reason: reason || null,
		person: person || null,
		party: party || null,
		expense_account: expenseAccount || null,
	})

export const voidMovement = ({ name }) => call('cosmestics.api.shift.void_movement', { name })

/* ---------- settings ---------- */

export const getSettings = () => call('cosmestics.api.settings.get')

export const savePosSettings = (values) =>
	call('cosmestics.api.settings.save_pos_settings', { values })

export const saveProfileSettings = ({ name, values }) =>
	call('cosmestics.api.settings.save_profile', { name, values })

export const assignProfile = ({ name, assign }) =>
	call('cosmestics.api.settings.assign_profile', { name, assign: assign ? 1 : 0 })

export const saveUserSettings = (values) => call('cosmestics.api.settings.save_user', { values })

export const getSettingsLinkOptions = ({ doctype, search }) =>
	call('cosmestics.api.settings.link_options', { doctype, search: search || null })

/* ---------- sharing ---------- */

/** Share an arbitrary list row or selection as a WhatsApp message. */
export const shareOnWhatsapp = ({ to, message, sender, doctype, name, csv }) =>
	call('cosmestics.api.notifications.share', {
		to,
		message,
		sender: sender || null,
		doctype: doctype || null,
		name: name || null,
		// A shared list goes as a spreadsheet as well as text: the message is for
		// reading on a phone, the CSV is what somebody works from.
		csv_columns: csv?.columns || null,
		csv_rows: csv?.rows || null,
		filename: csv?.filename || null,
	})

export const getWhatsappGroups = () => call('cosmestics.api.notifications.list_groups')

/* ---------- customers ---------- */

export const searchCustomers = (query) =>
	call('cosmestics.api.customers.search', { query: query || '' })

export const createCustomer = ({ customerName, mobileNo }) =>
	call('cosmestics.api.customers.create', {
		customer_name: customerName,
		mobile_no: mobileNo || null,
	})

/** Raise a Material Transfer request for stock held at another store. */
export function requestTransfer({ items, fromWarehouse }) {
	return call('cosmestics.api.stock.request_transfer', {
		items: items.map((i) => ({ item_code: i.item_code, qty: i.qty })),
		from_warehouse: fromWarehouse,
	})
}

/* ---------- reorder ---------- */

export const getWarehouseTree = () => call('cosmestics.api.reorder.get_warehouse_tree')

export const getReorderItems = ({ search, onlyUnconfigured }) =>
	call('cosmestics.api.reorder.get_reorder_items', {
		search: search || null,
		only_unconfigured: onlyUnconfigured ? 1 : 0,
	})

export const getItemReorder = ({ itemCode, parentWarehouse }) =>
	call('cosmestics.api.reorder.get_item_reorder', {
		item_code: itemCode,
		parent_warehouse: parentWarehouse || null,
	})

export const getReorderRows = ({ parentWarehouse, search, onlyBelow }) =>
	call('cosmestics.api.reorder.get_reorder_rows', {
		parent_warehouse: parentWarehouse,
		search: search || null,
		only_below: onlyBelow ? 1 : 0,
	})

export const saveReorderRules = (rules) =>
	call('cosmestics.api.reorder.save_reorder_rules', { rules })

export const copyReorderLevels = ({ fromWarehouse, toWarehouses, overwrite }) =>
	call('cosmestics.api.reorder.copy_levels', {
		from_warehouse: fromWarehouse,
		to_warehouses: toWarehouses,
		overwrite: overwrite ? 1 : 0,
	})

/* ---------- back-office modules ---------- */

export const getInventory = (params = {}) => call('cosmestics.api.modules.inventory', params)
export const getWarehouses = () => call('cosmestics.api.modules.warehouses')
export const getSales = (params = {}) => call('cosmestics.api.modules.sales', params)
export const getPurchasing = (params = {}) => call('cosmestics.api.modules.purchasing', params)
export const getAccounts = (params = {}) => call('cosmestics.api.modules.accounts', params)

/* ---------- reports ---------- */

export const listReports = () => call('cosmestics.api.reports.list_reports')
export const runReport = ({ report, days, warehouse }) =>
	call('cosmestics.api.reports.run', { report, days, warehouse: warehouse || null })

/* ---------- bulk pricing ---------- */

export const getPriceListOptions = () => call('cosmestics.api.pricing.get_price_list_options')
export const getPriceFilters = () => call('cosmestics.api.pricing.get_filters')

export const getPrices = ({ priceList, search, itemGroup, brand }) =>
	call('cosmestics.api.pricing.get_prices', {
		price_list: priceList,
		search: search || null,
		item_group: itemGroup || null,
		brand: brand || null,
	})

export const previewBulkChange = ({ priceList, itemCodes, mode, value, rounding }) =>
	call('cosmestics.api.pricing.preview_bulk_change', {
		price_list: priceList,
		item_codes: itemCodes,
		mode,
		value,
		rounding,
	})

export const applyBulkChange = ({ priceList, changes }) =>
	call('cosmestics.api.pricing.apply_bulk_change', { price_list: priceList, changes })

/* ---------- transactional documents ---------- */

/**
 * One generic set of calls for every document type. `key` is a registry slug
 * ('sales-invoice', 'stock-entry'), never a raw doctype name — the server maps
 * it, so the browser can never nominate a doctype of its own.
 */
export const listDocumentTypes = () => call('cosmestics.api.documents.list_types')

export const listDocuments = ({ key, days, status, party, search, limit, start }) =>
	call('cosmestics.api.documents.list_documents', {
		key,
		days,
		status: status || null,
		party: party || null,
		search: search || null,
		limit: limit || 100,
		start: start || 0,
	})

export const getDocument = ({ key, name }) =>
	call('cosmestics.api.documents.get_document', { key, name })

export const runDocumentAction = ({ key, name, action }) =>
	call('cosmestics.api.documents.run_action', { key, name, action })

export const getPrintUrl = ({ key, name, printFormat }) =>
	call('cosmestics.api.documents.print_url', { key, name, print_format: printFormat || null })

export const sendDocumentWhatsapp = ({ key, name, to, sender, asPdf }) =>
	call('cosmestics.api.documents.send_whatsapp', {
		key,
		name,
		to: to || null,
		sender: sender || null,
		as_pdf: asPdf === false ? 0 : 1,
	})

export const getWhatsappSenders = () => call('cosmestics.api.documents.whatsapp_senders')

/* creating */

export const getDocumentForm = ({ key }) =>
	call('cosmestics.api.documents.new_document_form', { key })

export const getDocumentLinkOptions = ({ key, fieldname, search }) =>
	call('cosmestics.api.documents.link_options', { key, fieldname, search: search || null })

export const createDocument = ({ key, values, items, submit }) =>
	call('cosmestics.api.documents.create_document', {
		key,
		values,
		items,
		submit: submit ? 1 : 0,
	})

export const getDocumentInsights = ({ key, days }) =>
	call('cosmestics.api.documents.insights', { key, days })

/* ---------- barcodes ---------- */

export const listBarcodeItems = ({ search, onlyMissing, limit } = {}) =>
	call('cosmestics.api.barcodes.list_items', {
		search: search || null,
		only_missing: onlyMissing === false ? 0 : 1,
		limit: limit || 200,
	})

export const generateBarcodes = ({ itemCodes, skipExisting } = {}) =>
	call('cosmestics.api.barcodes.generate', {
		item_codes: itemCodes,
		skip_existing: skipExisting === false ? 0 : 1,
	})

/* ---------- dashboard ---------- */

export const getDashboard = ({ days } = {}) =>
	call('cosmestics.api.dashboard.overview', { days: days || 30 })

export const getDashboardFilters = () => call('cosmestics.api.dashboard.filters')

/**
 * The tabbed dashboards. All five return {stats, sections}, so one component
 * renders them all — the tab only decides which endpoint and which filter.
 */
export const getDashboardTab = ({ tab, days, branch, warehouse }) =>
	call(`cosmestics.api.dashboard.${tab}`, {
		days: days || 30,
		...(branch ? { branch } : {}),
		...(warehouse ? { warehouse } : {}),
	})

/* ---------- master data ---------- */

export const listMasterTypes = () => call('cosmestics.api.master.list_types')

export const listMasterRecords = ({ key, search, limit }) =>
	call('cosmestics.api.master.list_records', {
		key,
		search: search || null,
		limit: limit || 100,
	})

export const getMasterOptions = ({ key, fieldname, search }) =>
	call('cosmestics.api.master.options', { key, fieldname, search: search || null })

export const createMaster = ({ key, values }) =>
	call('cosmestics.api.master.create', { key, values })

export const getMasterRecord = ({ key, name }) =>
	call('cosmestics.api.master.get_record', { key, name })

export const updateMaster = ({ key, name, values }) =>
	call('cosmestics.api.master.update', { key, name, values })

/** One customer's account: billed, paid, and the running balance. */
export const getCustomerLedger = ({ customer, days } = {}) =>
	call('cosmestics.api.customers.ledger', { customer, days: days || 365 })

/* ---------- recent sales ---------- */

export const getRecentSales = ({ limit, mine, thisShift } = {}) =>
	call('cosmestics.api.pos.recent_sales', {
		limit: limit || 20,
		mine: mine === false ? 0 : 1,
		this_shift: thisShift === false ? 0 : 1,
	})

/* ---------- session ---------- */

export const getMe = () => call('cosmestics.api.session.me')

/** Which till, shop and warehouse this session is selling from. */
export const getTillContext = () => call('cosmestics.api.session.context')
