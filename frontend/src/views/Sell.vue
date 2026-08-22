<script setup>
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'

import { useCatalogStore } from '@/stores/catalog'
import { useCartStore } from '@/stores/cart'
import { isUnloading } from '@/stores/cartStorage'
import { useTillStore } from '@/stores/till'
import { useBreakpoint } from '@/composables/useBreakpoint'
import { useScanner } from '@/composables/useScanner'
import { useShortcuts } from '@/composables/useShortcuts'
import { fmtMoney } from '@/utils/format'
import {
	submitSale,
	requestTransfer as apiRequestTransfer,
	getProfiles,
	getOpenShift,
	getClosingSummary,
	openShift as apiOpenShift,
	closeShift as apiCloseShift,
	getPaymentMethods,
	getReceiptUrl,
	getReceiptHtml,
	getRecentSales,
	sendDocumentWhatsapp,
	getMovementOptions,
	recordMovement as apiRecordMovement,
	voidMovement as apiVoidMovement,
	createQuotation,
	createDelivery,
	markQuotationConverted,
	updateQuotation,
	listCreditSales,
	payCreditSale,
} from '@/data/api'

import { Button, Dialog, FormControl } from 'frappe-ui'
import PillTabs from '@/components/PillTabs.vue'
import ItemGrid from '@/components/ItemGrid.vue'
import CartPanel from '@/components/CartPanel.vue'
import CartPreview from '@/components/CartPreview.vue'
import MobileCartBar from '@/components/MobileCartBar.vue'
import BottomSheet from '@/components/BottomSheet.vue'
import DateField from '@/components/DateField.vue'
import PaySheet from '@/components/PaySheet.vue'
import HeldSheet from '@/components/HeldSheet.vue'
import StockActionSheet from '@/components/StockActionSheet.vue'
import ShiftSheet from '@/components/ShiftSheet.vue'
import CustomerSheet from '@/components/CustomerSheet.vue'
import ScanSheet from '@/components/ScanSheet.vue'
import QuotationSheet from '@/components/QuotationSheet.vue'
import TillContext from '@/components/TillContext.vue'
import ReturnSheet from '@/components/ReturnSheet.vue'
import ShareSheet from '@/components/ShareSheet.vue'
import MaterialRequestSheet from '@/components/MaterialRequestSheet.vue'
import { saleMessage } from '@/utils/salesMessage'
import { printHtml, printUrl } from '@/utils/silentPrint'
import { cameraScanSupported } from '@/composables/useCameraScanner'
import LucideTriangleAlert from '~icons/lucide/triangle-alert'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideSunrise from '~icons/lucide/sunrise'
import LucideSunset from '~icons/lucide/sunset'
import LucideLayers from '~icons/lucide/layers'
import LucideScanLine from '~icons/lucide/scan-line'
import LucideUserRound from '~icons/lucide/user-round'
import LucidePrinter from '~icons/lucide/printer'
import LucideReceiptText from '~icons/lucide/receipt-text'
import LucideSend from '~icons/lucide/send'
import LucideFileText from '~icons/lucide/file-text'
import LucideUndo from '~icons/lucide/undo-2'
import LucideClipboardList from '~icons/lucide/clipboard-list'

const router = useRouter()
const catalog = useCatalogStore()
const cart = useCartStore()
const till = useTillStore()
const { isCompact } = useBreakpoint()
const { lines, count, total, isEmpty, held } = storeToRefs(cart)

const query = ref('')
const searchInput = ref(null)

/** Mode tabs from the reference layout. Menu is the till itself; the rest are
 *  the things a cashier does *between* sales, without leaving the counter.
 *
 *  Shift history is deliberately not here. It moved to the rail, because
 *  reading back over closed shifts is a back-office job done sitting down —
 *  putting it on the till strip meant a cashier one tap from navigating away
 *  from a half-rung sale. What stays are the two things done mid-sale: naming
 *  the customer, and recording money out of the drawer. */
const MODES = [
	{ label: 'Menu', value: 'menu' },
	{ label: 'Customer', value: 'customer' },
	{ label: 'Expenses', value: 'expenses' },
	{ label: 'Neighbours', value: 'neighbours' },
	// Both asked for by the shop, and both belong on this strip for the same
	// reason Expenses does: they are things done *between* sales, at the
	// counter, several times a day. Delivery sits beside Neighbours because
	// that is where the shop asked for it; Credit sits beside Delivery for the
	// same reason. The order is theirs, not ours.
	{ label: 'Delivery', value: 'delivery' },
	{ label: 'Credit', value: 'credit' },
]
const mode = ref('menu')

watch(mode, (m) => {
	if (m === 'customer') pickCustomer(false)
	// Their own pages, not tabs in the closing sheet. Both are done several
	// times a day, mid-shift, and both used to live on a screen whose main
	// action was "Close shift" — one mis-tap from ending the day of a cashier
	// who wanted to write down bus fare.
	if (m === 'expenses') router.push('/expenses')
	if (m === 'neighbours') router.push('/neighbours')
	if (m === 'delivery') router.push('/deliveries')
	// Receivables, lifted out of the closing sheet. It was reachable only by
	// opening the sheet whose main action is "Close shift", which is one
	// mis-tap from ending the day of a cashier who wanted to take a payment —
	// exactly the mistake Expenses was moved out to avoid.
	if (m === 'credit') router.push('/credit')
	// The tabs are actions, not destinations; snap back so the label never lies
	// about which view you are on.
	if (m !== 'menu') setTimeout(() => (mode.value = 'menu'), 150)
})

const cartSheet = ref(false)
/**
 * The whole cart, full width — see `CartPreview`.
 *
 * Opened from the docked panel, which is 360px wide and shows about six lines.
 * That is the right shape for the ordinary sale and useless for the trolley of
 * thirty a customer wants read back to them.
 */
const cartPreview = ref(false)
const paySheet = ref(false)
const heldSheet = ref(false)
const stockSheet = ref(false)
const stockItem = ref(null)
/** How many units short the cart is — pre-fills the sourcing form. */
const stockShortfall = ref(1)
/**
 * The total quantity actually wanted on the line, as opposed to the shortfall.
 *
 * The two agree only when nothing of the item is in the cart yet and none of
 * it is sourced — otherwise the shortfall undercounts what should end up on
 * the line. "Sell anyway" needs the real total: it sets the line to this
 * quantity rather than adding to it, so pressing `+` on an already-short line
 * moves it from 1 to 2, not from 1 to 1-plus-whatever-the-shortfall-was.
 */
const stockWantQty = ref(1)
const scanFlash = ref(0)

/* ---------- shift ---------- */

/**
 * The open shift, from the shared store rather than a local copy.
 *
 * It used to be loaded here once on mount, which was correct while the till was
 * the only place a shift could be opened. It is not any more — the Shifts page
 * opens and closes them too — and a second copy fetched at a different moment
 * is a copy that disagrees. That is the "the app is not loading the open shift"
 * symptom: open a shift elsewhere, come back, and this screen still says none.
 */
const { shift } = storeToRefs(till)
const profiles = ref([])
const shiftSheet = ref(false)
const shiftMode = ref('open')
const shiftBusy = ref(false)
const closingSummary = ref(null)
/** Expense accounts, modes and neighbours for the money-out form. */
const movementOptions = ref(null)
const movementBusy = ref(false)
/** Which tab the sheet opens on. The Expenses entry lands on 'money'. */
const shiftTab = ref('count')

/**
 * Modes to collect an opening float for.
 *
 * From the open shift once there is one, and otherwise from the till profile
 * itself — which is the same list the closing screen will ask to be counted.
 * It used to fall back to three hard-coded names, so a float counted into
 * M-Pesa Paybill had nowhere to be declared at opening and the shift closed
 * short by exactly that much, with nothing on screen explaining why.
 */
const paymentModes = computed(() => {
	if (shift.value?.balances?.length) {
		return shift.value.balances.map((b) => b.mode_of_payment)
	}
	const profileModes = profiles.value?.[0]?.modes
	return profileModes?.length ? profileModes : ['Cash', 'M-Pesa', 'Credit Card']
})

/* ---------- customer ---------- */

const customer = ref(null)
const customerSheet = ref(false)
const customerRequired = ref(false)

/**
 * The last posted sale, kept only so the cashier can print its receipt.
 *
 * Held after the cart is cleared on purpose: the receipt is wanted *after* the
 * sale is done, and by then there is nothing left on screen to print from.
 */
const lastSale = ref(null)

/** Every tender this till accepts, and the M-Pesa channels within it. Both come
 *  from the server; the pay sheet falls back to a built-in list if absent. */
const mpesaChannels = ref([])
const paymentMethods = ref([])

