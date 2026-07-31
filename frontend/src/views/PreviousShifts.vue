<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Button, FormControl, TabButtons } from 'frappe-ui'
import {
	listRecentShifts,
	getProfiles,
	getOpenShift,
	getClosingSummary,
	openShift as apiOpenShift,
	closeShift as apiCloseShift,
	getMovementOptions,
	recordMovement as apiRecordMovement,
	voidMovement as apiVoidMovement,
	getSettings,
	saveProfileSettings,
	assignProfile,
	getSettingsLinkOptions,
} from '@/data/api'
import { fmtMoney, fmtMoneyShort } from '@/utils/format'
import PageHeader from '@/components/PageHeader.vue'
import StatTiles from '@/components/StatTiles.vue'
import ShareSheet from '@/components/ShareSheet.vue'
import DataTable from '@/components/DataTable.vue'
import BottomSheet from '@/components/BottomSheet.vue'
import { useRowActions } from '@/composables/useRowActions'
import ShiftSheet from '@/components/ShiftSheet.vue'
import Reports from '@/views/Reports.vue'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideSend from '~icons/lucide/send'
import LucideUserRound from '~icons/lucide/user-round'
import LucideBanknote from '~icons/lucide/banknote'

/**
 * Shifts that have already closed.
 *
 * A page rather than a tab in the closing sheet, because these are two
 * different jobs. Closing a shift is done standing at the till with a customer
 * possibly waiting, in a sheet that covers the screen. Reading back over past
 * shifts — who was short, how much, and whose name is against it — is done
 * sitting down, and wants room and a URL somebody can be sent.
 *
 * The shortfalls lead. A closing that balanced needs no further attention; the
 * ones that did not are the reason anybody opens this.
 */
/**
 * Four tabs, because "shifts" is four different jobs that all belong to the
 * same object: what happened, what it adds up to, how the tills are set up, and
 * opening or closing one. Splitting them across screens would mean a manager
 * hunting for the till configuration in Settings while looking at the shift it
 * misconfigured.
 */
const TABS = [
	{ label: 'History', value: 'history' },
	{ label: 'Reports', value: 'reports' },
	{ label: 'Tills', value: 'profiles' },
	{ label: 'Open / close', value: 'run' },
]
const tab = ref('history')

/** Shift-shaped reports, so the picker is not the whole catalogue. */
const SHIFT_REPORTS = ['shift_history', 'cashier_sales', 'payment_modes']

const data = ref({ rows: [], totals: {} })
const loading = ref(false)
const mine = ref(false)
const limit = ref(25)

const SCOPES = [
	{ label: 'Everyone', value: false },
	{ label: 'Only mine', value: true },
]

const rows = computed(() => data.value.rows || [])

const stats = computed(() => {
	const t = data.value.totals || {}
	return [
		{ label: 'Shifts closed', value: t.shifts, type: 'number' },
		{ label: 'Taken', value: t.taken, type: 'currency' },
		{ label: 'Paid out', value: t.paid_out, type: 'currency' },
		{
			label: 'Short',
			value: t.short,
			type: 'currency',
			tone: t.short > 0 ? 'bad' : 'good',
			hint: t.unbalanced ? `${t.unbalanced} did not balance` : 'Every shift balanced',
		},
	]
})

/**
 * The register, in the order a manager reads it: when it closed, whose till it
 * was, what went through, and — last, where the eye lands — whether it balanced
 * and against whom.
 */
const COLUMNS = [
	{ label: 'Closed', key: 'closed', type: 'text' },
	{ label: 'Till', key: 'pos_profile', type: 'text' },
	{ label: 'Cashier', key: 'user', type: 'text' },
	{ label: 'Taken', key: 'grand_total', type: 'currency' },
	{ label: 'Paid out', key: 'paid_out', type: 'currency' },
	{ label: 'Difference', key: 'difference', type: 'currency' },
	{ label: 'Against', key: 'assigned_to', type: 'text' },
]

const { shareOpen, sharePayload, shareRow, shareList, actionsFor } = useRowActions({
	columns: COLUMNS,
	title: (row) => `Shift ${row.name}`,
})

/**
 * One shift, opened from its row.
 *
 * The list answers "which one went wrong"; this answers "how". The shortfalls
 * and their names live here rather than in the row, because a table wide enough
 * to hold them is one nobody can scan.
 */
