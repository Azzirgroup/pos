<script setup>
import { computed, ref, watch } from 'vue'
import { Button } from 'frappe-ui'
import { getDocument, listDocuments, runDocumentAction } from '@/data/api'
import { useCartStore } from '@/stores/cart'
import { useCatalogStore } from '@/stores/catalog'
import { loadRequestIntoCart, loadSummary } from '@/utils/requestToCart'
import BottomSheet from './BottomSheet.vue'
import DocumentFormSheet from './DocumentFormSheet.vue'
import LucideClipboardList from '~icons/lucide/clipboard-list'
import LucideSearch from '~icons/lucide/search'
import LucideCart from '~icons/lucide/shopping-cart'
import LucidePlus from '~icons/lucide/plus'
import LucideCheck from '~icons/lucide/check'
import LucideBan from '~icons/lucide/ban'
import LucideUndo from '~icons/lucide/undo-2'

/**
 * Stock the shop has asked for, from the till.
 *
 * Built like the Quotes sheet on purpose. Both answer the same shape of
 * question at the counter — "is there already one of these, and can I turn it
 * into a sale" — and a cashier who has learned one should not have to learn the
 * other. Same card, same place for the actions, same button to raise a new one.
 *
 * The list is deliberately shallow: a row carries what a request *is*, and the
 * lines are fetched only when somebody converts one. A material request with
 * forty lines is common, and loading every line of every request to render a
 * list nobody has acted on yet is work thrown away.
 */
const props = defineProps({
	modelValue: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'converted', 'notify'])

const cart = useCartStore()
const catalog = useCatalogStore()

const rows = ref([])
const loading = ref(false)
const search = ref('')
const busyOne = ref('')
const newOpen = ref(false)

watch(
	() => props.modelValue,
	(open) => {
		if (open) load()
	},
)

let timer = null
watch(search, () => {
	clearTimeout(timer)
	timer = setTimeout(load, 250)
})

async function load() {
	loading.value = true
	try {
		const res = await listDocuments({
			key: 'material-request',
			// A month, matching the Documents screen's own default. A request older
			// than that has either arrived or been forgotten.
			days: 30,
			search: search.value || null,
			limit: 50,
		})
		rows.value = res.rows || []
	} catch (e) {
		emit('notify', { message: e.message || 'Could not load the requests', tone: 'bad' })
		rows.value = []
	} finally {
		loading.value = false
	}
}

/**
 * Everything, cancelled ones included.
 *
 * They were filtered out as "history", which was wrong in one specific way: a
 * cancelled request is the only kind that can be amended, so hiding it put the
 * one action it still has out of reach. It is greyed instead, which says the
 * same thing without removing the way back.
 */
const visible = computed(() => rows.value)

function toneFor(row) {
	if (row.status === 'Stopped' || row.status === 'Cancelled') return 'bg-surface-gray-2 text-ink-gray-6'
	if (row.per_received >= 100) return 'bg-surface-green-2 text-ink-green-3'
	if (row.docstatus === 0) return 'bg-surface-gray-3 text-ink-gray-7'
	return 'bg-surface-amber-2 text-ink-amber-3'
}

async function convert(row) {
	// The lines are not on the row, so they are fetched now — see the note above.
	busyOne.value = row.name
	try {
		const doc = await getDocument({ key: 'material-request', name: row.name })
		if (!cart.isEmpty && !window.confirm('This will replace what is in the cart. Continue?')) return
		const result = loadRequestIntoCart(doc, { cart, catalog })
		const said = loadSummary(result, row.name)
		emit('notify', { message: said.message, tone: said.tone })
		if (!result.empty) {
			emit('converted', row.name)
			emit('update:modelValue', false)
		}
	} catch (e) {
		emit('notify', { message: e.message || 'Could not open that request', tone: 'bad' })
	} finally {
		busyOne.value = ''
	}
}

/**
 * Finish a request that was saved as a draft.
 *
 * A draft is not a request yet — nobody downstream sees it, and it is easy to
 * save one, get pulled back to the counter and never return to it. Offering the
 * step here means the list you check is also the list you can act on.
 *
 * Gated on the server's own `_actions`, the same list the Documents screen
 * reads, so this cannot offer a submit that would then be refused.
 */
const allows = (row, action) => (row._actions || []).includes(action)

/**
 * The three state changes a request has, run from the list.
 *
 * Submit finishes a draft, cancel undoes a submitted one, and amend reopens a
 * cancelled one as a fresh draft — ERPNext's own cycle, which is why each is
 * offered only when the server says so rather than on a docstatus test here.
 *
 * All three confirm. They are one tap apart on a counter tablet, and two of
 * them cannot be undone by tapping again.
 */
const CONFIRM = {
	submit: (name) => `Submit ${name}? It cannot be edited afterwards.`,
	cancel: (name) => `Cancel ${name}? This cannot be undone — you would have to amend it.`,
	amend: (name) => `Amend ${name}? A new draft is created from it.`,
}

async function act(row, action) {
	if (!window.confirm(CONFIRM[action](row.name))) return
	busyOne.value = row.name
	try {
		const res = await runDocumentAction({ key: 'material-request', name: row.name, action })
		emit('notify', { message: res.message || `${row.name} ${action}ed`, tone: 'good' })
		await load()
	} catch (e) {
		emit('notify', { message: e.message || `Could not ${action} that request`, tone: 'bad' })
	} finally {
		busyOne.value = ''
	}
}

function onCreated() {
	// Straight back to the list with the new one on it, rather than closing
	// everything: raising a request and then seeing it listed is one action.
	load()
	emit('notify', { message: 'Request raised', tone: 'good' })
}
</script>