onMounted(async () => {
	catalog.load()
	recoverInterruptedSale()

	// All three at once. They were two awaits in sequence, which cost the till an
	// extra round trip on every open for no reason — none of them depends on
	// another. `allSettled` keeps the independence that the sequence had: a
	// failed payment-methods lookup must not cost us the shift, and neither must
	// stop the catalogue.
	const [shiftResult, profilesResult, methodsResult] = await Promise.allSettled([
		// The shift comes from the store, so it is the same one the header and
		// the Shifts page are looking at.
		till.refreshShift(),
		getProfiles(),
		getPaymentMethods(),
	])

	if (shiftResult.status === 'rejected') {
		// Whether a failed lookup stops the *sale* is the shop's decision, and it
		// is enforced on the server rather than here.
		console.warn('[pos] shift lookup failed', shiftResult.reason)
	}

	profiles.value = profilesResult.status === 'fulfilled' ? profilesResult.value || [] : []

	if (methodsResult.status === 'fulfilled') {
		const methods = methodsResult.value
		if (methods?.methods?.length) paymentMethods.value = methods.methods
		if (methods?.mpesa_channels?.length) mpesaChannels.value = methods.mpesa_channels
	} else {
		console.warn('[pos] payment methods lookup failed', methodsResult.reason)
	}

	// Again once the session is known. Until `till.refresh` returns, the cart is
	// stored under an anonymous key, so a basket stashed under the real one is
	// not visible on the first pass. Clearing the stash makes this idempotent.
	recoverInterruptedSale()
})

/**
 * A sale the till was posting when it stopped — a reload, a crash, a tablet
 * that reclaimed the tab. The basket comes back as a held ticket, never as a
 * live cart: nobody knows whether that invoice reached the server, so settling
 * it has to be a deliberate act. See `cart.recoverPending`.
 *
 * Announced from a watcher rather than at the call site, because the stash can
 * be found either here or later by `adoptSession`, and the cashier has to be
 * told either way.
 */
function recoverInterruptedSale() {
	cart.recoverPending()
}

watch(
	() => cart.recovered,
	(found) => {
		if (!found) return
		notify(
			`A sale was interrupted — basket kept as ${found.ticket.id}. Check Recent sales before charging it again.`,
			'warn',
		)
		cart.recovered = null
	},
	{ immediate: true },
)

/**
 * The receipt prompt after a sale.
 *
 * Optional, and remembered. A shop that prints every receipt wants one tap; a
 * shop that prints none does not want a dialog in the way of the next customer.
 * The preference is per browser rather than per user, because it is a property
 * of the counter — whether there is a printer attached to *this* till.
 *
 * It never blocks: the sale is already posted and the cart already cleared by
 * the time this opens, so dismissing it loses nothing, and the toolbar keeps a
 * Receipt button for anyone who changes their mind.
 */
const PRINT_PREF = 'cosmestics:askPrint'
const askToPrint = ref(localStorage.getItem(PRINT_PREF) !== 'never')
const printPrompt = ref(false)

function setAskToPrint(on) {
	askToPrint.value = on
	localStorage.setItem(PRINT_PREF, on ? 'always' : 'never')
}

async function printFromPrompt() {
	printPrompt.value = false
	await printReceipt()
}

/* ---------- send the receipt on WhatsApp ---------- */

/**
 * The same receipt, to the customer's phone.
 *
 * Goes through `documents.send_whatsapp`, which attaches the real PDF rendered
 * from the invoice's print format — so what the customer receives is the
 * receipt, not a summary of it, and it matches what the printer would produce.
 *
 * The number is pre-filled from the customer when there was one, and editable
 * always: a walk-in has no record to read a number off, and the one on file is
 * often a landline.
 */
const whatsappOpen = ref(false)
const whatsappTo = ref('')
const whatsappSending = ref(false)

function openWhatsapp() {
	whatsappTo.value = lastSale.value?.phone || ''
	whatsappOpen.value = true
}

async function sendReceiptWhatsapp() {
	if (!lastSale.value || !whatsappTo.value) return
	whatsappSending.value = true
	try {
		const res = await sendDocumentWhatsapp({
			key: 'sales-invoice',
			name: lastSale.value.invoice,
			to: whatsappTo.value,
			asPdf: true,
		})
		notify(res.message, res.sent ? 'ok' : 'warn')
		if (res.sent) {
			whatsappOpen.value = false
			printPrompt.value = false
		}
	} catch (e) {
		notify(e.message || 'Could not send the receipt', 'warn')
	} finally {
		whatsappSending.value = false
	}
}

/**
 * Send one recent sale to WhatsApp — a number, or the shop's own group.
 *
 * Goes through `ShareSheet`, the same control every other list uses, rather
 * than the bespoke box in the post-sale prompt: that one only ever knew about
 * the sale just rung up, and "send me yesterday's receipt" is asked at the
 * counter as often as "print it again".
 *
 * The message is composed here and shown before it goes, carrying the fields a
 * shop reconciles its group chat against — see `utils/salesMessage`.
 */
const shareOpen = ref(false)
const sharePayload = ref(null)

function shareSale(row) {
	sharePayload.value = {
		title: `Send ${row.name}`,
		message: saleMessage(row, { shift: recent.value?.shift }),
		doctype: 'Sales Invoice',
		name: row.name,
	}
	shareOpen.value = true
}

async function printReceipt(invoice) {
	const target = invoice || lastSale.value?.invoice
	if (!target) return
	// Straight to the till printer — no tab, no preview. See `utils/silentPrint`.
	//
	// The receipt is fetched as finished HTML rather than as a `/printview`
	// address. That address is a desk page which assembles the printout in the
	// browser, and inside the hidden print frame it loses a race with its own
	// load event: the dialog opens on a page with nothing on it yet, or the
	// frame is gone before it opens at all. From the counter that is a Print
	// button that does nothing, which is what was reported for Recent sales.
	//
	// Said out loud while it fetches, because the gap between the tap and the
	// dialog is a second of nothing on a shop's connection, and a cashier who
	// gets no acknowledgement presses again.
	notify('Preparing the receipt…')
	try {
		const { html } = await getReceiptHtml({ invoice: target })
		printHtml(html, () => notify('Could not reach the printer', 'warn'))
		return
	} catch (e) {
		// Older sites, or a print format the server could not render: fall back
		// to the printview rather than leaving the cashier with no receipt.
		console.warn('[pos] receipt html failed, falling back to printview', e)
	}

	try {
		const { url } = await getReceiptUrl({ invoice: target })
		printUrl(url, () => notify('Could not reach the printer', 'warn'))
	} catch (e) {
		notify(e.message || 'Could not open the receipt', 'warn')
	}
}

/* ---------- recent sales ---------- */

/**
 * "Did that one go through?" is asked at a counter several times a day, and
 * until now the only way to answer it was to leave the till for the back
 * office. Defaults to this cashier's own sales — the question is almost always
 * about the sale just rung up, and everyone else's invoices bury it.
 */
const recentSheet = ref(false)
const recent = ref({ rows: [], totals: {} })
const recentLoading = ref(false)
const recentMine = ref(true)
/** Scoped to the open shift by default — see `pos.recent_sales`. */
const recentThisShift = ref(true)

async function openRecent() {
	recentSheet.value = true
	await loadRecent()
}

async function loadRecent() {
	recentLoading.value = true
	try {
		recent.value = await getRecentSales({
			limit: 25,
			mine: recentMine.value,
			// A day and a shift are different scopes; the server ignores the shift
			// when a date is given rather than returning the intersection, which is
			// usually nothing.
			thisShift: recentDate.value ? false : recentThisShift.value,
			onDate: recentDate.value || null,
		})
	} catch (e) {
		notify(e.message || 'Could not load recent sales', 'warn')
		recent.value = { rows: [], totals: {} }
	} finally {
		recentLoading.value = false
	}
}

/**
 * A specific day, for "what did we sell on Tuesday".
 *
 * Empty means the default scope — this shift, or everything when none is open.
 * Picking a date turns the shift filter off rather than combining with it, and
 * the control below says so instead of leaving the cashier to work out why an
 * old date returned nothing.
 */
/**
 * Today's sales, unless a date is picked.
 *
 * Pre-filled rather than blank: "did that go through?" is asked about something
 * rung up minutes ago, and a list starting at last month buries it. A cashier
 * who wants an older day still picks one.
 */
const recentDate = ref(new Date().toISOString().slice(0, 10))

watch([recentMine, recentThisShift, recentDate], () => {
	if (recentSheet.value) loadRecent()
})

const SHIFT_TABS = ['count', 'credit']

async function openShiftSheet(initialTab = 'count') {
	// Guarded because a bare `@click="openShiftSheet"` hands this the click
	// event, and the sheet then opened on a tab that does not exist — rendering
	// no panel at all, which reads as "Close shift is broken".
	shiftTab.value = SHIFT_TABS.includes(initialTab) ? initialTab : 'count'

	if (shift.value) {
		shiftMode.value = 'close'
		closingSummary.value = null
		shiftSheet.value = true
		await Promise.all([reloadClosingSummary(), loadMovementOptions(), loadCreditSales()])
		return
	}
	shiftMode.value = 'open'
	shiftSheet.value = true
}


async function reloadClosingSummary() {
	try {
		closingSummary.value = await getClosingSummary()
	} catch (e) {
		console.error('[pos] closing summary failed', e)
		notify('Could not load shift totals', 'warn')
	}
}

