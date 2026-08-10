<script setup>
import { ref, watch, nextTick } from 'vue'
import LucideChevronDown from '~icons/lucide/chevron-down'
import LucidePlus from '~icons/lucide/plus'

/**
 * A link field that searches the server instead of choosing from whatever
 * the first page of results happened to contain.
 *
 * Both `MasterSheet` and `DocumentFormSheet` used to pre-fetch twenty rows
 * per link field once, when the form opened, and render them as a plain
 * `<select>`. Fine for a handful of warehouses; wrong for an item group, a
 * customer, or an item on a shop with more than twenty of them — the one a
 * cashier actually wants was simply never in the list, with nothing on
 * screen explaining why. This asks the server again on every keystroke
 * instead, the same debounced-search pattern `CustomerSheet` uses.
 *
 * `fetcher` rather than a fixed API call: the two callers hit different
 * whitelisted methods (`master.options` vs `documents.link_options`), and
 * this component has no business knowing which doctype's rules apply to
 * which — it only knows how to turn typing into a debounced call and a list.
 */
const props = defineProps({
	modelValue: { type: String, default: '' },
	/** `(search: string) => Promise<{label, value}[]>` */
	fetcher: { type: Function, required: true },
	/**
	 * `(typed: string) => Promise<{label, value}>`, when this field can hold
	 * a record that does not exist yet — a supplier or customer met for the
	 * first time mid-form. Omit to leave the field search-only.
	 */
	onCreate: { type: Function, default: null },
	label: { type: String, default: '' },
	required: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])

const query = ref(props.modelValue || '')
const results = ref([])
const loading = ref(false)
const creating = ref(false)
const open = ref(false)
const input = ref(null)

let seq = 0
async function run(term = query.value) {
	const mine = ++seq
	loading.value = true
	try {
		const rows = await props.fetcher(term)
		// Drop stale responses: typing outruns the round trip.
		if (mine === seq) results.value = rows || []
	} catch {
		if (mine === seq) results.value = []
	} finally {
		if (mine === seq) loading.value = false
	}
}

let timer = null
watch(query, () => {
	clearTimeout(timer)
	timer = setTimeout(run, 200)
})

// The value can change from outside — switching record types resets the
// whole form — so the visible text has to follow it rather than freeze at
// whatever was last typed here.
watch(
	() => props.modelValue,
	(v) => {
		if (v !== query.value) query.value = v || ''
	},
)

function pick(option) {
	query.value = option.value
	emit('update:modelValue', option.value)
	open.value = false
}

/** Offered only when typing has not already landed on a real match. */
const showCreate = () =>
	props.onCreate &&
	query.value.trim() &&
	!results.value.some((r) => r.label.toLowerCase() === query.value.trim().toLowerCase())

async function createNew() {
	const typed = query.value.trim()
	if (!typed || !props.onCreate) return
	creating.value = true
	try {
		const option = await props.onCreate(typed)
		if (option) pick(option)
	} finally {
		creating.value = false
	}
}

async function onFocus() {
	open.value = true
	/**
	 * Opening a field that already holds a value must offer the alternatives,
	 * not just the value itself.
	 *
	 * The search used to run on whatever text was in the box, which was fine
	 * while these fields started empty. Now that several carry a default, that
	 * meant focusing "Into" searched for `Shop Floor - CS` and came back with
	 * one result — a picker that appeared to know of exactly one warehouse.
	 *
	 * The text is selected on focus anyway, so anything typed replaces it; a
	 * blank search is what "show me what I could pick instead" means.
	 */
	if (query.value && query.value === (props.modelValue || '')) run('')
	else if (!results.value.length) run()
	await nextTick()
	input.value?.select()
}

function onBlur() {
	// Deferred so a click on a result registers before the list disappears.
	setTimeout(() => {
		open.value = false
		// Nothing picked from what was typed — a link field can only hold a
		// real record, so a query that matches nothing is not silently kept.
		if (query.value !== (props.modelValue || '')) {
			query.value = props.modelValue || ''
		}
	}, 150)
}
</script>

<template>
	<div class="relative space-y-1.5">
		<label v-if="label" class="block text-p-sm text-ink-gray-6">
			{{ required ? `${label} *` : label }}
		</label>
		<div class="relative">
			<input
				ref="input"
				v-model="query"
				type="text"
				autocomplete="off"
				class="h-8 w-full rounded border border-outline-gray-3 bg-surface-white px-2 pr-7 text-p-sm text-ink-gray-8 focus:border-outline-gray-5 focus:outline-none focus:ring-1 focus:ring-outline-gray-3"
				@focus="onFocus"
				@blur="onBlur"
			/>
			<LucideChevronDown
				class="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-gray-4"
			/>
		</div>
		<div
			v-if="open"
			class="absolute inset-x-0 top-full z-10 mt-1 max-h-52 overflow-y-auto rounded-lg border border-outline-gray-2 bg-surface-white p-1 shadow-lg"
		>
			<p v-if="loading" class="px-2 py-1.5 text-p-xs text-ink-gray-5">Searching…</p>
			<template v-else>
				<button
					v-for="r in results"
					:key="r.value"
					type="button"
					class="flex w-full items-center rounded-md px-2 py-1.5 text-left text-p-sm text-ink-gray-8 hover:bg-surface-gray-2"
					@mousedown.prevent="pick(r)"
				>
					{{ r.label }}
				</button>
				<p v-if="!results.length" class="px-2 py-1.5 text-p-xs text-ink-gray-5">No matches</p>
				<!-- Met for the first time mid-form — a supplier or customer who has
				     never sold to or bought from this shop before is the common case
				     at the exact moment this field is being filled in, not an edge
				     case to send someone to the desk for. -->
				<button
					v-if="showCreate()"
					type="button"
					:disabled="creating"
					class="flex w-full items-center gap-1.5 rounded-md border-t border-outline-gray-1 px-2 py-1.5 text-left text-p-sm font-medium text-ink-blue-3 hover:bg-surface-blue-1 disabled:opacity-50"
					@mousedown.prevent="createNew"
				>
					<LucidePlus class="h-3.5 w-3.5 shrink-0" />
					{{ creating ? 'Creating…' : `Create "${query.trim()}"` }}
				</button>
			</template>
		</div>
	</div>
</template>
