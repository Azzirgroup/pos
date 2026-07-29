<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { storeToRefs } from 'pinia'

import { useCatalogStore } from '@/stores/catalog'
import { useCartStore } from '@/stores/cart'
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
	getRecentSales,
} from '@/data/api'

import { Button, Dialog, FormControl, TabButtons } from 'frappe-ui'
import ItemGrid from '@/components/ItemGrid.vue'
import CartPanel from '@/components/CartPanel.vue'
import MobileCartBar from '@/components/MobileCartBar.vue'
import BottomSheet from '@/components/BottomSheet.vue'
import PaySheet from '@/components/PaySheet.vue'
import HeldSheet from '@/components/HeldSheet.vue'
import StockActionSheet from '@/components/StockActionSheet.vue'
import ShiftSheet from '@/components/ShiftSheet.vue'
import CustomerSheet from '@/components/CustomerSheet.vue'
import ScanSheet from '@/components/ScanSheet.vue'
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

const catalog = useCatalogStore()
const cart = useCartStore()
const till = useTillStore()
const { isCompact } = useBreakpoint()
const { lines, count, total, isEmpty, held } = storeToRefs(cart)

const query = ref('')
const searchInput = ref(null)

/** Mode tabs from the reference layout. Menu is the till itself; the others
 *  reuse sheets this view already owns rather than being separate screens. */
const MODES = [
	{ label: 'Menu', value: 'menu' },
	{ label: 'Held', value: 'held' },
	{ label: 'Customer', value: 'customer' },
]
const mode = ref('menu')

watch(mode, (m) => {
	if (m === 'held') heldSheet.value = true
	if (m === 'customer') pickCustomer(false)
	// The tabs are actions, not destinations; snap back so the label never lies
	// about which view you are on.
	if (m !== 'menu') setTimeout(() => (mode.value = 'menu'), 150)
})

const cartSheet = ref(false)
const paySheet = ref(false)
const heldSheet = ref(false)
const stockSheet = ref(false)
const stockItem = ref(null)
const scanFlash = ref(0)

/* ---------- shift ---------- */

const shift = ref(null)
const profiles = ref([])
const shiftSheet = ref(false)
const shiftMode = ref('open')
const shiftBusy = ref(false)
const closingSummary = ref(null)

/** Modes to collect an opening float for — from the shift, else the till's three. */
const paymentModes = computed(() =>
	shift.value?.balances?.length
		? shift.value.balances.map((b) => b.mode_of_payment)
		: ['Cash', 'M-Pesa', 'Credit Card'],
)

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

/** M-Pesa channels this shop is set up for; the pay sheet falls back if absent. */
const mpesaChannels = ref([])

onMounted(async () => {
	catalog.load()
	try {
		const [s, p] = await Promise.all([getOpenShift(), getProfiles()])
		shift.value = s
		profiles.value = p || []
	} catch (e) {
		// Shifts are a convenience, not a gate — never block selling on this.
		console.warn('[pos] shift lookup failed', e)
	}

	// Separately: a failure here must not cost us the shift lookup above.
	try {
		const methods = await getPaymentMethods()
		if (methods?.mpesa_channels?.length) mpesaChannels.value = methods.mpesa_channels
	} catch (e) {
		console.warn('[pos] payment methods lookup failed', e)
	}
})

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

