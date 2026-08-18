import { frappeRequest } from 'frappe-ui'
import { withCache } from './cache'

/**
 * Thin wrapper over the POS endpoints.
 *
 * Still no retry policy — the outbox that makes checkout feel instant belongs
 * in the cart flow, not here. It does now go through `withCache`, which
 * remembers a named list of read endpoints for a minute and serves them while
 * refetching. Everything not on that list, including every write, goes straight
 * to the server and clears what was remembered; see `cache.js` for why the list
 * is explicit and why nothing from the till is on it.
 */
/**
 * Say what the server said.
 *
 * frappe-ui builds its Error's `message` from the URL and the exception class —
 * "/api/method/…settings.save_user ValidationError" — and puts the sentence the
 * server actually wrote in `messages`. Every toast in this app shows
 * `e.message`, so a refused PIN told the cashier the name of a Python class
 * instead of "Pick a less obvious PIN", and a refused sale named the endpoint
 * rather than the reason. The two are swapped here, once, rather than at each
 * of the several dozen call sites that display an error.
 *
 * Markup is stripped because `frappe.throw` accepts HTML and a toast is text.
 */
/**
 * What the browser says when it never reached the server at all.
 *
 * "Failed to fetch" is Chrome's wording for a request that did not leave the
 * building, and on a shop tablet that means the wifi has dropped — which the
 * cashier can act on, unlike a phrase that reads as a bug in the till.
 */
const OFFLINE_PATTERNS = /failed to fetch|networkerror|network request failed|load failed/i

function readable(error) {
	if (error?.message && OFFLINE_PATTERNS.test(error.message) && !error.messages?.length) {
		error.message = navigator.onLine
			? 'Could not reach the server — it may be down, or this tablet is offline'
			: 'No internet connection on this tablet'
		error.offline = true
		return error
	}

	const said = (error?.messages || []).filter(Boolean).join(' ')
	if (said) error.message = said
	else if (error?.exc) {
		// An unhandled exception carries no server message — Frappe sends a
		// traceback instead, and the app was showing a bare "Internal Server
		// Error", which tells whoever is standing at the till nothing and gives
		// whoever they call nothing to go on either. The last line of a Python
		// traceback is the exception and its text, which is the one line worth
		// reading.
		const lines = String(error.exc).trim().split('\n').filter((l) => l.trim())
		const last = lines[lines.length - 1] || ''
		// Drop the module path: "frappe.exceptions.ValidationError: x" → "x",
		// keeping the type only when there is no message after it.
		const match = last.match(/^[\w.]*?(\w*Error|\w*Exception):\s*(.+)$/)
		if (match) error.message = match[2] || match[1]
		else if (last) error.message = last
	}
	if (error?.message) {
		error.message = String(error.message)
			.replace(/<[^>]*>/g, ' ')
			.replace(/\s+/g, ' ')
			.trim()
	}
	return error
}

function call(method, args) {
	return withCache(method, args, () =>
		frappeRequest({
			url: `/api/method/${method}`,
			method: 'POST',
			params: args,
		}).catch((e) => {
			throw readable(e)
		}),
	)
}

