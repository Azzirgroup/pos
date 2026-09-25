<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { Button } from 'frappe-ui'
import { toast } from 'frappe-ui'
import { listOnlineOrders, getOnlineOrder, advanceOnlineOrder, searchRiders } from '@/data/api'
import PageHeader from '@/components/PageHeader.vue'
import PillTabs from '@/components/PillTabs.vue'
import BottomSheet from '@/components/BottomSheet.vue'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideSearch from '~icons/lucide/search'
import LucidePhone from '~icons/lucide/phone'
import LucideMapPin from '~icons/lucide/map-pin'
import LucideStore from '~icons/lucide/store'
import LucideTruck from '~icons/lucide/truck'
import LucideClock from '~icons/lucide/clock'
import LucideCheck from '~icons/lucide/check'
import LucidePackage from '~icons/lucide/package'

/**
 * Orders placed on the online shop, as a worklist.
 *
 * The queue opens on what needs doing — paid and not yet finished — oldest
 * first, because the customer who paid first has waited longest. Each order
 * moves along the shop's workflow (see cosmestics/online_orders.py):
 *
 *   Order Received → Processing → Out for Delivery / Ready for Pickup → Complete
 *
 * Sending an order out, or marking it ready for pickup, **bills** it: the Sales
 * Invoice is raised from the order with the customer's M-Pesa advance
 * allocated. A delivery also lands on the Deliveries worklist with its rider,
 * and when the rider marks it delivered the order completes on its own.
 */
const TABS = [
	{ label: 'To do', value: '' },
	{ label: 'New', value: 'Order Received' },
	{ label: 'Processing', value: 'Processing' },
	{ label: 'Out for delivery', value: 'Out for Delivery' },
	{ label: 'Ready for pickup', value: 'Ready for Pickup' },
	{ label: 'Complete', value: 'Complete' },
	{ label: 'Cancelled', value: 'Cancelled' },
	{ label: 'Carts', value: 'Draft' },
]

const TONES = {
	Draft: 'bg-surface-gray-2 text-ink-gray-6',
	'Order Received': 'bg-surface-blue-2 text-ink-blue-3',
	Processing: 'bg-surface-amber-2 text-ink-amber-3',
	'Out for Delivery': 'bg-surface-violet-2 text-violet-700',
	'Ready for Pickup': 'bg-surface-violet-2 text-violet-700',
	Complete: 'bg-surface-green-2 text-ink-green-3',
	Cancelled: 'bg-surface-red-2 text-ink-red-3',
}

/** The button that moves an order to each next status. */
const ACTIONS = {
	Processing: { label: 'Start packing', variant: 'solid' },
	'Out for Delivery': { label: 'Send out for delivery', variant: 'solid' },
	'Ready for Pickup': { label: 'Ready for pickup', variant: 'solid' },
	Complete: { label: 'Mark complete', variant: 'solid' },
	Cancelled: { label: 'Cancel order', variant: 'subtle', theme: 'red' },
}

const status = ref('')
const search = ref('')
const data = ref(null)
const loading = ref(false)
const busy = ref('')

const detail = ref(null)
const detailOpen = ref(false)
const sendOpen = ref(false)
const cancelOpen = ref(false)
const rider = ref({ name: '', courier: '' })
const riders = ref([])
const cancelNote = ref('')

const rows = computed(() => data.value?.orders || [])
const tabs = computed(() =>
	TABS.map((t) => {
		const counts = data.value?.counts || {}
		const n = t.value
			? counts[t.value]
			: ['Order Received', 'Processing', 'Out for Delivery', 'Ready for Pickup'].reduce((a, s) => a + (counts[s] || 0), 0)
		return { ...t, label: n ? `${t.label} (${n})` : t.label }
	})
)

async function load() {
	loading.value = true
	try {
		data.value = await listOnlineOrders({ status: status.value, search: search.value })
	} catch (e) {
		toast.error(e.message)
	} finally {
		loading.value = false
	}
}

let searchTimer = null
watch(status, load)
watch(search, () => {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(load, 300)
})

// New orders arrive while the screen is open; look again every minute.
let poll = null
onMounted(() => {
	load()
	poll = setInterval(() => document.hidden || load(), 60000)
})
onBeforeUnmount(() => clearInterval(poll))

async function open(row) {
	detailOpen.value = true
	detail.value = { ...row, lines: null }
	try {
		detail.value = await getOnlineOrder(row.name)
	} catch (e) {
		toast.error(e.message)
	}
}