/** Fetched once per sheet opening — the account list does not change mid-shift. */
async function loadMovementOptions() {
	try {
		movementOptions.value = await getMovementOptions()
	} catch (e) {
		// The count still works without them; only the money-out form degrades.
		console.warn('[pos] movement options failed', e)
	}
}

/**
 * Money out of the drawer, mid-shift.
 *
 * The summary is reloaded rather than patched locally: the expected amounts are
 * the server's arithmetic, and a cashier counting against a figure this screen
 * worked out for itself is exactly the disagreement the whole flow exists to
 * prevent.
 */
async function doRecordMovement(payload) {
	movementBusy.value = true
	try {
		const res = await apiRecordMovement(payload)
		await reloadClosingSummary()
		notify(
			`${fmtMoney(res.amount)} out of ${res.mode_of_payment}` +
				(res.reference_name ? ` · ${res.reference_name}` : ''),
			'ok',
		)
	} catch (e) {
		notify(e.message || 'Could not record that', 'warn')
	} finally {
		movementBusy.value = false
	}
}

/* ---------- credit sales ---------- */

/**
 * What the shop is still owed, and taking it when the customer walks back in.
 *
 * Loaded with the shift sheet rather than at start-up: it is a list a cashier
 * consults, not one they act on every sale, and on a shop that sells on account
 * it is long enough that fetching it on every till open would be a waste.
 */
const creditSales = ref(null)
const creditBusy = ref(false)

async function loadCreditSales() {
	try {
		creditSales.value = await listCreditSales({})
	} catch (e) {
		creditSales.value = { rows: [], totals: {}, reason: e.message || 'Could not load credit sales' }
	}
}

async function doPayCredit({ invoice, amount }) {
	creditBusy.value = true
	try {
		const res = await payCreditSale({ invoice, amount })
		// Both, because the payment changed both: the invoice is settled or part
		// paid, and the drawer is expected to hold that much more.
		await Promise.all([loadCreditSales(), reloadClosingSummary()])
		notify(
			res.settled
				? `${fmtMoney(res.paid)} received · ${invoice} settled`
				: `${fmtMoney(res.paid)} received · ${fmtMoney(res.outstanding)} still owed`,
			'ok',
		)
	} catch (e) {
		notify(e.message || 'Could not take that payment', 'warn')
	} finally {
		creditBusy.value = false
	}
}

async function doVoidMovement(movement) {
	movementBusy.value = true
	try {
		await apiVoidMovement({ name: movement.name })
		await reloadClosingSummary()
		notify(`${fmtMoney(movement.amount)} put back`, 'ok')
	} catch (e) {
		notify(e.message || 'Could not void that', 'warn')
	} finally {
		movementBusy.value = false
	}
}

async function doOpenShift(payload) {
	shiftBusy.value = true
	try {
		await apiOpenShift(payload)
		shiftSheet.value = false
		// One refresh updates every screen reading the store — this one, the
		// header chip, and the Shifts page. Assigning a local copy instead is
		// what let them drift apart.
		await till.refresh()
		notify('Shift opened', 'ok')
	} catch (e) {
		notify(e.message || 'Could not open shift', 'warn')
	} finally {
		shiftBusy.value = false
	}
}

async function doCloseShift(payload) {
	shiftBusy.value = true
	try {
		const res = await apiCloseShift(payload)
		shiftSheet.value = false
		closingSummary.value = null
		await till.refresh()
		// Naming who a shortfall is against is the point of recording it, so the
		// confirmation says so rather than reporting an anonymous number.
		const named = (res.shorts_recorded || []).map((s) => s.person).join(', ')
		notify(
			res.difference === 0
				? `Shift closed — balanced (${res.name})`
				: `Shift closed — ${res.difference > 0 ? 'over' : 'short'} ${fmtMoney(Math.abs(res.difference))}` +
					(named ? ` · against ${named}` : ''),
			res.difference === 0 ? 'ok' : 'warn',
		)
	} catch (e) {
		notify(e.message || 'Could not close shift', 'warn')
	} finally {
		shiftBusy.value = false
	}
}

function pickCustomer(required = false) {
	customerRequired.value = required
	customerSheet.value = true
}

/** Re-read prices and stock. Cheap enough to offer as a manual shortcut, since
 *  another till selling the same stock is the normal case in a busy shop. */
async function refreshCatalog() {
	if (catalog.loading) return
	await catalog.refresh()
	notify(catalog.isDemo ? 'Still showing demo items' : 'Prices and stock refreshed', catalog.isDemo ? 'warn' : 'ok')
}

function onCustomerSelected(c) {
	customer.value = c
	cart.customer = c ? c.customer_name || c.name : null
}

const visibleItems = computed(() => catalog.search(query.value))

/** item_code → qty, so ItemCard can show its pip without scanning the cart. */
/**
 * How much of each item the cart holds, **in stock units**.
 *
 * Not in the unit it was rung up in: a line of one dozen takes twelve off the
 * shelf, and the shelf is what the stock check compares against. Counting the
 * line as "1" would let a cashier sell twelve of the last three without the
 * app ever offering to source them.
 */
const cartQtys = computed(() => {
	const m = {}
	for (const l of lines.value) {
		m[l.item_code] = (m[l.item_code] || 0) + l.qty * (l.conversionFactor || 1)
	}
	return m
})

/* ---------- toast ---------- */

const toastMsg = ref('')
const toastTone = ref('info')
let toastTimer = null

function notify(message, tone = 'info') {
	toastMsg.value = message
	toastTone.value = tone
	clearTimeout(toastTimer)
	toastTimer = setTimeout(() => (toastMsg.value = ''), 2200)
}

/* ---------- actions ---------- */

/**
 * Running out mid-cart is the same decision as being out at the start.
 *
 * The shelf count is checked against what the cart *would* hold, not against
 * what it holds now: two of the last one is the moment to offer the shop next
 * door, and finding out at checkout — when the invoice fails on negative stock
 * and the customer is already paying — is far too late. Lines already sourced
 * from a neighbour are excluded from the tally, since they are not coming off
 * this shelf.
 *
 * Returns true when the sheet was opened, so callers can leave the cart alone.
 */
function promptIfShort(item, wantQty) {
	// Already agreed once for this line — a `+` on a cart line that is
	// deliberately selling past the shelf count is a quantity change, not a
	// new decision, and re-opening the sheet on every tap was the bug.
	if (lines.value.some((l) => l.item_code === item.item_code && l.negativeStockOk)) {
		return false
	}

	const stock = Number(item.stock) || 0
	const sourcedQty = lines.value
		.filter((l) => l.item_code === item.item_code && l.sourced)
		.reduce((n, l) => n + l.qty * (l.conversionFactor || 1), 0)

	if (wantQty - sourcedQty <= stock) return false

	stockItem.value = item
	// Pre-filled with the gap rather than 1: the cashier is short by a specific
	// number and should not have to work it out under a queue.
	stockShortfall.value = Math.max(1, Math.ceil(wantQty - sourcedQty - stock))
	stockWantQty.value = Math.max(1, Math.ceil(wantQty))
	stockSheet.value = true
	return true
}

function addItem(item) {
	// Out of stock is a decision point, not an error. The cashier chooses:
	// buy it from next door, request it from another store, or sell anyway
	// because it is physically on the shelf but not yet received.
	const inCart = cartQtys.value[item.item_code] || 0
	// One of the item's default unit, which is the stock unit — a dozen is
	// chosen on the cart line, not by tapping the grid.
	if (promptIfShort(item, inCart + 1)) return
	cart.add(item, 1)
}

/** Quantity controls live on the cell itself in the dense layout, so the grid
 *  needs to be able to change the cart, not only append to it. */
function setItemQty({ item, qty }) {
	const line = lines.value.find((l) => l.item_code === item.item_code)
	if (!line) {
		if (qty <= 0) return
		if (promptIfShort(item, qty)) return
		return cart.add(item, qty)
	}
	if (qty <= 0) return cart.remove(line.id)
	if (qty > line.qty && promptIfShort(item, qty)) return
	cart.setQty(line.id, qty)
}

function removeItem(item) {
	const line = lines.value.find((l) => l.item_code === item.item_code)
	if (line) cart.remove(line.id)
}

/**
 * The same check from the cart side.
 *
 * The cart panel used to change the store directly, which meant the one place a
 * quantity is most often nudged past the shelf count — the `+` next to a line —
 * was the one place that never asked. It emits upward now so the decision lives
 * where the sheet does.
 */
function cartInc(id, step = 1) {
	const line = lines.value.find((l) => l.id === id)
	if (!line) return
	// A line already bought from a neighbour has no shelf to run out of.
	if (!line.sourced) {
		const item = catalog.byCode.get(line.item_code)
		const inCart = cartQtys.value[line.item_code] || 0
		if (item && promptIfShort(item, inCart + step)) return
	}
	cart.inc(id, step)
}