const detail = ref(null)
const detailOpen = ref(false)

function openDetail(row) {
	detail.value = row
	detailOpen.value = true
}

onMounted(load)
watch([mine, limit], load)

async function load() {
	loading.value = true
	try {
		data.value = await listRecentShifts({ limit: limit.value, mine: mine.value })
	} catch (e) {
		console.error('[shifts]', e)
		data.value = { rows: [], totals: {} }
	} finally {
		loading.value = false
	}
}

/** Timestamps come back full; the day and time is what is being read. */
function when(value) {
	if (!value) return '—'
	return String(value).replace('T', ' ').slice(0, 16)
}

function toneFor(difference) {
	if (Math.abs(difference) < 0.005) return 'text-ink-green-3'
	return difference > 0 ? 'text-ink-blue-3' : 'text-ink-red-3'
}

/* ---------- opening and closing, away from the till ---------- */

/**
 * The same sheet the POS uses, reached from here too.
 *
 * A supervisor closing a till at the end of the day is not the person who was
 * selling on it, and sending them to the POS screen to do it means loading a
 * catalogue they are not going to use. The sheet is shared rather than rebuilt,
 * so the counting rules cannot differ between the two doors into it.
 */
const shift = ref(null)
const profiles = ref([])
const shiftSheet = ref(false)
const shiftMode = ref('open')
const shiftBusy = ref(false)
const closingSummary = ref(null)
const movementOptions = ref(null)
const movementBusy = ref(false)

const paymentModes = computed(() =>
	shift.value?.balances?.length
		? shift.value.balances.map((b) => b.mode_of_payment)
		: ['Cash', 'M-Pesa', 'Credit Card'],
)

async function loadShiftState() {
	try {
		const [s, p] = await Promise.all([getOpenShift(), getProfiles()])
		shift.value = s
		profiles.value = p || []
	} catch (e) {
		console.warn('[shifts] state lookup failed', e)
	}
}

async function openSheet(initialTab = 'count') {
	shiftTab.value = initialTab
	if (shift.value) {
		shiftMode.value = 'close'
		closingSummary.value = null
		shiftSheet.value = true
		await Promise.all([
			getClosingSummary()
				.then((s) => (closingSummary.value = s))
				.catch(() => notify('Could not load shift totals', 'bad')),
			getMovementOptions()
				.then((o) => (movementOptions.value = o))
				.catch(() => {}),
		])
		return
	}
	shiftMode.value = 'open'
	shiftSheet.value = true
}

const shiftTab = ref('count')

async function doOpenShift(payload) {
	shiftBusy.value = true
	try {
		shift.value = await apiOpenShift(payload)
		shiftSheet.value = false
		notify('Shift opened', 'good')
	} catch (e) {
		notify(e.message || 'Could not open shift', 'bad')
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
		closingSummary.value = null
		const named = (res.shorts_recorded || []).map((s) => s.person).join(', ')
		notify(
			res.difference === 0
				? `Shift closed — balanced (${res.name})`
				: `Shift closed — ${res.difference > 0 ? 'over' : 'short'} ${fmtMoney(Math.abs(res.difference))}` +
					(named ? ` · against ${named}` : ''),
			res.difference === 0 ? 'good' : 'bad',
		)
		// The shift just closed is now the newest row in the history.
		load()
	} catch (e) {
		notify(e.message || 'Could not close shift', 'bad')
	} finally {
		shiftBusy.value = false
	}
}

async function doRecordMovement(payload) {
	movementBusy.value = true
	try {
		await apiRecordMovement(payload)
		closingSummary.value = await getClosingSummary()
		notify('Recorded', 'good')
	} catch (e) {
		notify(e.message || 'Could not record that', 'bad')
	} finally {
		movementBusy.value = false
	}
}

async function doVoidMovement(movement) {
	movementBusy.value = true
	try {
		await apiVoidMovement({ name: movement.name })
		closingSummary.value = await getClosingSummary()
		notify('Put back', 'good')
	} catch (e) {
		notify(e.message || 'Could not void that', 'bad')
	} finally {
		movementBusy.value = false
	}
}

/* ---------- till profiles ---------- */