async function move(order, to, extra = {}) {
	busy.value = `${order.name}:${to}`
	try {
		const res = await advanceOnlineOrder({ name: order.name, to, ...extra })
		toast.success(res.message)
		if (detailOpen.value && detail.value?.name === order.name) detail.value = res
		sendOpen.value = false
		cancelOpen.value = false
		load()
	} catch (e) {
		toast.error(e.message)
	} finally {
		busy.value = ''
	}
}

function act(order, to) {
	if (to === 'Out for Delivery') {
		detail.value = detail.value?.name === order.name ? detail.value : order
		rider.value = { name: '', courier: '' }
		sendOpen.value = true
		loadRiders('')
	} else if (to === 'Cancelled') {
		detail.value = detail.value?.name === order.name ? detail.value : order
		cancelNote.value = ''
		cancelOpen.value = true
	} else {
		move(order, to)
	}
}

async function loadRiders(q) {
	try {
		riders.value = (await searchRiders(q)) || []
	} catch (e) {
		riders.value = []
	}
}

/** "2d 4h", "3h 12m", "8m" — how long the order has sat in its status. */
function waited(seconds) {
	if (seconds === null || seconds === undefined) return ''
	const d = Math.floor(seconds / 86400)
	const h = Math.floor((seconds % 86400) / 3600)
	const m = Math.floor((seconds % 3600) / 60)
	if (d) return `${d}d ${h}h`
	if (h) return `${h}h ${m}m`
	return `${Math.max(m, 1)}m`
}

function longWait(row) {
	// A paid order nobody has touched for two hours is worth flagging.
	return row.status === 'Order Received' && row.seconds_in_status > 7200
}