function cartSetQty(id, qty) {
	const line = lines.value.find((l) => l.id === id)
	if (!line) return
	if (qty > line.qty && !line.sourced) {
		const item = catalog.byCode.get(line.item_code)
		const inCart = (cartQtys.value[line.item_code] || 0) - line.qty + qty
		if (item && promptIfShort(item, inCart)) return
	}
	cart.setQty(id, qty)
}

function sellAnyway({ item }) {
	// Ignores the sheet's own `qty` — that field carries the shelf shortfall,
	// which is only the right number to *add* when the cart holds none of the
	// item yet. Once some is already on the line, `cart.add` would stack the
	// shortfall on top of it instead of reaching the total actually wanted —
	// see `stockWantQty`.
	const line = lines.value.find((l) => l.item_code === item.item_code && !l.sourced)
	if (line) {
		cart.setQty(line.id, stockWantQty.value)
		// Marks the line so future `+` taps skip the sheet — see `promptIfShort`.
		line.negativeStockOk = true
	} else {
		cart.add(item, stockWantQty.value, { negativeStockOk: true })
	}
	notify(`${item.item_name} added — stock will go negative`, 'warn')
}

function sourceFromNeighbour({ item, qty, buyQty, supplier, buyRate, paidNow }) {
	const buying = Math.max(Number(buyQty) || qty, qty)
	cart.add(item, qty, { sourced: { supplier, buyRate, paidNow: !!paidNow, buyQty: buying } })

	const kept = buying - qty
	notify(
		`Sourcing ${buying} × ${item.item_name} from ${supplier}` +
			(kept > 0 ? `, selling ${qty} · ${kept} to stock` : '') +
			(paidNow ? ` · ${fmtMoney(buying * buyRate)} out of the drawer` : ''),
		'ok',
	)
}

async function requestTransfer({ items, warehouse }) {
	try {
		const res = await apiRequestTransfer({
			items,
			fromWarehouse: warehouse,
		})
		// It used to say "sent to WhatsApp" unconditionally, which the app had no
		// basis for: the message is queued after submit, and on a site where
		// WhatsApp is not configured it never goes anywhere. Now it reports what
		// is actually known — that it was queued, or that nobody will see it.
		notify(
			res.whatsapp?.usable
				? `${res.name} raised — posting to the staff group`
				: `${res.name} raised, but nobody was notified: ${res.whatsapp?.reason || 'WhatsApp is not set up'}`,
			res.whatsapp?.usable ? 'ok' : 'warn',
		)
	} catch (e) {
		console.error('[pos] material request failed', e)
		notify(`Request failed: ${e.message || 'server error'}`, 'warn')
	}
}

/* ---------- scanning ---------- */

/**
 * A scan proposes an item; the cashier confirms the quantity.
 *
 * It used to add straight to the cart, which was wrong twice over. A camera
 * holds a barcode in frame for as long as the phone is pointed at it and reads
 * it many times a second, so one product landed in the cart repeatedly with
 * nobody touching anything. And even with a handheld scanner, a quantity of one
 * is a guess — six of the same lipstick is one scan and a number, not six scans.
 *
 * So the read opens a confirmation with the quantity focused: Enter accepts,
 * Escape discards. One extra keypress per scan, and the cart stops filling
 * itself.
 */
const scanned = ref(null)
const scanQty = ref('1')
const scanQtyInput = ref(null)
/** Set when the item on screen has just been scanned again. */
const scanRepeat = ref(false)

/** How many of the scanned item are already in the cart, if any. */
const scannedInCart = computed(() =>
	scanned.value ? cartQtys.value[scanned.value.item_code] || 0 : 0,
)

/** The last code accepted, so a camera re-reading it does not reopen the sheet. */
let lastCode = ''
let lastCodeAt = 0
const REPEAT_WINDOW_MS = 2000

async function onScan(code) {
	const now = performance.now()
	// A camera fires the same code continuously while it is in frame.
	if (code === lastCode && now - lastCodeAt < REPEAT_WINDOW_MS) return
	lastCode = code
	lastCodeAt = now

	const item = catalog.findByBarcode(code)
	if (!item) {
		// Unknown barcode: drop it into search so the cashier can find it by name
		// rather than being left with a dead end.
		query.value = code
		scanResult.value = { ok: false, message: `No item with barcode ${code}` }
		notify(`No item with barcode ${code}`, 'warn')
		return
	}

	scanFlash.value++
	scanResult.value = { ok: true, message: `${item.item_name} · ${fmtMoney(item.price)}` }

	// Scanning the same item again does NOT count up.
	//
	// It used to, on the theory that repeatedly scanning a pile of identical
	// products means "one more each time". In practice a scanner fires twice off
	// one trigger pull often enough that the quantity was silently wrong, and a
	// number that changes by itself is one nobody checks. So the read is
	// acknowledged and the quantity is left exactly where the cashier put it —
	// they say how many, and the field is reselected so typing it is one action.
	if (scanned.value?.item_code === item.item_code) {
		scanRepeat.value = true
		await nextTick()
		scanQtyInput.value?.select?.()
		return
	}

	scanned.value = item
	scanRepeat.value = false
	scanQty.value = '1'
	await nextTick()
	scanQtyInput.value?.select?.()
}

function confirmScan() {
	const item = scanned.value
	const qty = Number(scanQty.value)
	if (!item || !(qty > 0)) return

	// The stock check applies to a scan as much as to a tap: scanning six of
	// something with two on the shelf is the same decision as typing it.
	const inCart = cartQtys.value[item.item_code] || 0
	if (promptIfShort(item, inCart + qty)) {
		scanned.value = null
		scanRepeat.value = false
		lastCode = ''
		return
	}

	cart.add(item, qty)
	notify(`${qty} × ${item.item_name}`, 'ok')
	scanned.value = null
	scanRepeat.value = false
	// Cleared so the same product can be scanned again straight away as a
	// separate line decision.
	lastCode = ''
}

function cancelScan() {
	scanned.value = null
	scanRepeat.value = false
	lastCode = ''
}

/* ---------- camera scanning ---------- */

const scanSheet = ref(false)
const scanResult = ref(null)
// Only offered where the browser can actually do it (Chrome on Android today).
// A dead button is worse than no button at a busy counter.
const cameraScanAvailable = cameraScanSupported()

let scanResultTimer = null
watch(scanResult, () => {
	clearTimeout(scanResultTimer)
	scanResultTimer = setTimeout(() => (scanResult.value = null), 2000)
})

function onCameraScan(code) {
	onScan(code)
}

/**
 * A misread is not an unknown product.
 *
 * A truncated or corrupted read used to fall through to "No item with barcode
 * 6291", which sends the cashier looking for something that was never on the
 * shelf. Saying the scan itself failed tells them to do the one thing that
 * fixes it.
 */
useScanner(onScan, {
	onMisread: (code, reason) => {
		scanResult.value = { ok: false, message: 'Bad scan — try again' }
		notify(
			reason === 'checksum'
				? `That scan came through wrong (${code}) — scan it again`
				: 'That scan came through incomplete — scan it again',
			'warn',
		)
	},
})

/**
 * Whether this shop refuses to sell without an open shift.
 *
 * The server is what enforces it — this only avoids walking the cashier through
 * a whole payment sheet to be refused at the end, with a customer waiting.
 */
const requiresShift = computed(() => Boolean(till.context?.requires_shift))
const blockedByShift = computed(() => requiresShift.value && !shift.value)

function openPay() {
	if (isEmpty.value) return
	if (blockedByShift.value) {
		notify('Open a shift before selling — count the drawer first', 'warn')
		openShiftSheet()
		return
	}
	cartSheet.value = false
	paySheet.value = true
}

/**
 * Park the sale — or bring the last one back.
 *
 * One button, because the mistake it undoes happens at the counter with a
 * customer waiting: a cashier who taps hold by accident is looking at an empty
 * cart, and the recovery has to be the control they just pressed rather than a
 * list of tickets they have to go and find. With items in the cart it holds, as
 * it always did; with none, it resumes the most recent ticket.
 */
function holdSale() {
	if (cart.isEmpty && cart.held.length) {
		const ticket = cart.held[cart.held.length - 1]
		cart.resume(ticket.id)
		notify(`Sale ${ticket.id} is back in the cart`, 'ok')
		return
	}

	const ticket = cart.hold()
	if (ticket) {
		cartSheet.value = false
		notify(`Sale ${ticket.id} held — tap again to undo`, 'ok')
	}
}

/* ---------- returns ---------- */

/**
 * Taking goods back, started from the sale they came from.
 *
 * Reached through Recent sales because that is where a customer with a receipt
 * lands: the cashier finds the sale, then decides what is coming back. A blank
 * return form would let somebody be refunded for something they never bought.
 */
const returnSheet = ref(false)
const returnInvoice = ref('')

function openReturn(row) {
	returnInvoice.value = row.name
	returnSheet.value = true
}

function onReturned(res) {
	notify(
		res.method === 'cash'
			? `${fmtMoney(res.refunded)} refunded in cash · ${res.name}`
			: `${fmtMoney(res.refunded)} credited to the account · ${res.name}`,
		'ok',
	)
	// Stock came back and, for a cash refund, the drawer changed — both are
	// stale on screen now.
	catalog.refresh()
	loadRecent()
}