const settings = ref(null)
const profileValues = ref({})
const profileName = ref(null)
const savingProfile = ref(false)
const linkOptions = ref({})

const PROFILE_FIELDS = [
	{ key: 'warehouse', label: 'Warehouse', link: 'Warehouse', help: 'Stock every sale on this till draws down.' },
	{ key: 'selling_price_list', label: 'Price list', link: 'Price List', help: 'What this till sells at.' },
	{ key: 'customer', label: 'Default customer', link: 'Customer', help: 'Used when a sale has no named customer.' },
	{ key: 'allow_discount_change', label: 'Allow discounts', type: 'check' },
	{ key: 'allow_rate_change', label: 'Allow price edits at the till', type: 'check' },
]

const tillProfiles = computed(() => settings.value?.profiles || [])
const activeProfile = computed(
	() => tillProfiles.value.find((p) => p.name === profileName.value) || null,
)

async function loadProfiles() {
	try {
		settings.value = await getSettings()
		if (!profileName.value) selectProfile(settings.value.profiles[0]?.name || null)
		await Promise.all(
			[...new Set(PROFILE_FIELDS.filter((f) => f.link).map((f) => f.link))].map(async (dt) => {
				try {
					linkOptions.value[dt] = await getSettingsLinkOptions({ doctype: dt })
				} catch {
					linkOptions.value[dt] = []
				}
			}),
		)
	} catch (e) {
		notify(e.message || 'Could not load till profiles', 'bad')
	}
}

function selectProfile(name) {
	profileName.value = name
	profileValues.value = {
		...(tillProfiles.value.find((p) => p.name === name)?.values || {}),
	}
}

async function saveProfile() {
	savingProfile.value = true
	try {
		const res = await saveProfileSettings({ name: profileName.value, values: profileValues.value })
		notify(res.message, 'good')
		await loadProfiles()
	} catch (e) {
		notify(e.message || 'Could not save', 'bad')
	} finally {
		savingProfile.value = false
	}
}

async function toggleAssign(p) {
	savingProfile.value = true
	try {
		const res = await assignProfile({ name: p.name, assign: !p.mine })
		notify(res.assigned ? `You can now open a shift on ${p.name}` : `Removed from ${p.name}`, 'good')
		await Promise.all([loadProfiles(), loadShiftState()])
	} catch (e) {
		notify(e.message || 'Could not change that', 'bad')
	} finally {
		savingProfile.value = false
	}
}

// Fetched when their tab is first opened, not on mount: most visits are to read
// the history, and neither of these is cheap.
watch(tab, (t) => {
	if (t === 'run' && !profiles.value.length) loadShiftState()
	if (t === 'profiles' && !settings.value) loadProfiles()
})