<template>
	<BottomSheet
		:model-value="modelValue"
		tall
		wide
		@update:model-value="emit('update:modelValue', $event)"
	>
		<div class="flex flex-col gap-3 px-4 pb-5 pt-1">
			<header class="flex items-start gap-3">
				<span class="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-teal-100 text-teal-700">
					<LucideClipboardList class="h-4 w-4" />
				</span>
				<div class="min-w-0 flex-1">
					<h2 class="text-p-lg font-semibold text-ink-gray-9">Material requests</h2>
					<p class="text-p-xs text-ink-gray-5">Stock asked for. Load one into the cart to sell it.</p>
				</div>
			</header>

			<!-- Raising one lives at the top, where the Quotes sheet keeps its own
			     "Quote this cart" — the same place for the same kind of action. -->
			<Button
				variant="subtle"
				class="!bg-teal-100 !text-teal-700 hover:!bg-teal-200"
				:icon-left="LucidePlus"
				label="Create material request"
				@click="newOpen = true"
			/>

			<div class="relative">
				<LucideSearch
					class="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-gray-4"
				/>
				<input
					v-model="search"
					type="text"
					placeholder="Search by number or item…"
					class="h-9 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 pl-8 pr-3 text-p-sm text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
				/>
			</div>

			<p v-if="loading" class="py-8 text-center text-p-sm text-ink-gray-5">Loading…</p>
			<p v-else-if="!visible.length" class="py-8 text-center text-p-sm text-ink-gray-5">
				No requests in the last month. Create one above.
			</p>

			<template v-else>
				<div
					v-for="row in visible"
					:key="row.name"
					class="flex flex-col rounded-xl border p-3"
					:class="
						row.docstatus === 2
							? 'border-outline-gray-2 bg-surface-gray-1'
							: 'border-outline-gray-2 bg-surface-white'
					"
				>
					<div class="flex min-w-0 items-start gap-3">
						<div class="min-w-0 flex-1">
							<div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
								<span class="max-w-full truncate text-p-base font-medium text-ink-gray-9">
									{{ row.name }}
								</span>
								<span
									class="shrink-0 rounded-full px-2 py-0.5 text-p-xs font-medium"
									:class="toneFor(row)"
								>
									{{ row.docstatus === 0 ? 'Draft' : row.docstatus === 2 ? 'Cancelled' : row.status }}
								</span>
							</div>
							<div class="truncate text-p-xs text-ink-gray-5">
								{{ row.material_request_type }} · {{ row.transaction_date }}
								<span v-if="row.per_received > 0"> · {{ Math.round(row.per_received) }}% received</span>
							</div>
						</div>
					</div>

					<div class="mt-2 flex flex-wrap items-center gap-2 border-t border-outline-gray-1 pt-2">
						<button
							class="flex items-center gap-1.5 rounded-md bg-[#7C3AED] px-2.5 py-1.5 text-p-xs font-semibold text-white transition-colors hover:bg-[#6D28D9] disabled:opacity-50"
							:disabled="busyOne === row.name"
							@click="convert(row)"
						>
							<LucideCart class="h-3.5 w-3.5" />
							{{ busyOne === row.name ? 'Loading…' : 'Convert to POS' }}
						</button>
						<!-- Only when the server says so. Dark rather than coloured:
						     submitting is the plain next step, not the one being
						     encouraged over converting. -->
						<button
							v-if="allows(row, 'submit')"
							class="flex items-center gap-1.5 rounded-md bg-surface-gray-7 px-2.5 py-1.5 text-p-xs font-semibold text-ink-white transition-colors hover:bg-surface-gray-6 disabled:opacity-50"
							:disabled="busyOne === row.name"
							@click="act(row, 'submit')"
						>
							<LucideCheck class="h-3.5 w-3.5" />
							{{ busyOne === row.name ? 'Working…' : 'Submit' }}
						</button>
						<!-- Outlined, not filled: undoing a request is a real action but
						     never the one to reach for first. -->
						<button
							v-if="allows(row, 'cancel')"
							class="flex items-center gap-1.5 rounded-md border border-outline-gray-2 bg-surface-white px-2.5 py-1.5 text-p-xs font-semibold text-ink-gray-7 transition-colors hover:border-outline-red-2 hover:bg-surface-red-1 hover:text-ink-red-3 disabled:opacity-50"
							:disabled="busyOne === row.name"
							@click="act(row, 'cancel')"
						>
							<LucideBan class="h-3.5 w-3.5" />
							{{ busyOne === row.name ? 'Working…' : 'Cancel' }}
						</button>
						<!-- The way back from a cancellation, and the only thing a
						     cancelled request can still do. -->
						<button
							v-if="allows(row, 'amend')"
							class="flex items-center gap-1.5 rounded-md border border-outline-gray-2 bg-surface-white px-2.5 py-1.5 text-p-xs font-semibold text-ink-gray-7 transition-colors hover:bg-surface-gray-2 disabled:opacity-50"
							:disabled="busyOne === row.name"
							@click="act(row, 'amend')"
						>
							<LucideUndo class="h-3.5 w-3.5" />
							{{ busyOne === row.name ? 'Working…' : 'Amend' }}
						</button>
					</div>
				</div>
			</template>
		</div>
	</BottomSheet>

	<!-- The same form the Documents screen raises one from, so a request typed
	     here and one typed in the back office are the same document. -->
	<DocumentFormSheet
		v-model:open="newOpen"
		doc-key="material-request"
		@created="onCreated"
		@notify="emit('notify', { message: $event.message, tone: $event.tone })"
	/>
</template>