/* ---------- quotations ---------- */

/**
 * A price given now, honoured when the customer comes back.
 *
 * Held tickets solved the wrong half of this: they live in the browser and die
 * with the tab, so "how much for all this?" had no answer that survived the
 * customer walking out. A Quotation is ERPNext's document for it — it prints, it
 * carries a validity date, and the back office already knows what one is.
 */
/**
 * Requests, in a sheet rather than a screen.
 *
 * It used to route to the Documents list, which meant leaving the till — and a
 * cashier mid-basket does not want the counter to disappear. Same treatment as
 * Quotes: a sheet over the till, with the list, a way to raise one, and the
 * button that turns one into a cart.
 */
const materialSheet = ref(false)

const quotationSheet = ref(false)
const quotationBusy = ref(false)

/** Fold several parked sales into one ticket — see `cart.mergeHeld`. */
function mergeHeldTickets(ids) {
	const ticket = cart.mergeHeld(ids)
	if (ticket) notify(`Merged into ${ticket.id} · ${fmtMoney(ticket.total)}`, 'ok')
}

async function saveQuotation({ validDays, notes, asNew }) {
	if (isEmpty.value) return
	quotationBusy.value = true
	// Editing a quote loaded into the cart updates that quote rather than
	// raising a second one with a different number — unless the cashier
	// deliberately asked for a new document.
	const editing = !asNew && cart.sourceQuotation
	try {
		const res = editing
			? await updateQuotation({ name: editing, items: lines.value, validDays, notes })
			: await createQuotation({
					items: lines.value,
					customer: customer.value?.name || null,
					validDays,
					notes,
				})
		quotationSheet.value = false
		// The cart has become the quotation, so it stops being a sale in progress.
		// Leaving it loaded meant the next customer's items were rung up on top of
		// somebody else's quoted basket — and the cashier, having just been told
		// the quote saved, had no reason to look.
		cart.clear()
		notify(
			`${res.updated ? 'Updated' : 'Quoted'} ${fmtMoney(res.grand_total)} — ${res.name}, valid to ${res.valid_till}`,
			'ok',
		)
	} catch (e) {
		notify(e.message || 'Could not save the quotation', 'warn')
	} finally {
		quotationBusy.value = false
	}
}

/**
 * Load a quote into the cart, at the prices it was quoted at.
 *
 * Replaces the cart rather than appending: a quote is a whole basket somebody
 * was given a total for, and mixing it into a half-rung sale produces a number
 * that matches neither. The current cart is held first when there is one, so
 * nothing is destroyed by loading a quote onto it by mistake.
 */
function loadQuotation(quote) {
	if (!isEmpty.value) {
		const ticket = cart.hold()
		if (ticket) notify(`Current sale held as ${ticket.id}`, 'ok')
	}

	cart.clear()
	for (const line of quote.items) {
		const item = catalog.byCode.get(line.item_code) || {
			item_code: line.item_code,
			item_name: line.item_name,
			price: line.rate,
			uom: line.uom,
			stock: 0,
		}
		const added = cart.add({ ...item, price: line.rate }, line.qty)
		// The quoted rate wins over today's price list — that is the promise the
		// quote made, and re-pricing here would make it a suggestion.
		if (added) cart.setRate(added.id, line.rate)
	}

	if (quote.customer_id) {
		customer.value = { name: quote.customer_id, customer_name: quote.customer }
		cart.customer = quote.customer
	}

	// Saving after an edit now updates this quote instead of raising another.
	cart.sourceQuotation = quote.name

	quotationSheet.value = false

	// Said out loud rather than dropped: a quote whose lines quietly vanish is
	// worse than one that names the line it cannot honour.
	if (quote.unavailable?.length) {
		notify(
			`${quote.name} loaded — ${quote.unavailable.length} line${quote.unavailable.length === 1 ? '' : 's'} no longer sellable and left out`,
			'warn',
		)
	} else if (quote.expired) {
		notify(`${quote.name} loaded — note it expired on ${quote.valid_till}`, 'warn')
	} else {
		notify(`${quote.name} loaded at quoted prices`, 'ok')
	}
}

function resumeHeld(id) {
	cart.resume(id)
	heldSheet.value = false
	notify('Sale resumed', 'ok')
}

async function completeSale(payment) {
	// Snapshot before clearing — the cart is emptied immediately so the next
	// customer can be served while the invoice posts in the background.
	const snapshot = {
		items: lines.value.map((l) => ({ ...l })),
		customer: customer.value?.name || null,
		// Clamped to the subtotal — `cart.discount` is the raw typed value,
		// `discountAmount` is what actually applies and what was charged.
		discountAmount: cart.discountAmount,
	}
	// The same basket in the shape the cart takes back, kept separately because
	// the payload above is the server's shape and drops what a re-ring needs.
	const basket = {
		lines: lines.value.map((l) => ({ ...l })),
		customer: customer.value,
		discount: cart.discount,
		sourceQuotation: cart.sourceQuotation,
		sourceTicket: cart.sourceTicket,
	}
	// Durable from here until the server answers: the cart is about to be
	// emptied and this becomes the only copy. See `cartStorage.savePending`.
	cart.submitStarted(basket)
	const paid = total.value
	const wasCredit = payment.method === 'credit'
	const customerName = customer.value?.customer_name || customer.value?.name
	// Captured before the cart clears: by the time the receipt prompt opens there
	// is no customer on screen to read a number off.
	const customerPhone = customer.value?.mobile_no || customer.value?.phone || ''
	// The quote this cart came from, captured before `cart.clear()` forgets it.
	const fromQuotation = cart.sourceQuotation

	cart.clear()
	customer.value = null
	paySheet.value = false
	notify(
		wasCredit
			? `${fmtMoney(paid)} on credit to ${customerName}`
			: payment.outstanding > 0
				? `Part-paid · ${fmtMoney(payment.outstanding)} owed by ${customerName}`
				: payment.change > 0
					? `Paid ${fmtMoney(paid)} · change ${fmtMoney(payment.change)}`
					: `Paid ${fmtMoney(paid)}`,
		'ok',
	)

	try {
		const res = await submitSale({
			items: snapshot.items,
			customer: snapshot.customer,
			discountAmount: snapshot.discountAmount,
			payment: {
				method: payment.method,
				// Present only for split tender; the backend treats it as the
				// authoritative breakdown when it is.
				parts: payment.parts || null,
				tendered: payment.tendered,
				change: payment.change,
				reference: payment.reference,
			},
		})
		// Posted. The basket is now the invoice's problem, not ours.
		cart.submitSettled()
		lastSale.value = {
			invoice: res.invoice,
			customer: customerName,
			phone: customerPhone,
			total: paid,
			change: payment.change || 0,
			outstanding: res.outstanding || 0,
			at: Date.now(),
		}
		// The quote has become a sale, so it stops being an outstanding promise.
		// After the invoice exists — that is what it is being marked as — and
		// separately, so a bookkeeping update can never cost the shop the sale.
		if (fromQuotation) {
			try {
				const q = await markQuotationConverted({ name: fromQuotation, invoice: res.invoice })
				notify(q.message, 'ok')
			} catch (e) {
				console.error('[pos] could not mark the quote sold', e)
				notify(`Sale posted, but ${fromQuotation} is still showing as open`, 'warn')
			}
		}

		// Going out with a rider. Done after the invoice exists, because the
		// delivery points at one — and separately from the sale, so a delivery
		// that cannot be recorded never costs the shop the sale itself.
		if (payment.delivery?.rider || payment.delivery?.riderName) {
			try {
				const drop = await createDelivery({
					invoice: res.invoice,
					customer: snapshot.customer,
					...payment.delivery,
				})
				notify(drop.message, 'ok')
			} catch (e) {
				console.error('[pos] delivery failed', e)
				notify(
					`Sale posted, but the delivery was not recorded: ${e.message || 'server error'}`,
					'warn',
				)
			}
		}

		if (askToPrint.value) printPrompt.value = true
		notify(
			res.outstanding > 0
				? `Invoice ${res.invoice} · ${fmtMoney(res.outstanding)} outstanding`
				: `Invoice ${res.invoice} posted`,
			'ok',
		)
		// Stock moved, so the grid's counts are now stale. Refreshed after the
		// receipt, never before — the cashier must not wait on this.
		catalog.refresh()
	} catch (e) {
		// The customer has already walked away, so this cannot be a silent
		// failure — it needs to be loud enough that the cashier tells someone.
		console.error('[pos] sale submit failed', e)

		// The tab is closing and took the request with it. Nobody knows whether
		// the invoice posted, so the stash is deliberately left in place: the
		// next load parks it as a held ticket, which someone has to look at
		// before it can be charged again. See `cartStorage.isUnloading`.
		if (isUnloading()) return

		cart.submitSettled()

		// Give the basket back. Without this the commonest failure — the wifi
		// dropping between the tap and the invoice — left the cashier re-scanning
		// a full trolley with the customer watching, which is precisely what the
		// cart persistence work exists to prevent.
		const back = cart.restoreFailedSale(basket)
		const reason = e.message || 'server error'
		notify(
			back?.where === 'held'
				? `Sale NOT posted: ${reason} — basket parked as ${back.ticket.id}, tell the manager`
				: back
					? `Sale NOT posted: ${reason} — basket is back, try again`
					: `Sale NOT posted: ${reason} — tell the manager`,
			'warn',
		)
		// The cart came back with it, so the customer it belonged to should too.
		if (back?.where === 'cart') customer.value = basket.customer
	}
}