async function printReceipt(invoice) {
	const target = invoice || lastSale.value?.invoice
	if (!target) return
	try {
		const { url } = await getReceiptUrl({ invoice: target })
		window.open(url, '_blank', 'noopener')
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

async function openRecent() {
	recentSheet.value = true
	await loadRecent()
}

async function loadRecent() {
	recentLoading.value = true
	try {
		recent.value = await getRecentSales({ limit: 25, mine: recentMine.value })
	} catch (e) {
		notify(e.message || 'Could not load recent sales', 'warn')
		recent.value = { rows: [], totals: {} }
	} finally {
		recentLoading.value = false
	}
}

watch(recentMine, () => {
	if (recentSheet.value) loadRecent()
})

async function openShiftSheet() {
	if (shift.value) {
		shiftMode.value = 'close'
		closingSummary.value = null
		shiftSheet.value = true
		try {
			closingSummary.value = await getClosingSummary()
		} catch (e) {
			console.error('[pos] closing summary failed', e)
			notify('Could not load shift totals', 'warn')
		}
		return
	}
	shiftMode.value = 'open'
	shiftSheet.value = true
}

async function doOpenShift(payload) {
	shiftBusy.value = true
	try {
		shift.value = await apiOpenShift(payload)
		shiftSheet.value = false
		// The header chip reads the shift from the shared store, so it has to be
		// told — otherwise it keeps saying "No shift" until the page reloads,
		// which is the one moment it most needs to be right.
		till.refresh()
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
		shift.value = null
		shiftSheet.value = false
		till.refresh()
		notify(
			res.difference === 0
				? `Shift closed — balanced (${res.name})`
				: `Shift closed — ${res.difference > 0 ? 'over' : 'short'} ${fmtMoney(Math.abs(res.difference))}`,
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
const cartQtys = computed(() => {
	const m = {}
	for (const l of lines.value) m[l.item_code] = (m[l.item_code] || 0) + l.qty
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

function addItem(item) {
	// Out of stock is a decision point, not an error. The cashier chooses:
	// buy it from next door, request it from another store, or sell anyway
	// because it is physically on the shelf but not yet received.
	if (item.stock <= 0) {
		stockItem.value = item
		stockSheet.value = true
		return
	}
	cart.add(item, 1)
}

/** Quantity controls live on the cell itself in the dense layout, so the grid
 *  needs to be able to change the cart, not only append to it. */
function setItemQty({ item, qty }) {
	const line = lines.value.find((l) => l.item_code === item.item_code)
	if (!line) return qty > 0 ? cart.add(item, qty) : undefined
	if (qty <= 0) return cart.remove(line.id)
	cart.setQty(line.id, qty)
}

function removeItem(item) {
	const line = lines.value.find((l) => l.item_code === item.item_code)
	if (line) cart.remove(line.id)
}

function sellAnyway({ item, qty }) {
	cart.add(item, qty)
	notify(`${item.item_name} added — stock will go negative`, 'warn')
}

function sourceFromNeighbour({ item, qty, supplier, buyRate }) {
	cart.add(item, qty, { sourced: { supplier, buyRate } })
	notify(`Sourcing ${qty} × ${item.item_name} from ${supplier}`, 'ok')
}

async function requestTransfer({ item, qty, warehouse }) {
	try {
		const res = await apiRequestTransfer({
			items: [{ item_code: item.item_code, qty }],
			fromWarehouse: warehouse,
		})
		notify(`${res.name} raised — sent to WhatsApp`, 'ok')
	} catch (e) {
		console.error('[pos] material request failed', e)
		notify(`Request failed: ${e.message || 'server error'}`, 'warn')
	}
}

function onScan(code) {
	const item = catalog.findByBarcode(code)
	if (item) {
		cart.add(item, 1)
		scanFlash.value++
		// Feedback stays on the camera overlay so the cashier can keep scanning
		// without looking away to check the cart.
		scanResult.value = { ok: true, message: `${item.item_name} · ${fmtMoney(item.price)}` }
		return
	}
	// Unknown barcode: drop it into search so the cashier can find it by name
	// rather than being left with a dead end.
	query.value = code
	scanResult.value = { ok: false, message: `No item with barcode ${code}` }
	notify(`No item with barcode ${code}`, 'warn')
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

useScanner(onScan)

function openPay() {
	if (isEmpty.value) return
	cartSheet.value = false
	paySheet.value = true
}

function holdSale() {
	const ticket = cart.hold()
	if (ticket) {
		cartSheet.value = false
		notify(`Sale ${ticket.id} held`, 'ok')
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
	}
	const paid = total.value
	const wasCredit = payment.method === 'credit'
	const customerName = customer.value?.customer_name || customer.value?.name

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
		lastSale.value = {
			invoice: res.invoice,
			total: paid,
			change: payment.change || 0,
			outstanding: res.outstanding || 0,
			at: Date.now(),
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
		notify(`Sale NOT posted: ${e.message || 'server error'} — tell the manager`, 'warn')
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
		if (heldSheet.value) return (heldSheet.value = false)
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
			<TabButtons v-model="mode" :buttons="MODES" />
			<div class="ml-auto flex items-center gap-2">
				<span class="tabular rounded-md border border-outline-gray-2 px-2 py-1 text-p-xs text-ink-gray-6">
					{{ count }} {{ count === 1 ? 'item' : 'items' }} · {{ fmtMoney(total) }}
				</span>
			</div>
		</div>

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
			<Button
				v-if="lastSale"
				variant="subtle"
				:icon-left="LucidePrinter"
				:label="`Receipt ${lastSale.invoice}`"
				@click="printReceipt()"
			/>
			<Button
				variant="subtle"
				:icon-left="LucideReceiptText"
				label="Recent sales"
				@click="openRecent"
			/>
			<Button
				variant="subtle"
				:icon-left="shift ? LucideSunset : LucideSunrise"
				:label="shift ? 'Close shift' : 'Open shift'"
				@click="openShiftSheet"
			/>
			<Button
				variant="subtle"
				:icon-left="LucideLayers"
				:label="held.length ? `Held (${held.length})` : 'Held'"
				@click="heldSheet = true"
			/>
			<Button
				variant="subtle"
				:icon-left="LucideUserRound"
				:label="customer ? (customer.customer_name || customer.name) : 'Walk-in'"
				@click="pickCustomer(false)"
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
					@add="addItem"
					@set-qty="setItemQty"
					@remove="removeItem"
				/>
			</div>

			<!-- Landscape tablet & desktop: cart docked beside the grid, always visible. -->
			<div
				class="hidden w-[360px] shrink-0 border-l border-outline-gray-2 lg:flex 2xl:w-[420px]"
			>
				<CartPanel @pay="openPay" @hold="holdSale" @pick-customer="pickCustomer(false)" />
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
				<CartPanel embedded class="min-h-0 flex-1" @pay="openPay" @hold="holdSale" @pick-customer="pickCustomer(false)" />
			</div>
		</BottomSheet>

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
					<button
						class="text-left text-p-xs text-ink-gray-5 underline decoration-outline-gray-3 underline-offset-2 hover:text-ink-gray-7"
						@click="setAskToPrint(false)"
					>
						Stop asking on this till — the Receipt button stays in the toolbar
					</button>
				</div>
			</template>
			<template #actions>
				<div class="flex gap-2">
					<Button
						theme="gray"
						variant="solid"
						class="flex-1"
						:icon-left="LucidePrinter"
						label="Print receipt"
						@click="printFromPrompt"
					/>
					<Button variant="subtle" label="No receipt" @click="printPrompt = false" />
				</div>
			</template>
		</Dialog>

		<BottomSheet v-model="recentSheet" title="Recent sales" tall>
			<div class="flex flex-col gap-2 px-4 pb-5">
				<div class="flex items-center justify-between gap-2">
					<FormControl v-model="recentMine" type="checkbox" label="Only mine" />
					<span class="tabular text-p-sm text-ink-gray-6">
						{{ recent.totals.count || 0 }} sales · {{ fmtMoney(recent.totals.revenue || 0) }}
					</span>
				</div>

				<div v-if="recentLoading" class="grid h-32 place-items-center">
					<span class="text-p-sm text-ink-gray-5">Loading…</span>
				</div>
				<p v-else-if="!recent.rows.length" class="py-8 text-center text-p-sm text-ink-gray-5">
					No sales yet.
				</p>

				<button
					v-for="row in recent.rows"
					:key="row.name"
					class="flex items-center gap-3 rounded-xl border border-outline-gray-2 p-3 text-left transition-colors hover:bg-surface-gray-1"
					@click="printReceipt(row.name)"
				>
					<div class="min-w-0 flex-1">
						<div class="truncate text-p-base font-medium text-ink-gray-9">
							{{ row.customer }}
						</div>
						<div class="truncate text-p-xs text-ink-gray-5">
							{{ row.name }} · {{ row.posting_date }}
							<span v-if="!row.is_pos"> · off-till</span>
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
			</div>
		</BottomSheet>

		<PaySheet
			v-model="paySheet"
			:total="total"
			:customer="customer"
			:mpesa-channels="mpesaChannels.length ? mpesaChannels : undefined"
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
			@open-shift="doOpenShift"
			@close-shift="doCloseShift"
		/>

		<CustomerSheet
			v-model="customerSheet"
			:required="customerRequired"
			@select="onCustomerSelected"
		/>

		<ScanSheet v-model="scanSheet" :last-result="scanResult" @scan="onCameraScan" />

		<!-- Placeholder: the real banner is rendered inline above the grid so it
		     pushes content rather than covering it. See the strip after TopBar. -->

		<HeldSheet
			v-model="heldSheet"
			:tickets="held"
			@resume="resumeHeld"
			@drop="cart.dropHeld"
		/>

		<StockActionSheet
			v-model="stockSheet"
			:item="stockItem"
			:warehouses="catalog.warehouses"
			:neighbours="catalog.neighbours"
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