const toast = ref(null)
let toastTimer = null
function notify(message, tone = 'good') {
	toast.value = { message, tone }
	clearTimeout(toastTimer)
	toastTimer = setTimeout(() => (toast.value = null), 2600)
}
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col overflow-hidden">
		<PageHeader
			title="Previous shifts"
			subtitle="Closed tills, what they were short, and against whom">
			<template #actions>
				<template v-if="tab === 'history'">
					<div class="w-[150px]">
						<FormControl type="select" v-model="mine" :options="SCOPES" />
					</div>
					<Button
						variant="subtle"
						:icon-left="LucideSend"
						:disabled="!rows.length"
						label="Share"
						@click="shareList(rows, 'Previous shifts')"
					/>
					<Button
						variant="subtle"
						:icon-left="LucideRefreshCw"
						:loading="loading"
						@click="load"
					/>
				</template>
			</template>
		</PageHeader>

		<div class="shrink-0 overflow-x-auto px-4 pt-3">
			<TabButtons v-model="tab" :buttons="TABS" />
		</div>

		<StatTiles v-if="tab === 'history'" :stats="stats" />

		<div v-if="tab === 'history'" class="min-h-0 flex-1 overflow-auto px-4 pb-4">
			<div v-if="loading && !rows.length" class="grid h-40 place-items-center">
				<p class="text-p-sm text-ink-gray-5">Loading…</p>
			</div>

			<div v-else-if="!rows.length" class="grid h-40 place-items-center px-6 text-center">
				<p class="text-p-sm text-ink-gray-5">
					No shifts have been closed yet. The first close will show up here.
				</p>
			</div>

			<!-- A list, not cards. Cards suited a shortlist; this is a register a
			     manager scans down looking for the one that did not balance, and a
			     column of differences compares far better than the same number
			     repeated in twelve boxes. Clicking a row opens what it was short
			     and against whom. -->
			<div v-else class="overflow-hidden rounded-lg border border-outline-gray-2">
				<DataTable
					:columns="COLUMNS"
					:rows="rows"
					row-key="closing"
					:scroll="false"
					:actions="actionsFor"
					empty-text="No shifts have been closed yet."
				>
					<template #cell-closed="{ row }">
						<button
							class="text-left font-medium text-ink-gray-8 underline decoration-outline-gray-3 underline-offset-2 hover:decoration-ink-gray-8"
							@click="openDetail(row)"
						>
							{{ when(row.closed) }}
						</button>
					</template>
					<template #cell-difference="{ row }">
						<span class="tabular font-semibold" :class="toneFor(row.difference)">
							{{
								Math.abs(row.difference) < 0.005
									? 'Balanced'
									: `${row.difference > 0 ? '+' : '−'}${fmtMoney(Math.abs(row.difference))}`
							}}
						</span>
					</template>
					<template #cell-assigned_to="{ row }">
						<!-- The names are the reason a short is recorded here at all,
						     so they are shown in the row rather than behind the click. -->
						<span v-if="row.assigned_to.length" class="text-ink-red-3">
							{{ row.assigned_to.join(', ') }}
						</span>
						<span v-else class="text-ink-gray-4">—</span>
					</template>
				</DataTable>
			</div>
		</div>

		<!-- ---------- Reports ----------
		     The existing report view, narrowed to the ones that say something
		     about a shift. Embedded rather than reimplemented so a figure here
		     and the same figure under Reports cannot drift apart. -->
		<Reports v-else-if="tab === 'reports'" embedded :only="SHIFT_REPORTS" />

		<!-- ---------- Till profiles ---------- -->
		<div v-else-if="tab === 'profiles'" class="min-h-0 flex-1 overflow-auto px-4 py-3">
			<div class="flex max-w-3xl flex-col gap-4">
				<p
					v-if="settings && !settings.can_edit_profile"
					class="rounded-lg bg-surface-amber-2 px-3 py-2 text-p-sm text-ink-amber-3"
				>
					You can see these but not change them.
				</p>

				<section class="rounded-lg border border-outline-gray-2 bg-surface-white">
					<header class="border-b border-outline-gray-2 px-4 py-2.5">
						<h2 class="text-p-sm font-semibold text-ink-gray-8">Tills</h2>
						<p class="mt-0.5 text-p-xs text-ink-gray-5">
							A till is a POS Profile. Every sale carries it, which is what the branch
							figures group by — and which shifts can be opened on it.
						</p>
					</header>
					<div class="flex flex-col gap-2 p-4">
						<p v-if="!tillProfiles.length" class="text-p-sm text-ink-gray-5">
							No till profiles you can use. Somebody with permission has to add you to
							one.
						</p>
						<div
							v-for="p in tillProfiles"
							:key="p.name"
							class="flex items-center gap-3 rounded-lg border px-3 py-2.5"
							:class="
								profileName === p.name
									? 'border-outline-gray-4 bg-surface-gray-2'
									: 'border-outline-gray-2'
							"
						>
							<button class="min-w-0 flex-1 text-left" @click="selectProfile(p.name)">
								<div class="truncate text-p-base font-medium text-ink-gray-9">
									{{ p.name }}
								</div>
								<div class="truncate text-p-xs text-ink-gray-5">
									{{ p.company }} · {{ p.users.length || 'all' }}
									{{ p.users.length === 1 ? 'user' : 'users' }}
								</div>
							</button>
							<Button
								:variant="p.mine ? 'subtle' : 'solid'"
								theme="gray"
								:label="p.mine ? 'Yours' : 'Use this till'"
								:disabled="!settings?.can_edit_profile || savingProfile"
								@click="toggleAssign(p)"
							/>
						</div>
					</div>
				</section>

				<section
					v-if="activeProfile"
					class="rounded-lg border border-outline-gray-2 bg-surface-white"
				>
					<header
						class="flex items-center gap-3 border-b border-outline-gray-2 px-4 py-2.5"
					>
						<div class="min-w-0 flex-1">
							<h2 class="truncate text-p-sm font-semibold text-ink-gray-8">
								{{ profileName }}
							</h2>
							<p class="mt-0.5 text-p-xs text-ink-gray-5">
								Changing the warehouse changes which stock every sale on this till
								draws down.
							</p>
						</div>
						<Button
							theme="gray"
							variant="solid"
							label="Save"
							:loading="savingProfile"
							:disabled="!settings?.can_edit_profile"
							@click="saveProfile"
						/>
					</header>
					<div class="flex flex-col gap-3 p-4">
						<div
							v-for="f in PROFILE_FIELDS"
							:key="f.key"
							class="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-4"
						>
							<label class="text-p-sm font-medium text-ink-gray-7 sm:w-[200px] sm:shrink-0">
								{{ f.label }}
							</label>
							<div class="min-w-0 flex-1">
								<input
									v-if="f.type === 'check'"
									v-model="profileValues[f.key]"
									type="checkbox"
									:true-value="1"
									:false-value="0"
									:disabled="!settings?.can_edit_profile"
									class="h-5 w-5 rounded border-outline-gray-3"
								/>
								<select
									v-else
									v-model="profileValues[f.key]"
									:disabled="!settings?.can_edit_profile"
									class="h-10 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
								>
									<option :value="null">Not set</option>
									<option
										v-for="o in linkOptions[f.link] || []"
										:key="o.name"
										:value="o.name"
									>
										{{ o.name }}
									</option>
								</select>
								<p v-if="f.help" class="mt-1 text-p-xs text-ink-gray-5">{{ f.help }}</p>
							</div>
						</div>
					</div>
				</section>
			</div>
		</div>

		<!-- ---------- Open / close ---------- -->
		<div v-else class="min-h-0 flex-1 overflow-auto px-4 py-3">
			<div class="flex max-w-2xl flex-col gap-4">
				<section class="rounded-lg border border-outline-gray-2 bg-surface-white p-4">
					<div v-if="shift" class="flex flex-col gap-3">
						<div>
							<div class="text-p-base font-medium text-ink-gray-9">
								{{ shift.pos_profile }} is open
							</div>
							<div class="text-p-sm text-ink-gray-5">
								Since {{ when(shift.period_start_date) }} · {{ shift.name }}
							</div>
						</div>
						<p
							v-if="shift.outdated"
							class="rounded-lg bg-surface-red-2 px-3 py-2 text-p-sm font-medium text-ink-red-3"
						>
							Opened on an earlier day, so sales cannot be posted against it. Close it
							and open a new one.
						</p>
						<div class="flex flex-wrap gap-2">
							<Button
								theme="gray"
								variant="solid"
								label="Count and close"
								@click="openSheet('count')"
							/>
							<Button variant="subtle" label="Money out" @click="openSheet('money')" />
							<Button
								variant="subtle"
								label="Neighbours"
								@click="openSheet('neighbours')"
							/>
						</div>
					</div>

					<div v-else class="flex flex-col gap-3">
						<div>
							<div class="text-p-base font-medium text-ink-gray-9">No shift is open</div>
							<div class="text-p-sm text-ink-gray-5">
								Count the drawer before selling, so the close means something.
							</div>
						</div>
						<Button
							theme="gray"
							variant="solid"
							label="Open a shift"
							:disabled="!profiles.length"
							@click="openSheet()"
						/>
						<p v-if="!profiles.length" class="text-p-sm text-ink-amber-3">
							You are not on any till profile. Add yourself under the Tills tab first.
						</p>
					</div>
				</section>

				<p class="px-1 text-p-xs text-ink-gray-5">
					This is the same counting sheet the till uses — a supervisor closing at the end
					of the day should not have to load the sales screen to do it.
				</p>
			</div>
		</div>

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
			@open-shift="doOpenShift"
			@close-shift="doCloseShift"
			@record-movement="doRecordMovement"
			@void-movement="doVoidMovement"
		/>

		<!-- One shift, opened from its row: what it was short and against whom. -->
		<BottomSheet v-model="detailOpen" title="Shift" tall>
			<div v-if="detail" class="flex flex-col gap-3 px-4 pb-5 pt-1">
				<div>
					<div class="text-p-lg font-semibold text-ink-gray-9">{{ when(detail.closed) }}</div>
					<div class="text-p-sm text-ink-gray-5">
						{{ detail.pos_profile }} · {{ detail.user }} · opened {{ when(detail.opened) }}
					</div>
				</div>

				<div
					class="flex items-center justify-between rounded-xl px-4 py-3"
					:class="
						Math.abs(detail.difference) < 0.005
							? 'bg-surface-green-2'
							: detail.difference > 0
								? 'bg-surface-blue-2'
								: 'bg-surface-red-2'
					"
				>
					<span class="text-p-base font-medium" :class="toneFor(detail.difference)">
						{{
							Math.abs(detail.difference) < 0.005
								? 'Balanced'
								: detail.difference > 0
									? 'Over'
									: 'Short'
						}}
					</span>
					<span class="tabular text-2xl font-semibold" :class="toneFor(detail.difference)">
						{{ fmtMoney(Math.abs(detail.difference)) }}
					</span>
				</div>

				<div class="grid grid-cols-3 gap-2 rounded-xl border border-outline-gray-2 p-3 text-p-xs">
					<div>
						<div class="text-ink-gray-5">Taken</div>
						<div class="tabular font-medium text-ink-gray-8">
							{{ fmtMoneyShort(detail.grand_total) }}
						</div>
					</div>
					<div>
						<div class="text-ink-gray-5">Paid out</div>
						<div class="tabular font-medium text-ink-gray-8">
							{{ fmtMoneyShort(detail.paid_out) }}
						</div>
					</div>
					<div>
						<div class="text-ink-gray-5">Expenses</div>
						<div class="tabular font-medium text-ink-gray-8">
							{{ fmtMoneyShort(detail.expenses) }}
						</div>
					</div>
				</div>

				<!-- The names against each shortfall — the thing ERPNext's closing
				     entry books but has nowhere to record. -->
				<div v-if="detail.shorts.length" class="flex flex-col gap-2">
					<div class="text-p-sm font-medium text-ink-red-3">
						{{ fmtMoney(detail.short_total) }} short, against
						{{ detail.assigned_to.length === 1 ? 'one person' : `${detail.assigned_to.length} people` }}
					</div>
					<div
						v-for="short in detail.shorts"
						:key="short.name"
						class="flex items-center gap-2 rounded-xl bg-surface-red-1 px-3 py-2 text-p-sm"
					>
						<LucideUserRound class="h-4 w-4 shrink-0 text-ink-gray-5" />
						<span class="min-w-0 flex-1 truncate text-ink-gray-8">
							{{ short.person }}
							<span class="text-ink-gray-5">· {{ short.mode_of_payment }}</span>
						</span>
						<span class="tabular shrink-0 font-semibold text-ink-red-3">
							{{ fmtMoney(short.amount) }}
						</span>
					</div>
				</div>

				<div
					v-else-if="detail.expenses"
					class="flex items-center gap-2 rounded-xl bg-surface-gray-2 px-3 py-2 text-p-sm text-ink-gray-6"
				>
					<LucideBanknote class="h-4 w-4 shrink-0 text-ink-gray-5" />
					{{ fmtMoney(detail.expenses) }} of till expenses, and it still balanced
				</div>

				<button
					class="min-h-touch w-full rounded-xl border border-outline-gray-2 py-3 text-p-base font-medium text-ink-gray-7 hover:bg-surface-gray-2"
					@click="shareRow(detail)"
				>
					Share this shift
				</button>
			</div>
		</BottomSheet>

		<ShareSheet v-model="shareOpen" :payload="sharePayload" />

		<Transition
			enter-active-class="transition-all duration-200"
			leave-active-class="transition-all duration-200"
			enter-from-class="opacity-0 translate-y-2"
			leave-to-class="opacity-0"
		>
			<div
				v-if="toast"
				class="pos-toast pointer-events-none absolute bottom-5 left-1/2 -translate-x-1/2 rounded-lg px-4 py-2.5 text-p-sm font-medium text-ink-white shadow-lg"
				:class="toast.tone === 'bad' ? 'bg-surface-red-5' : 'bg-surface-green-3'"
			>
				{{ toast.message }}
			</div>
		</Transition>
	</div>
</template>