useShortcuts({
	F2: () => searchInput.value?.$el?.querySelector('input')?.focus(),
	F3: holdSale,
	F4: openPay,
	escape: () => {
		if (customerSheet.value) return (customerSheet.value = false)
		if (shiftSheet.value) return (shiftSheet.value = false)
		if (stockSheet.value) return (stockSheet.value = false)
		if (paySheet.value) return (paySheet.value = false)
		if (returnSheet.value) return (returnSheet.value = false)
		if (quotationSheet.value) return (quotationSheet.value = false)
		if (heldSheet.value) return (heldSheet.value = false)
		if (cartPreview.value) return (cartPreview.value = false)
		if (cartSheet.value) return (cartSheet.value = false)
		if (query.value) return query.value = ''
	},
})
</script>

<template>
	<!-- Sits inside AppShell, which owns the window chrome and the module rail.
	     This view only lays out the POS itself. -->
	<div class="flex min-h-0 flex-1 flex-col overflow-hidden bg-surface-gray-1">
		<!-- POS sub-header: mode tabs on the left, running total on the right. -->
		<div
			class="flex shrink-0 items-center gap-2 border-b border-outline-gray-2 bg-surface-white px-3 py-1.5"
		>
			<PillTabs v-model="mode" :buttons="MODES" inset />
			<div class="ml-auto flex min-w-0 items-center gap-2">
				<!-- Who is selling, from which till and warehouse. Moved off the app
				     header, where it sat above screens it had nothing to do with;
				     here it is beside the cart it actually describes. -->
				<TillContext class="hidden md:flex" />
				<!-- Blue for the same reason `utils/tone.js` reserves it for any
				     figure with no good/bad meaning of its own — this is a running
				     total, not a warning or a result. -->
				<span class="tabular shrink-0 rounded-md border border-outline-blue-2 bg-surface-blue-2 px-2 py-1 text-p-xs font-medium text-ink-blue-3">
					{{ count }} {{ count === 1 ? 'item' : 'items' }} · {{ fmtMoney(total) }}
				</span>
			</div>
		</div>

		<!-- A shift left open overnight makes every till sale fail at submit:
		     ERPNext refuses an is_pos invoice against an opening entry from an
		     earlier day. Said here, before anything is rung up, because found at
		     checkout it fails after the customer has already paid — and the
		     message ERPNext raises does not name the fix. -->
		<button
			v-if="shift?.outdated"
			class="flex w-full shrink-0 items-center gap-2.5 bg-surface-red-5 px-4 py-2 text-left text-p-sm font-medium text-ink-white"
			@click="openShiftSheet()"
		>
			<LucideTriangleAlert class="h-4 w-4 shrink-0" />
			<span class="min-w-0">
				This shift was opened on an earlier day, so sales cannot be posted. Close it and
				open a new one — tap here.
			</span>
		</button>

		<!-- This shop requires a shift and there is none. Said before anything is
		     rung up, because the alternative is a full cart and a refusal at the
		     moment the customer is handing money over. -->
		<button
			v-if="blockedByShift"
			class="flex w-full shrink-0 items-center gap-2.5 bg-surface-amber-3 px-4 py-2 text-left text-p-sm font-medium text-ink-white"
			@click="openShiftSheet()"
		>
			<LucideSunrise class="h-4 w-4 shrink-0" />
			<span class="min-w-0">
				No shift is open, so sales cannot be completed. Count the drawer and open one
				— tap here.
			</span>
		</button>

		<!-- Demo catalog is unsellable: no ERPNext Item matches these codes, so
		     checkout fails at submit. Inline rather than floating — as an overlay
		     it sat on top of the item grid and hid a product card. -->
		<div
			v-if="catalog.isDemo && catalog.loaded"
			class="flex shrink-0 items-center gap-2.5 bg-surface-amber-3 px-4 py-2 text-p-sm font-medium text-ink-white"
		>
			<LucideTriangleAlert class="h-4 w-4 shrink-0" />
			<span class="min-w-0">
				{{
					catalog.error
						? 'Catalog unavailable — showing demo items that cannot be sold'
						: 'No sellable items on this site — showing demo items that cannot be sold'
				}}
			</span>
		</div>

		<!-- Toolbar: shortcuts left, item search right, matching the reference. -->
		<div
			class="flex shrink-0 flex-wrap items-center gap-2 border-b border-outline-gray-2 bg-surface-white px-3 py-2"
		>
			<Button
				variant="subtle"
				:icon-left="LucideRefreshCw"
				:loading="catalog.loading"
				tooltip="Refresh prices and stock"
				@click="refreshCatalog"
			/>
			<!-- Appears only once there is something to print, and names the
			     invoice: a cashier three customers later needs to know which sale
			     this receipt is for before pressing it. -->
			<!-- Appears only once there is something to print, and names the
			     invoice: a cashier three customers later needs to know which sale
			     this receipt is for before pressing it. -->
			<!-- Green: a receipt to reprint is a sale that already went through. -->
			<Button
				v-if="lastSale"
				variant="subtle"
				theme="green"
				:icon-left="LucidePrinter"
				:label="`Receipt ${lastSale.invoice}`"
				@click="printReceipt()"
			/>
			<!-- Blue, matching the running total beside it — both are "figures to
			     look up", not warnings or results. -->
			<Button
				variant="subtle"
				theme="blue"
				:icon-left="LucideReceiptText"
				label="Recent sales"
				@click="openRecent"
			/>
			<!-- Green to start a shift, amber to end one — the same open/shut
			     colours `TillContext`'s shift chip uses, so the two never disagree
			     about what "open" looks like. -->
			<!-- `!` on each utility below: Button defaults to a gray theme
			     internally even with no `theme` prop passed, so a plain override
			     class collides with its bg/text at equal specificity and the
			     winner depends on Tailwind's generated source order — not which
			     class was written last here. The `!important` modifier makes the
			     override actually win. -->
			<Button
				variant="subtle"
				:class="
					shift
						? '!bg-surface-amber-2 !text-ink-amber-3 hover:!bg-amber-200 active:!bg-amber-300'
						: '!bg-surface-green-2 !text-green-800 hover:!bg-green-200 active:!bg-green-300'
				"
				:icon-left="shift ? LucideSunset : LucideSunrise"
				:label="shift ? 'Close shift' : 'Open shift'"
				@click="openShiftSheet()"
			/>
			<!-- Violet: a cart set aside, same family as the signed-in chip and the
			     active mode tab — all three are "this counter, right now". -->
			<Button
				variant="subtle"
				class="!bg-surface-violet-1 !text-violet-600 hover:!bg-violet-200 active:!bg-violet-300"
				:icon-left="LucideLayers"
				:label="held.length ? `Held (${held.length})` : 'Held'"
				@click="heldSheet = true"
			/>
			<!-- Amber: a quote is a price nothing has been paid against yet — the
			     same "not settled" meaning amber carries on the shift chip. -->
			<!-- Beside Held on purpose: both answer "keep this basket for later",
			     and the difference is only whether it has to survive the tab. -->
			<Button
				variant="subtle"
				class="!bg-surface-amber-2 !text-ink-amber-3 hover:!bg-amber-200 active:!bg-amber-300"
				:icon-left="LucideFileText"
				label="Quotes"
				@click="quotationSheet = true"
			/>
			<!-- Blue once a real customer is named — walk-in stays neutral because
			     there is nothing yet to look up. -->
			<Button
				variant="subtle"
				:theme="customer ? 'blue' : 'gray'"
				:icon-left="LucideUserRound"
				:label="customer ? (customer.customer_name || customer.name) : 'Walk-in'"
				@click="pickCustomer(false)"
			/>
			<!-- Ask for stock without hunting through the sidebar.
			     Opens the list of requests rather than a blank form: most of the
			     time the question at the counter is "did anyone already ask for
			     this" — and the list has its own Add button for when the answer is
			     no. Teal because it is neither money nor a parked sale: it is a
			     message to whoever restocks. -->
			<Button
				variant="subtle"
				class="!bg-teal-100 !text-teal-700 hover:!bg-teal-200 active:!bg-teal-300"
				:icon-left="LucideClipboardList"
				label="Request for item"
				@click="materialSheet = true"
			/>

			<!-- Scan lives inside the search field: searching and scanning are the
			     same act to a cashier — find this product — so they share one control. -->
			<div class="relative ml-auto w-full sm:w-[280px]">
				<FormControl
					ref="searchInput"
					v-model="query"
					type="text"
					placeholder="Search or scan items…"
					:class="cameraScanAvailable ? 'pr-9' : ''"
				/>
				<button
					v-if="cameraScanAvailable"
					class="absolute right-1 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded text-ink-gray-5 transition-colors hover:bg-surface-gray-3 hover:text-ink-gray-7"
					aria-label="Scan with camera"
					@click="scanSheet = true"
				>
					<LucideScanLine class="h-4 w-4" />
				</button>
			</div>
		</div>

		<div class="flex min-h-0 flex-1 overflow-hidden">
			<div class="flex min-w-0 flex-1 flex-col overflow-hidden">
				<ItemGrid
					:items="visibleItems"
					:cart-qtys="cartQtys"
					:query="query"
					:show-images="!!till.context?.show_item_images"
					@add="addItem"
					@set-qty="setItemQty"
					@remove="removeItem"
				/>
			</div>

			<!-- Landscape tablet & desktop: cart docked beside the grid, always visible. -->
			<div
				class="hidden w-[360px] shrink-0 border-l border-outline-gray-2 lg:flex 2xl:w-[420px]"
			>
				<CartPanel @pay="openPay"
					@hold="holdSale"
					@quote="quotationSheet = true"
					@pick-customer="pickCustomer(false)"
					@inc="cartInc"
					@dec="cart.dec"
					@set-qty="cartSetQty"
					@set-uom="cart.setUom"
					@preview="cartPreview = true"
					:allow-rate-change="Boolean(till.context?.allow_rate_change)"
					:allow-discount-change="Boolean(till.context?.allow_discount_change)"
				/>
			</div>
		</div>

		<!-- Phone & portrait tablet: summary bar instead of a docked panel. -->
		<MobileCartBar
			class="lg:hidden"
			:count="count"
			:total="total"
			@open="cartSheet = true"
			@pay="openPay"
		/>

		<!-- Mobile cart review -->
		<BottomSheet v-if="isCompact" v-model="cartSheet" title="Cart" tall>
			<div class="flex h-[64dvh] flex-col">
				<CartPanel embedded class="min-h-0 flex-1" @pay="openPay"
					@hold="holdSale"
					@quote="quotationSheet = true"
					@pick-customer="pickCustomer(false)"
					@inc="cartInc"
					@dec="cart.dec"
					@set-qty="cartSetQty"
					@set-uom="cart.setUom"
					:allow-rate-change="Boolean(till.context?.allow_rate_change)"
					:allow-discount-change="Boolean(till.context?.allow_discount_change)"
				/>
			</div>
		</BottomSheet>

		<!-- Scan confirmation: what was read, and how many of it. -->
		<!-- Bound through a boolean: the dialog's open state is a flag, and handing
		     it the scanned item itself would make "closing" mean "set the item to
		     false". -->
		<Dialog
			:model-value="!!scanned"
			:options="{ title: scanRepeat ? 'Already scanned' : 'Scanned', size: 'sm' }"
			@update:model-value="$event || cancelScan()"
		>
			<template #body-content>
				<div v-if="scanned" class="flex flex-col gap-3">
					<div class="rounded-xl bg-surface-gray-2 px-4 py-3">
						<div class="text-p-base font-medium text-ink-gray-9">{{ scanned.item_name }}</div>
						<div class="tabular text-p-sm text-ink-gray-6">
							{{ fmtMoney(scanned.price) }}
							<span :class="scanned.stock > 0 ? 'text-ink-gray-5' : 'text-ink-red-3'">
								· {{ scanned.stock > 0 ? `${Math.floor(scanned.stock)} in stock` : 'out of stock' }}
							</span>
						</div>
					</div>

					<label class="block text-p-sm font-medium text-ink-gray-7">Quantity</label>
					<div class="flex items-center gap-2">
						<button
							class="grid h-12 w-12 shrink-0 place-items-center rounded-xl border border-outline-gray-2 text-ink-gray-7 hover:bg-surface-gray-2"
							@click="scanQty = String(Math.max(1, (Number(scanQty) || 1) - 1))"
						>
							−
						</button>
						<input
							ref="scanQtyInput"
							v-model="scanQty"
							type="number"
							inputmode="numeric"
							min="1"
							class="tabular h-12 min-w-0 flex-1 rounded-xl border border-outline-gray-2 bg-surface-gray-2 px-3 text-center text-2xl font-semibold text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
							@keyup.enter="confirmScan"
							@focus="$event.target.select()"
						/>
						<button
							class="grid h-12 w-12 shrink-0 place-items-center rounded-xl border border-outline-gray-2 text-ink-gray-7 hover:bg-surface-gray-2"
							@click="scanQty = String((Number(scanQty) || 0) + 1)"
						>
							+
						</button>
					</div>
					<!-- The quantity is the cashier's to set, and nothing changes it
					     behind them. A second read of the same label says so rather
					     than counting up: scanners double-fire off one trigger pull
					     often enough that a self-incrementing number is one nobody
					     can trust. -->
					<p
						v-if="scanRepeat"
						class="rounded-lg bg-surface-amber-2 px-3 py-2 text-p-sm font-medium text-ink-amber-3"
					>
						Already scanned — set the quantity you want.
					</p>
					<p v-if="scannedInCart" class="text-p-xs text-ink-gray-5">
						{{ scannedInCart }} already in the cart; this adds to that.
					</p>
					<p class="text-p-xs text-ink-gray-5">Enter accepts.</p>
				</div>
			</template>
			<template #actions>
				<div class="flex gap-2">
					<Button
						theme="gray"
						variant="solid"
						class="flex-1"
						:label="`Add ${Number(scanQty) || 0} to cart`"
						:disabled="!(Number(scanQty) > 0)"
						@click="confirmScan"
					/>
					<Button variant="subtle" label="Discard" @click="cancelScan" />
				</div>
			</template>
		</Dialog>

		<!-- Receipt prompt. Deliberately after the cart has cleared: the next
		     customer can already be served behind it. -->
		<Dialog v-model="printPrompt" :options="{ title: 'Sale complete', size: 'sm' }">
			<template #body-content>
				<div v-if="lastSale" class="flex flex-col gap-3">
					<div class="rounded-xl bg-surface-gray-2 px-4 py-3">
						<div class="text-p-xs text-ink-gray-5">{{ lastSale.invoice }}</div>
						<div class="tabular mt-0.5 text-2xl font-semibold text-ink-gray-9">
							{{ fmtMoney(lastSale.total) }}
						</div>
						<div v-if="lastSale.change > 0" class="tabular mt-0.5 text-p-sm text-ink-green-3">
							Change {{ fmtMoney(lastSale.change) }}
						</div>
						<div v-else-if="lastSale.outstanding > 0" class="tabular mt-0.5 text-p-sm text-ink-amber-3">
							{{ fmtMoney(lastSale.outstanding) }} still owed
						</div>
					</div>
					<!-- Sending it is a second way to hand over the same receipt, so it
					     opens in place rather than replacing the print choice. -->
					<div v-if="whatsappOpen" class="flex items-end gap-2 rounded-xl bg-surface-gray-2 p-3">
						<div class="flex-1">
							<FormControl
								v-model="whatsappTo"
								type="text"
								label="Send to"
								placeholder="Phone number"
							/>
						</div>
						<Button
							theme="green"
							variant="solid"
							:icon-left="LucideSend"
							label="Send"
							:loading="whatsappSending"
							:disabled="!whatsappTo"
							@click="sendReceiptWhatsapp"
						/>
					</div>

					<button
						class="text-left text-p-xs text-ink-gray-5 underline decoration-outline-gray-3 underline-offset-2 hover:text-ink-gray-7"
						@click="setAskToPrint(false)"
					>
						Stop asking on this till — the Receipt button stays in the toolbar
					</button>
				</div>
			</template>
			<template #actions>
				<div class="flex flex-wrap gap-2">
					<Button
						theme="gray"
						variant="solid"
						class="flex-1"
						:icon-left="LucidePrinter"
						label="Print receipt"
						@click="printFromPrompt"
					/>
					<Button
						v-if="!whatsappOpen"
						variant="subtle"
						:icon-left="LucideSend"
						label="WhatsApp"
						@click="openWhatsapp"
					/>
					<Button variant="subtle" label="No receipt" @click="printPrompt = false" />
				</div>
			</template>
		</Dialog>

		<BottomSheet v-model="recentSheet" title="Recent sales" tall wide>
			<div class="flex flex-col gap-2 px-4 pb-5">
				<div class="flex flex-wrap items-center justify-between gap-2">
					<FormControl v-model="recentMine" type="checkbox" label="Only mine" />
					<!-- A list scoped to a shift and a list that is simply empty look
					     identical, so the scope is a control rather than a silent
					     filter. -->
					<FormControl
						v-model="recentThisShift"
						type="checkbox"
						:label="recent.shift ? 'This shift only' : 'This shift only (none open)'"
						:disabled="!!recentDate || (!recent.shift && recentThisShift)"
					/>
					<span class="tabular text-p-sm text-ink-gray-6">
						{{ recent.totals.count || 0 }} sales · {{ fmtMoney(recent.totals.revenue || 0) }}
					</span>
				</div>

				<div class="flex items-end gap-2">
					<!-- Tappable across its whole width, and it says the day in words
					     rather than in ISO — see `DateField`. -->
					<DateField v-model="recentDate" label="On" class="w-[220px]" />
					<button
						v-if="recentDate"
						class="min-h-touch rounded-lg border border-outline-gray-2 px-3 text-p-sm font-medium text-ink-gray-7 hover:bg-surface-gray-2"
						@click="recentDate = ''"
					>
						Clear
					</button>
					<span v-if="recentDate" class="text-p-xs text-ink-gray-5">
						Showing that whole day, not just this shift
					</span>
				</div>

				<div v-if="recentLoading" class="grid h-32 place-items-center">
					<span class="text-p-sm text-ink-gray-5">Loading…</span>
				</div>
				<p v-else-if="!recent.rows.length" class="py-8 text-center text-p-sm text-ink-gray-5">
					No sales yet.
				</p>

				<div
					v-for="row in recent.rows"
					:key="row.name"
					class="flex items-center gap-3 rounded-xl border border-outline-gray-2 p-3 transition-colors hover:bg-surface-gray-1"
				>
					<button class="flex min-w-0 flex-1 items-center gap-3 text-left" @click="printReceipt(row.name)">
					<div class="min-w-0 flex-1">
						<!-- Wraps rather than competing for one line. The chips beside the
						     name never shrink, so on a narrow sheet they took their width
						     first and left the customer as "kam…" or "W…" — the one field
						     the row exists to identify. Now the name gets the line and the
						     chips drop below it when there is no room for both. -->
						<div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
							<span class="max-w-full truncate text-p-base font-medium text-ink-gray-9">
								{{ row.customer }}
							</span>
							<!-- Who rang it up. On a shared till "whose sale was that" is
							     asked constantly, and the invoice owner is the only record
							     of it. -->
							<span
								v-if="row.salesperson"
								class="flex shrink-0 items-center gap-1 rounded-full bg-[#EDE9FE] px-2 py-0.5 text-p-xs font-medium text-[#6D28D9]"
							>
								<LucideUserRound class="h-3 w-3" />
								{{ row.salesperson }}
							</span>
							<!-- Paid, part-paid or on account, in a word. The amount alone
							     cannot tell a settled sale from an unpaid one. -->
							<span
								v-if="row.status"
								class="shrink-0 rounded-full px-2 py-0.5 text-p-xs font-medium"
								:class="
									row.outstanding_amount > 0
										? 'bg-surface-amber-2 text-ink-amber-3'
										: 'bg-surface-green-2 text-ink-green-3'
								"
							>
								{{ row.status }}
							</span>
						</div>
						<div class="truncate text-p-xs text-ink-gray-5">
							{{ row.name }} · {{ row.posting_date }}
							<!-- Named rather than left to be inferred from a negative
							     total: a credit note beside a sale of the same value is
							     otherwise indistinguishable at a glance. -->
							<span v-if="row.is_return" class="font-medium text-ink-amber-3">
								· return of {{ row.return_against }}
							</span>
							<span v-else-if="!row.is_pos"> · off-till</span>
						</div>
					</div>
					<div class="shrink-0 text-right">
						<div class="tabular text-p-base font-semibold text-ink-gray-9">
							{{ fmtMoney(row.grand_total) }}
						</div>
						<div
							v-if="row.outstanding_amount > 0"
							class="tabular text-p-xs font-medium text-ink-red-3"
						>
							{{ fmtMoney(row.outstanding_amount) }} owed
						</div>
					</div>
					<LucidePrinter class="h-4 w-4 shrink-0 text-ink-gray-5" />
					</button>
					<!-- Beside the printer, because "send it to them" and "print it
					     again" are the same request answered two ways — and the shop
					     posts the same summary to its own group to reconcile the day. -->
					<button
						class="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-ink-gray-5 transition-colors hover:bg-surface-green-2 hover:text-ink-green-3"
						:aria-label="`Send ${row.name} on WhatsApp`"
						title="Send on WhatsApp"
						@click="shareSale(row)"
					>
						<LucideSend class="h-4 w-4" />
					</button>
					<!-- Kept a separate control: a customer wanting a reprint and one
					     wanting their money back must not be one mis-tap apart.
					     Absent on a credit note — a return is not itself returnable,
					     and the endpoint refuses one anyway, so offering the button
					     would only promise something that cannot happen. -->
					<button
						v-if="!row.is_return"
						class="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-ink-gray-5 transition-colors hover:bg-surface-amber-2 hover:text-ink-amber-3"
						:aria-label="`Return goods from ${row.name}`"
						title="Take goods back"
						@click="openReturn(row)"
					>
						<LucideUndo class="h-4 w-4" />
					</button>
				</div>
			</div>
		</BottomSheet>

		<!-- Quantity changes route through the same handlers the panel uses, so the
		     out-of-stock sheet still fires from here. A second component writing
		     to the cart store directly is how the one control that skips the shelf
		     check gets created. -->
		<CartPreview
			v-model="cartPreview"
			:allow-rate-change="Boolean(till.context?.allow_rate_change)"
			@inc="cartInc"
			@dec="cart.dec"
			@set-qty="cartSetQty"
			@set-uom="cart.setUom"
			@pay="cartPreview = false; openPay()"
		/>

		<PaySheet
			v-model="paySheet"
			:total="total"
			:customer="customer"
			:mpesa-channels="mpesaChannels.length ? mpesaChannels : undefined"
			:methods="paymentMethods"
			@complete="completeSale"
			@pick-customer="pickCustomer(true)"
		/>

		<ShiftSheet
			v-model="shiftSheet"
			:mode="shiftMode"
			:profiles="profiles"
			:payment-modes="paymentModes"
			:summary="closingSummary"
			:busy="shiftBusy"
			:options="movementOptions"
			:movement-busy="movementBusy"
			:initial-tab="shiftTab"
			:credit-sales="creditSales"
			:credit-busy="creditBusy"
			@pay-credit="doPayCredit"
			@open-shift="doOpenShift"
			@close-shift="doCloseShift"
			@record-movement="doRecordMovement"
			@void-movement="doVoidMovement"
		/>

		<CustomerSheet
			v-model="customerSheet"
			:required="customerRequired"
			@select="onCustomerSelected"
		/>

		<ScanSheet v-model="scanSheet" :last-result="scanResult" @scan="onCameraScan" />

		<ReturnSheet v-model="returnSheet" :invoice="returnInvoice" @returned="onReturned" />

		<!-- Sends the real PDF, and offers the shop's WhatsApp groups as well as a
		     number — the same control the back-office lists share rows through. -->
		<ShareSheet v-model="shareOpen" :payload="sharePayload" />

		<MaterialRequestSheet
			v-model="materialSheet"
			@converted="catalog.refresh()"
			@notify="notify($event.message, $event.tone === 'bad' ? 'warn' : 'ok')"
		/>

		<QuotationSheet
			v-model="quotationSheet"
			:lines="lines"
			:total="total"
			:customer="customer"
			:busy="quotationBusy"
			:editing-quotation="cart.sourceQuotation || ''"
			@save="saveQuotation"
			@load="loadQuotation"
		/>

		<!-- Placeholder: the real banner is rendered inline above the grid so it
		     pushes content rather than covering it. See the strip after TopBar. -->

		<HeldSheet
			v-model="heldSheet"
			:tickets="held"
			@resume="resumeHeld"
			@merge="mergeHeldTickets"
			@drop="cart.dropHeld"
		/>

		<StockActionSheet
			v-model="stockSheet"
			:item="stockItem"
			:warehouses="catalog.warehouses"
			:neighbours="catalog.neighbours"
			:suggested-qty="stockShortfall"
			@source="sourceFromNeighbour"
			@request-transfer="requestTransfer"
			@sell-anyway="sellAnyway"
		/>

		<!-- Toast. Sits above the mobile pay bar so it never covers the primary action. -->
		<Transition
			enter-active-class="transition duration-150 ease-out"
			leave-active-class="transition duration-150 ease-in"
			enter-from-class="translate-y-2 opacity-0"
			leave-to-class="translate-y-2 opacity-0"
		>
			<div
				v-if="toastMsg"
				class="pointer-events-none fixed inset-x-0 bottom-24 z-30 flex justify-center px-4 md:bottom-6"
			>
				<!-- frappe-ui has no dark green/amber *surface* token, only light
				     tints, so success and warning use tint + dark ink rather than a
				     solid fill. Matches the change-due block in the pay sheet. -->
				<div
					class="max-w-sm rounded-lg border px-4 py-2.5 text-p-sm font-medium shadow-lg"
					:class="{
						'border-transparent bg-surface-gray-7 text-ink-white': toastTone === 'info',
						'border-outline-green-2 bg-surface-green-2 text-ink-green-3':
							toastTone === 'ok',
						'border-outline-amber-2 bg-surface-amber-2 text-ink-amber-3':
							toastTone === 'warn',
					}"
				>
					{{ toastMsg }}
				</div>
			</div>
		</Transition>
	</div>
</template>