function durationText(seconds) {
	if (seconds === null || seconds === undefined) return ''
	const d = Math.floor(seconds / 86400)
	const h = Math.floor((seconds % 86400) / 3600)
	const m = Math.floor((seconds % 3600) / 60)
	const p = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`
	if (d) return h ? `${p(d, 'day')} ${p(h, 'hour')}` : p(d, 'day')
	if (h) return m ? `${p(h, 'hour')} ${m} min` : p(h, 'hour')
	return m ? `${m} min` : 'under a minute'
}
</script>

<template>
	<div class="flex h-full flex-col">
		<PageHeader title="Online orders" subtitle="Paid on the online shop - pack them and send them out">
			<template #actions>
				<Button variant="subtle" :icon-left="LucideRefreshCw" :loading="loading" @click="load">Refresh</Button>
			</template>
		</PageHeader>

		<div class="flex flex-col gap-2 border-b border-outline-gray-1 px-4 py-2 sm:flex-row sm:items-center">
			<div class="min-w-0 overflow-x-auto"><PillTabs v-model="status" :buttons="tabs" inset /></div>
			<div class="relative ml-auto w-full sm:w-[260px]">
				<LucideSearch class="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-gray-4" />
				<input
					v-model="search"
					type="text"
					placeholder="Order, customer or phone…"
					class="h-9 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 pl-8 pr-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
				/>
			</div>
		</div>

		<div class="min-h-0 flex-1 overflow-auto px-4 py-4">
			<p v-if="loading && !rows.length" class="py-10 text-center text-p-sm text-ink-gray-5">Loading…</p>
			<div v-else-if="!rows.length" class="flex flex-col items-center gap-2 py-14 text-center">
				<LucidePackage class="h-8 w-8 text-ink-gray-4" />
				<p class="text-p-base font-medium text-ink-gray-8">{{ status ? 'Nothing here' : 'All caught up' }}</p>
				<p class="text-p-sm text-ink-gray-5">{{ status ? 'No online orders in this status.' : 'New paid orders from the online shop will appear here.' }}</p>
			</div>

			<div v-else class="grid gap-2 xl:grid-cols-2">
				<div
					v-for="row in rows"
					:key="row.name"
					class="flex flex-col gap-2.5 rounded-xl border bg-surface-white p-3"
					:class="longWait(row) ? 'border-amber-300' : 'border-outline-gray-2'"
				>
					<div
						class="-m-1 flex min-w-0 cursor-pointer items-start gap-3 rounded-lg p-1 transition-colors hover:bg-surface-gray-1"
						role="button"
						tabindex="0"
						@click="open(row)"
						@keyup.enter="open(row)"
					>
						<span class="grid h-9 w-9 shrink-0 place-items-center rounded-lg" :class="TONES[row.status]">
							<LucideTruck v-if="row.fulfilment === 'Delivery'" class="h-4 w-4" />
							<LucideStore v-else class="h-4 w-4" />
						</span>
						<div class="min-w-0 flex-1">
							<div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
								<span class="max-w-full truncate text-p-base font-medium text-ink-gray-9">{{ row.customer_name }}</span>
								<span class="shrink-0 rounded-full px-2 py-0.5 text-p-xs font-medium" :class="TONES[row.status]">{{ row.status }}</span>
								<span class="tabular shrink-0 text-p-sm font-medium text-ink-gray-8">{{ row.total_label }}</span>
							</div>
							<div class="truncate text-p-xs text-ink-gray-5">
								{{ row.name }} · {{ row.count }} item{{ row.count === 1 ? '' : 's' }} · {{ row.fulfilment }}<template v-if="row.receipt"> · {{ row.receipt }}</template>
							</div>
						</div>
						<span class="flex shrink-0 items-center gap-1 text-p-xs" :class="longWait(row) ? 'font-semibold text-ink-amber-3' : 'text-ink-gray-5'" :title="`In ${row.status} since ${row.since}`">
							<LucideClock class="h-3.5 w-3.5" />{{ waited(row.seconds_in_status) }}
						</span>
					</div>

					<div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-p-xs text-ink-gray-6">
						<span v-if="row.area" class="flex items-center gap-1.5"><LucideMapPin class="h-3.5 w-3.5 text-ink-gray-4" />{{ row.area }}</span>
						<a v-if="row.phone" :href="`tel:+${row.phone}`" class="flex items-center gap-1.5 hover:text-ink-gray-9"><LucidePhone class="h-3.5 w-3.5 text-ink-gray-4" />{{ row.phone }}</a>
					</div>

					<div v-if="row.next.length" class="flex flex-wrap gap-2">
						<Button
							v-for="to in row.next.filter((t) => t !== 'Cancelled' && (t !== 'Out for Delivery' || row.fulfilment === 'Delivery') && (t !== 'Ready for Pickup' || row.fulfilment === 'Pickup'))"
							:key="to"
							:variant="ACTIONS[to].variant"
							size="sm"
							:loading="busy === `${row.name}:${to}`"
							@click="act(row, to)"
						>
							{{ ACTIONS[to].label }}
						</Button>
						<Button v-if="row.next.includes('Cancelled')" variant="ghost" theme="red" size="sm" @click="act(row, 'Cancelled')">Cancel</Button>
					</div>
				</div>
			</div>
		</div>

		<BottomSheet v-model="detailOpen" :title="detail?.name || 'Order'" tall>
			<div v-if="detail" class="flex flex-col gap-4 px-4 pb-5">
				<div class="flex flex-wrap items-center gap-2">
					<span class="rounded-full px-2.5 py-1 text-p-xs font-semibold" :class="TONES[detail.status]">{{ detail.status }}</span>
					<span class="text-p-sm text-ink-gray-6">{{ detail.customer_name }} · {{ detail.total_label }}</span>
					<span v-if="detail.receipt" class="rounded bg-green-600 px-1.5 py-0.5 text-[10px] font-bold text-white">M-PESA {{ detail.receipt }}</span>
				</div>

				<div class="rounded-lg border border-outline-gray-2 p-3 text-p-sm">
					<p class="mb-1 font-medium text-ink-gray-8">{{ detail.fulfilment === 'Pickup' ? 'Pickup at the shop' : 'Deliver to' }}</p>
					<template v-if="detail.fulfilment === 'Delivery'">
						<p class="text-ink-gray-8">{{ detail.address }}</p>
						<p class="text-ink-gray-5">{{ detail.area }}<template v-if="detail.landmark"> · {{ detail.landmark }}</template></p>
					</template>
					<p class="mt-1 text-ink-gray-6">Phone: {{ detail.phone }}</p>
					<p v-if="detail.note" class="mt-1 italic text-ink-gray-6">"{{ detail.note }}"</p>
					<p v-if="detail.invoice" class="mt-1 text-ink-gray-5">Invoice {{ detail.invoice }}<template v-if="detail.delivery"> · Delivery {{ detail.delivery }}</template></p>
				</div>

				<div v-if="detail.lines" class="flex flex-col divide-y divide-outline-gray-1 rounded-lg border border-outline-gray-2">
					<div v-for="l in detail.lines" :key="l.item_code" class="flex items-center gap-3 p-2.5">
						<img v-if="l.image" :src="l.image" class="h-10 w-10 shrink-0 rounded border border-outline-gray-1 object-contain" alt="" />
						<span v-else class="h-10 w-10 shrink-0 rounded bg-surface-gray-2" />
						<span class="min-w-0 flex-1 truncate text-p-sm text-ink-gray-8">{{ l.name }}</span>
						<span class="text-p-sm text-ink-gray-6">× {{ l.qty }}</span>
						<span class="tabular w-20 text-right text-p-sm font-medium text-ink-gray-8">{{ l.amount_label }}</span>
					</div>
					<div class="flex justify-between p-2.5 text-p-sm text-ink-gray-6"><span>Delivery fee</span><span>{{ detail.delivery_fee_label }}</span></div>
				</div>

				<div v-if="detail.timeline">
					<p class="mb-2 text-p-sm font-medium text-ink-gray-8">History</p>
					<ol class="flex flex-col gap-2.5">
						<li v-for="s in detail.timeline.filter((t) => t.entered_at)" :key="s.status" class="flex items-start gap-2.5">
							<span class="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full" :class="s.state === 'current' ? 'bg-violet-600 text-white' : 'bg-surface-gray-3 text-ink-gray-6'">
								<LucideCheck class="h-3 w-3" />
							</span>
							<div class="min-w-0 flex-1 text-p-sm">
								<div class="flex flex-wrap justify-between gap-x-3">
									<span class="font-medium text-ink-gray-8">{{ s.status }}</span>
									<span class="text-p-xs text-ink-gray-5">{{ s.entered_at?.slice(0, 16) }}<template v-if="s.by"> · {{ s.by }}</template></span>
								</div>
								<p v-if="s.note" class="text-p-xs text-ink-gray-6">{{ s.note }}</p>
								<p v-if="s.seconds !== null" class="text-p-xs text-ink-gray-5">{{ s.state === 'current' ? `${durationText(s.seconds)} so far` : `${durationText(s.seconds)} in this stage` }}</p>
							</div>
						</li>
					</ol>
				</div>

				<div v-if="detail.next?.length" class="flex flex-wrap gap-2 border-t border-outline-gray-1 pt-3">
					<Button
						v-for="to in detail.next.filter((t) => t !== 'Cancelled' && (t !== 'Out for Delivery' || detail.fulfilment === 'Delivery') && (t !== 'Ready for Pickup' || detail.fulfilment === 'Pickup'))"
						:key="to"
						:variant="ACTIONS[to].variant"
						:loading="busy === `${detail.name}:${to}`"
						@click="act(detail, to)"
					>
						{{ ACTIONS[to].label }}
					</Button>
					<Button v-if="detail.next.includes('Cancelled')" variant="ghost" theme="red" @click="act(detail, 'Cancelled')">Cancel order</Button>
				</div>
			</div>
		</BottomSheet>

		<BottomSheet v-model="sendOpen" title="Send out for delivery">
			<div class="flex flex-col gap-3 px-4 pb-5">
				<p class="text-p-sm text-ink-gray-6">
					This bills {{ detail?.name }} (the M-Pesa payment is applied to the invoice), takes the stock, and puts it on the Deliveries worklist with the rider.
				</p>
				<div>
					<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">Rider</label>
					<input
						v-model="rider.name"
						list="online-riders"
						placeholder="Rider's name"
						class="h-9 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
						@input="loadRiders(rider.name)"
					/>
					<datalist id="online-riders">
						<option v-for="r in riders" :key="r.value || r.name" :value="r.value || r.name">{{ r.description || '' }}</option>
					</datalist>
				</div>
				<div>
					<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">Courier <span class="font-normal text-ink-gray-5">(Optional)</span></label>
					<input
						v-model="rider.courier"
						placeholder="In-house"
						class="h-9 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
					/>
				</div>
				<Button
					variant="solid"
					:disabled="!rider.name.trim()"
					:loading="busy === `${detail?.name}:Out for Delivery`"
					@click="move(detail, 'Out for Delivery', { riderName: rider.name.trim(), courier: rider.courier.trim() })"
				>
					Bill and send out
				</Button>
			</div>
		</BottomSheet>

		<BottomSheet v-model="cancelOpen" title="Cancel order">
			<div class="flex flex-col gap-3 px-4 pb-5">
				<p class="text-p-sm text-ink-gray-6">
					The customer sees this order as cancelled.<template v-if="detail?.paid_at"> They have paid - refund the M-Pesa payment {{ detail?.receipt }} yourself after cancelling.</template>
				</p>
				<textarea
					v-model="cancelNote"
					rows="3"
					placeholder="Why is it cancelled? The customer sees this."
					class="w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 py-2 text-p-sm focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
				/>
				<Button variant="solid" theme="red" :disabled="!cancelNote.trim()" :loading="busy === `${detail?.name}:Cancelled`" @click="move(detail, 'Cancelled', { note: cancelNote.trim() })">
					Cancel order
				</Button>
			</div>
		</BottomSheet>
	</div>
</template>
