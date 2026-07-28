<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { storeToRefs } from 'pinia'

import { useCatalogStore } from '@/stores/catalog'
import { useCartStore } from '@/stores/cart'
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
} from '@/data/api'

import { Button, FormControl, TabButtons } from 'frappe-ui'
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

const catalog = useCatalogStore()
const cart = useCartStore()
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

		<PaySheet
			v-model="paySheet"
			:total="total"
			:customer="customer"
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