/** Submit a completed sale. Resolves with {invoice, grand_total, change, …}. */
export function submitSale({ items, payment, customer, discountAmount }) {
	return call('cosmestics.api.pos.submit_sale', {
		discount_amount: discountAmount || 0,
		items: items.map((l) => ({
			item_code: l.item_code,
			qty: l.qty,
			rate: l.rate,
			// The unit sold in, and how many stock units one of them is. Without
			// the factor the server would take a dozen off the shelf as one.
			uom: l.uom || null,
			conversion_factor: l.conversionFactor || 1,
			discount_pct: l.discountPct,
			sourced: l.sourced
				? {
						supplier: l.sourced.supplier,
						buy_rate: l.sourced.buyRate,
						paid: l.sourced.paidNow ? 1 : 0,
						// How many to buy, which can exceed how many are being sold —
						// the shop next door sells a carton. Defaults to the line
						// quantity on the server if absent.
						buy_qty: l.sourced.buyQty || l.qty,
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

/** Printable receipt for a completed sale, as a printview URL. */
export const getReceiptUrl = ({ invoice, printFormat } = {}) =>
	call('cosmestics.api.pos.receipt_url', { invoice, print_format: printFormat || null })

/**
 * The same receipt as finished HTML, rendered on the server.
 *
 * What the till prints. The URL above points at a desk page that assembles
 * itself in the browser, which loses a race with the hidden print frame — see
 * `pos.receipt_html`.
 */
export const getReceiptHtml = ({ invoice, printFormat } = {}) =>
	call('cosmestics.api.pos.receipt_html', { invoice, print_format: printFormat || null })

/* ---------- shift ---------- */

export const getProfiles = () => call('cosmestics.api.shift.get_profiles')
export const getOpenShift = () => call('cosmestics.api.shift.get_open_shift')
export const getClosingSummary = () => call('cosmestics.api.shift.get_closing_summary')

/** Who else may be put on a shift at this till. */
export const listCashiers = ({ posProfile }) =>
	call('cosmestics.api.shift.list_cashiers', { pos_profile: posProfile })

/**
 * `cashiers` is everyone *else* working the counter. Whoever opens the shift is
 * on it by opening it, so the till never sends their own name.
 */
export const openShift = ({ posProfile, balances, cashiers }) =>
	call('cosmestics.api.shift.open_shift', {
		pos_profile: posProfile,
		balances,
		cashiers: cashiers?.length ? cashiers : null,
	})

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

export const returnToNeighbour = ({ invoice, lines, reason, refundMethod, refundMode }) =>
	call('cosmestics.api.sourcing.return_to_neighbour', {
		invoice,
		lines: lines || null,
		reason: reason || null,
		// 'account' comes off what we owe them; 'cash' is money handed back over
		// the counter, and the mode is what picks the account it lands in.
		refund_method: refundMethod || 'account',
		refund_mode: refundMode || null,
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

export const listQuotations = ({ days, status, search, limit, todayOnly } = {}) =>
	call('cosmestics.api.quotations.list_quotations', {
		days: days || 30,
		status: status || null,
		search: search || null,
		limit: limit || 50,
		today_only: todayOnly ? 1 : 0,
	})

export const getQuotation = ({ name }) => call('cosmestics.api.quotations.get', { name })

/**
 * Change a quote that already exists, keeping its number. Used instead of
 * `createQuotation` whenever the cart was loaded from one — see `cart.sourceQuotation`.
 */
export const updateQuotation = ({ name, items, validDays, notes }) =>
	call('cosmestics.api.quotations.update', {
		name,
		items: items.map((l) => ({
			item_code: l.item_code,
			qty: l.qty,
			rate: l.rate,
			discount_pct: l.discountPct,
		})),
		valid_days: validDays || null,
		notes: notes || null,
	})

/**
 * Combine several quotes into one. The originals are closed, and the new quote
 * says which they were — see `quotations.merge`.
 */
export const mergeQuotations = ({ names, customer, validDays, notes }) =>
	call('cosmestics.api.quotations.merge', {
		names,
		// Required only when the selection spans more than one customer.
		customer: customer || null,
		valid_days: validDays || null,
		notes: notes || null,
	})

/**
 * Record that a quote became a sale, so it leaves the open list. Fills
 * `ordered_qty` so ERPNext reaches "Ordered" by its own rule — see
 * `quotations.mark_converted`.
 */
export const markQuotationConverted = ({ name, invoice }) =>
	call('cosmestics.api.quotations.mark_converted', { name, invoice })

/** Stop chasing a quote. Recorded as Lost — ERPNext's word for closed. */
export const closeQuotation = ({ name, reason }) =>
	call('cosmestics.api.quotations.close', { name, reason: reason || null })

export const getQuotationPrintUrl = ({ name, printFormat } = {}) =>
	call('cosmestics.api.quotations.print_url', { name, print_format: printFormat || null })

export const sendQuotationWhatsapp = ({ name, to, sender }) =>
	call('cosmestics.api.quotations.send_whatsapp', { name, to, sender: sender || null })

/* ---------- deliveries ---------- */

/**
 * Put a sale on a delivery run at the moment it is rung up. Joins the driver's
 * open trip for today rather than raising a parallel one — see `add_stop`.
 */
export const addDeliveryStop = ({
	invoice, driverName, destination, driverPhone, vehicle, contactPhone, trip,
}) =>
	call('cosmestics.api.deliveries.add_stop', {
		sales_invoice: invoice,
		driver_name: driverName,
		destination: destination || null,
		driver_phone: driverPhone || null,
		vehicle: vehicle || null,
		contact_phone: contactPhone || null,
		trip: trip || null,
	})

/** Runs still being loaded, so a second sale can join one. */
export const listOpenTrips = () => call('cosmestics.api.deliveries.open_trips')

/**
 * Riders the shop already uses. Searched on the server rather than filtered
 * from a pre-fetched list, so a shop with sixty riders still finds the one
 * standing at the counter.
 */
export const searchRiders = (search) =>
	call('cosmestics.cosmestics.doctype.cosmestics_rider.cosmestics_rider.search_riders', {
		search: search || null,
	})

/** Add a rider mid-sale. Returns the same shape `searchRiders` rows have. */
export const createRider = ({ riderName, phone, courier, vehicle }) =>
	call('cosmestics.cosmestics.doctype.cosmestics_rider.cosmestics_rider.create_rider', {
		rider_name: riderName,
		phone: phone || null,
		courier: courier || null,
		vehicle: vehicle || null,
	})

/**
 * Record where one order is going. Raised from the pay sheet at the moment the
 * sale is rung up — see `deliveries.create_delivery` for why that timing
 * matters.
 */
export const createDelivery = ({
	invoice,
	customer,
	rider,
	riderName,
	riderPhone,
	courier,
	vehicle,
	contactPhone,
	address,
	landmark,
	mapLocation,
	instructions,
	status,
	trip,
}) =>
	call('cosmestics.api.deliveries.create_delivery', {
		sales_invoice: invoice || null,
		customer: customer || null,
		rider: rider || null,
		rider_name: riderName || null,
		rider_phone: riderPhone || null,
		courier: courier || null,
		vehicle: vehicle || null,
		contact_phone: contactPhone || null,
		address: address || null,
		landmark: landmark || null,
		map_location: mapLocation || null,
		delivery_instructions: instructions || null,
		status: status || 'Pending',
		trip: trip || null,
	})

export const listDeliveries = ({ onDate, days, status, search, limit } = {}) =>
	call('cosmestics.api.deliveries.list_deliveries', {
		on_date: onDate || null,
		days: days || 7,
		status: status || null,
		search: search || null,
		limit: limit || 100,
	})

/**
 * Move a delivery along. Dispatching is what stamps the time and messages the
 * customer — both are the doctype's own doing, so this only says which state.
 */
export const setDeliveryStatus = ({ name, status }) =>
	call('cosmestics.api.deliveries.set_delivery_status', { name, status })

export const updateDelivery = ({ name, values }) =>
	call('cosmestics.api.deliveries.update_delivery', { name, values })

/** The slip that gets taped to the carton. */
export const getDeliveryPrintUrl = ({ name, printFormat } = {}) =>
	call('cosmestics.api.deliveries.delivery_print_url', {
		name,
		print_format: printFormat || null,
	})

/** Stock bought from neighbouring shops, and what is still owed for it. */
export const listNeighbourPurchases = ({ days, status, limit } = {}) =>
	call('cosmestics.api.sourcing.list_purchases', {
		days: days || 30,
		status: status || null,
		limit: limit || 200,
	})

/** Shifts already closed, newest first. */
export const listRecentShifts = ({ limit, mine, includeOpen } = {}) =>
	call('cosmestics.api.shift.list_recent_shifts', {
		limit: limit || 10,
		mine: mine === false ? 0 : 1,
		// Shifts still running are listed alongside the closed ones — "whose till
		// is open" is the same question as "what happened yesterday", asked now.
		include_open: includeOpen === false ? 0 : 1,
	})

/** Everything that happened on one shift — open or closed. */
export const getShiftActivity = ({ shift }) =>
	call('cosmestics.api.shift.shift_activity', { shift })

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

/* ---------- credit sales ---------- */

/** Sales still owed for. `thisShift` narrows to what this cashier put on account. */
export const listCreditSales = ({ days, thisShift, limit } = {}) =>
	call('cosmestics.api.credit.list_credit_sales', {
		days: days || 90,
		this_shift: thisShift ? 1 : 0,
		limit: limit || 200,
	})

/** Take money against a credit sale. Omit `amount` to settle it in full. */
export const payCreditSale = ({ invoice, amount, modeOfPayment, reference }) =>
	call('cosmestics.api.credit.pay_credit_sale', {
		invoice,
		amount: amount ?? null,
		mode_of_payment: modeOfPayment || null,
		reference: reference || null,
	})

/** Who owes the shop money, one row per customer rather than per invoice. */
export const listCreditCustomers = ({ days, limit } = {}) =>
	call('cosmestics.api.credit.list_credit_customers', {
		days: days || 90,
		limit: limit || 200,
	})

/** One customer's unpaid sales, oldest first — the order a payment applies in. */
export const getCustomerCredit = ({ customer, days } = {}) =>
	call('cosmestics.api.credit.customer_credit', { customer, days: days || 90 })

/**
 * Take money from a customer and let it reconcile itself against their oldest
 * invoices first. The customer is paying down what they owe, not choosing an
 * invoice — see `credit.pay_customer`.
 */
export const payCustomer = ({ customer, amount, modeOfPayment, reference }) =>
	call('cosmestics.api.credit.pay_customer', {
		customer,
		amount,
		mode_of_payment: modeOfPayment || null,
		reference: reference || null,
	})

/* ---------- settings ---------- */

export const getSettings = () => call('cosmestics.api.settings.get')

export const savePosSettings = (values) =>
	call('cosmestics.api.settings.save_pos_settings', { values })

/** Add a till. The payment methods and write-off accounts come from the company. */
export const createPosProfile = ({ profileName, values }) =>
	call('cosmestics.api.settings.create_profile', {
		profile_name: profileName,
		values: values || {},
	})

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

/** Numbers already on file for whoever a document is about. */
export const getContactNumbers = ({ doctype, name, party } = {}) =>
	call('cosmestics.api.notifications.contact_numbers', {
		doctype: doctype || null,
		name: name || null,
		party: party || null,
	})

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
		items: items.map((i) => ({
			item_code: i.item_code,
			qty: i.qty,
			// Each line can name its own branch; `fromWarehouse` below is only
			// the fallback for a caller with a single source for everything.
			from_warehouse: i.from_warehouse || i.fromWarehouse || null,
		})),
		from_warehouse: fromWarehouse || null,
	})
}

/** What a specific warehouse actually holds of each item — {item_code: qty}. */
export const getWarehouseQtys = ({ itemCodes, warehouse }) =>
	call('cosmestics.api.stock.warehouse_qtys', { item_codes: itemCodes, warehouse })

/**
 * Balances for a form that is about to ask for more — {item_code: {here,
 * total, ordered, uom}}. Unlike `getWarehouseQtys` this answers even when no
 * warehouse is chosen, which is the case a Purchase request is always in.
 */
export const getItemStock = ({ itemCodes, warehouse } = {}) =>
	call('cosmestics.api.stock.item_stock', {
		item_codes: itemCodes,
		warehouse: warehouse || null,
	})

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

/** Accounts a landed cost charge can book to. */
export const getExpenseAccounts = (search) =>
	call('cosmestics.api.documents.expense_accounts', { search: search || null })

/** Allocate freight/customs/etc. across a just-submitted receipt or invoice. */
export const createLandedCostVoucher = ({ receiptKey, receiptName, charges, vendorInvoices, distributeBasedOn }) =>
	call('cosmestics.api.documents.create_landed_cost_voucher', {
		receipt_key: receiptKey,
		receipt_name: receiptName,
		charges,
		vendor_invoices: vendorInvoices || null,
		distribute_based_on: distributeBasedOn || 'Qty',
	})

/* ---------- delivery trips ---------- */

/** Submitted sales to pick from — {name, customer, grand_total} each. */
export const searchTripInvoices = (search) =>
	call('cosmestics.api.deliveries.search_invoices', { search: search || null })

/** Raise and dispatch a trip carrying several invoices at once. */
export const createDeliveryTrip = ({ driverName, driverPhone, vehicle, departureTime, invoices }) =>
	call('cosmestics.api.deliveries.create_trip', {
		driver_name: driverName,
		driver_phone: driverPhone || null,
		vehicle: vehicle || null,
		departure_time: departureTime || null,
		invoices,
	})

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

export const getRecentSales = ({ limit, mine, thisShift, onDate } = {}) =>
	call('cosmestics.api.pos.recent_sales', {
		limit: limit || 20,
		mine: mine === false ? 0 : 1,
		this_shift: thisShift === false ? 0 : 1,
		// A specific day. Overrides the shift window on the server — the two are
		// different scopes and their intersection is usually empty.
		on_date: onDate || null,
	})

/* ---------- session ---------- */

export const getMe = () => call('cosmestics.api.session.me')

/** Which till, shop and warehouse this session is selling from. */
export const getTillContext = () => call('cosmestics.api.session.context')

/**
 * End the session.
 *
 * Frappe's own `logout`, and it must go through `call` rather than a bare
 * `fetch`: the endpoint is declared `methods=["POST"]` and validates a CSRF
 * token, so a GET is refused with a permission error the browser never shows —
 * which looks exactly like a sign-out button that does nothing.
 *
 * Being outside `CACHEABLE` also empties the read cache on the way out, so the
 * next person to sign in cannot be served the previous cashier's screens.
 */
export const logout = () => call('logout')
