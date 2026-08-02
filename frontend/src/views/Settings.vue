<script setup>
import { ref, computed, onMounted } from 'vue'
import { Button, Spinner } from 'frappe-ui'
import {
	getSettings,
	savePosSettings,
	saveProfileSettings,
	saveUserSettings,
	assignProfile,
	getSettingsLinkOptions,
	createPosProfile,
	getWhatsappGroups,
} from '@/data/api'
import PageHeader from '@/components/PageHeader.vue'
import PillTabs from '@/components/PillTabs.vue'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideSave from '~icons/lucide/save'
import LucideCheck from '~icons/lucide/check'
import LucideLock from '~icons/lucide/lock'

/**
 * Everything configurable, in the app.
 *
 * These settings existed already — in the desk, which is a place a shop manager
 * either cannot reach or will not find. The result was a shop running on
 * whatever the installer guessed, with no way to point the M-Pesa channels at
 * the accounts they actually reconcile against.
 *
 * Nothing here is a new setting. The fields, their labels and their link
 * targets are read from the DocTypes, so this screen cannot describe a field
 * that no longer exists, and a field relabelled in the desk relabels here.
 */
const data = ref(null)
const loading = ref(false)
const saving = ref(false)
const toast = ref(null)

const TABS = [
	{ label: 'Till', value: 'pos' },
	{ label: 'This till', value: 'profile' },
	{ label: 'You', value: 'user' },
]
const tab = ref('pos')

/** Working copies, so an abandoned edit changes nothing. */
const pos = ref({})
const user = ref({})
const profileValues = ref({})
const profileName = ref(null)

/** doctype → [{name}], filled on demand for the link fields on screen. */
const options = ref({})

/**
 * WhatsApp groups, from the bridge.
 *
 * The staff group is stored as a JID — `120363012345678901@g.us` — which is not
 * a value a shop manager can find, verify or type. Worse, a wrong one fails by
 * delivering nowhere at all rather than by erroring, so a shop can believe it is
 * posting stock requests for weeks. `notifications.list_groups` already asks
 * waclient what groups exist; this is that list, as a dropdown.
 */
const groups = ref([])
const groupsLoading = ref(false)
const groupsError = ref(null)

async function loadGroups() {
	groupsLoading.value = true
	groupsError.value = null
	try {
		const res = await getWhatsappGroups()
		groups.value = res?.groups || []
		// The endpoint reports *why* it is empty — unconfigured, or configured
		// and genuinely groupless. Those need different actions, so the reason is
		// shown rather than an empty dropdown.
		if (!groups.value.length) groupsError.value = res?.reason || 'No groups came back from WhatsApp.'
	} catch (e) {
		groupsError.value = e.message || 'Could not reach WhatsApp'
		groups.value = []
	} finally {
		groupsLoading.value = false
	}
}

/** True when the stored JID is not one of the groups the bridge knows about. */
const unknownGroup = computed(
	() =>
		Boolean(pos.value.whatsapp_group_jid) &&
		groups.value.length > 0 &&
		!groups.value.some((g) => g.id === pos.value.whatsapp_group_jid),
)

onMounted(load)

async function load() {
	loading.value = true
	try {
		const res = await getSettings()
		data.value = res
		pos.value = { ...res.pos }
		user.value = { ...res.user }
		profileName.value = res.profiles[0]?.name || null
		profileValues.value = { ...(res.profiles[0]?.values || {}) }
		await loadOptions()
	} catch (e) {
		console.error('[settings]', e)
		notify(e.message || 'Could not load settings', 'bad')
	} finally {
		loading.value = false
	}
}

/**
 * Every link target on screen, fetched once.
 *
 * A shop has a handful of warehouses and modes of payment, so the whole list is
 * cheaper than a search-as-you-type round trip — and a dropdown a cashier can
 * see the end of is easier to trust than one they have to guess at.
 */
async function loadOptions() {
	const targets = new Set()
	for (const meta of [data.value.pos_meta, data.value.user_meta]) {
		for (const df of Object.values(meta || {})) {
			if (df.fieldtype === 'Link' && df.options) targets.add(df.options)
		}
	}
	for (const t of PROFILE_LINKS) targets.add(t)

	// Fetched alongside the link fields: the group picker is the one field on
	// this screen nobody can fill in by hand.
	loadGroups()

	await Promise.all(
		[...targets].map(async (doctype) => {
			try {
				options.value[doctype] = await getSettingsLinkOptions({ doctype })
			} catch {
				// A doctype this user cannot read simply gets no dropdown; the field
				// stays visible and empty rather than the section failing to render.
				options.value[doctype] = []
			}
		}),
	)
}

/** The POS Profile fields worth offering, and what each one points at. */
const PROFILE_FIELDS = [
	{ key: 'warehouse', label: 'Warehouse', link: 'Warehouse', help: 'Stock every sale on this till draws down.' },
	{ key: 'selling_price_list', label: 'Price list', link: 'Price List', help: 'What this till sells at.' },
	{ key: 'customer', label: 'Default customer', link: 'Customer', help: 'Used when a sale has no named customer.' },
	{ key: 'allow_discount_change', label: 'Allow discounts', type: 'check' },
	{ key: 'allow_rate_change', label: 'Allow price edits at the till', type: 'check' },
	{ key: 'hide_unavailable_items', label: 'Hide out-of-stock items', type: 'check' },
	{
		key: 'cosmestics_short_account',
		label: 'Till short account',
		link: 'Account',
		help: 'Where a shortfall a cashier is named for is charged. Anything nobody is named for goes to the Unattributed Short Account below.',
	},
]
const PROFILE_LINKS = PROFILE_FIELDS.filter((f) => f.link).map((f) => f.link)

/* ---------- adding a till ---------- */

const addingTill = ref(false)
const newTillName = ref('')
const newTillWarehouse = ref(null)
const creatingTill = ref(false)

const warehouseOptions = computed(() => (options.value['Warehouse'] || []).map((o) => o.name || o))

async function createTill() {
	if (!newTillName.value.trim()) return
	creatingTill.value = true
	try {
		const res = await createPosProfile({
			profileName: newTillName.value.trim(),
			values: newTillWarehouse.value ? { warehouse: newTillWarehouse.value } : {},
		})
		newTillName.value = ''
		newTillWarehouse.value = null
		addingTill.value = false
		await load()
		selectProfile(res.name)
		notify(res.message, 'good')
	} catch (e) {
		notify(e.message || 'Could not add that till', 'bad')
	} finally {
		creatingTill.value = false
	}
}

const profiles = computed(() => data.value?.profiles || [])
const activeProfile = computed(() => profiles.value.find((p) => p.name === profileName.value) || null)

function selectProfile(name) {
	profileName.value = name
	profileValues.value = { ...(profiles.value.find((p) => p.name === name)?.values || {}) }
}

/** Which POS settings fields go in which group, so the page reads in sections. */
const POS_GROUPS = [
	{
		title: 'Payment methods',
		hint: 'Each M-Pesa channel settles into a different account. Point them at the accounts you reconcile separately, or leave one blank to fall back to the generic M-Pesa mode.',
		fields: [
			'mode_cash',
			'mode_mpesa',
			'mode_mpesa_send',
			'mode_mpesa_paybill',
			'mode_mpesa_withdraw',
			'mode_card',
		],
	},
	{
		title: 'Selling',
		fields: ['selling_price_list'],
	},
	{
		title: 'Neighbour sourcing',
		hint: 'Suppliers in this group are offered at the till when an item runs short.',
		fields: ['neighbour_supplier_group', 'default_source_warehouse'],
	},
	{
		title: 'Till movements',
		hint: 'Where cash taken out of the drawer for a non-sales expense is booked.',
		fields: ['default_expense_account', 'require_shift_to_sell'],
	},
	{
		title: 'WhatsApp',
		fields: ['notify_material_request', 'whatsapp_group_jid', 'whatsapp_sender'],
	},
]

function meta(field) {
	return data.value?.pos_meta?.[field] || { label: field, fieldtype: 'Data' }
}

/* ---------- saving ---------- */

async function save() {
	saving.value = true
	try {
		let res
		if (tab.value === 'pos') res = await savePosSettings(pos.value)
		else if (tab.value === 'user') res = await saveUserSettings(user.value)
		else res = await saveProfileSettings({ name: profileName.value, values: profileValues.value })

		notify(res.message, 'good')
		// Reloaded rather than assumed: a link field can be rewritten by a
		// validation hook, and a screen still showing what was typed would
		// disagree with what was saved.
		await load()
	} catch (e) {
		notify(e.message || 'Could not save', 'bad')
	} finally {
		saving.value = false
	}
}

async function toggleAssign(profile) {
	saving.value = true
	try {
		const res = await assignProfile({ name: profile.name, assign: !profile.mine })
		notify(res.assigned ? `You can now open a shift on ${profile.name}` : `Removed from ${profile.name}`, 'good')
		await load()
	} catch (e) {
		notify(e.message || 'Could not change that', 'bad')
	} finally {
		saving.value = false
	}
}

const canSave = computed(() => {
	if (tab.value === 'pos') return data.value?.can_edit_pos
	if (tab.value === 'profile') return data.value?.can_edit_profile && profileName.value
	return true
})

let toastTimer = null
function notify(message, tone = 'good') {
	toast.value = { message, tone }
	clearTimeout(toastTimer)
	toastTimer = setTimeout(() => (toast.value = null), 2600)
}
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col overflow-hidden">
		<PageHeader title="Settings" subtitle="How this shop and this till are set up">
			<template #actions>
				<Button variant="subtle" :icon-left="LucideRefreshCw" :loading="loading" @click="load" />
			</template>

			<template #primary>
				<Button
					theme="gray"
					variant="solid"
					:icon-left="LucideSave"
					label="Save"
					:loading="saving"
					:disabled="!canSave"
					@click="save"
				/>
			</template>
		</PageHeader>

		<div class="shrink-0 overflow-x-auto px-4 pt-3">
			<PillTabs v-model="tab" :buttons="TABS" />
		</div>

		<div v-if="loading && !data" class="grid flex-1 place-items-center">
			<Spinner class="h-5 w-5" />
		</div>

		<div v-else-if="data" class="min-h-0 flex-1 overflow-auto px-4 py-3">
			<!-- ---------- Shop-wide till settings ---------- -->
			<div v-if="tab === 'pos'" class="flex max-w-3xl flex-col gap-4">
				<p
					v-if="!data.can_edit_pos"
					class="flex items-center gap-2 rounded-lg bg-surface-amber-2 px-3 py-2 text-p-sm text-ink-amber-3"
				>
					<LucideLock class="h-4 w-4 shrink-0" />
					You can see these but not change them. Ask whoever administers the site.
				</p>

				<section
					v-for="group in POS_GROUPS"
					:key="group.title"
					class="rounded-lg border border-outline-gray-2 bg-surface-white"
				>
					<header class="border-b border-outline-gray-2 px-4 py-2.5">
						<h2 class="text-p-sm font-semibold text-ink-gray-8">{{ group.title }}</h2>
						<p v-if="group.hint" class="mt-0.5 text-p-xs text-ink-gray-5">{{ group.hint }}</p>
					</header>
					<div class="flex flex-col gap-3 p-4">
						<div
							v-for="field in group.fields"
							:key="field"
							class="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-4"
						>
							<label class="text-p-sm font-medium text-ink-gray-7 sm:w-[200px] sm:shrink-0">
								{{ meta(field).label }}
							</label>
							<div class="min-w-0 flex-1">
								<!-- The staff group is a JID, which nobody can type or verify,
								     and a wrong one fails by delivering nowhere at all. Picked
								     from what the bridge actually reports instead. -->
								<template v-if="field === 'whatsapp_group_jid'">
									<select
										v-model="pos[field]"
										:disabled="!data.can_edit_pos || !groups.length"
										class="h-10 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none disabled:text-ink-gray-5"
									>
										<option :value="null">No group</option>
										<option v-for="g in groups" :key="g.id" :value="g.id">
											{{ g.name }}
										</option>
										<!-- Kept selectable so opening this screen cannot silently
										     clear a group that was already working. -->
										<option v-if="unknownGroup" :value="pos[field]">
											{{ pos[field] }} — not in the list
										</option>
									</select>
									<div class="mt-1 flex flex-wrap items-center gap-2">
										<button
											class="text-p-xs font-medium text-ink-gray-6 hover:text-ink-gray-8"
											:disabled="groupsLoading"
											@click="loadGroups"
										>
											{{ groupsLoading ? 'Checking…' : 'Refresh groups' }}
										</button>
										<span v-if="groupsError" class="text-p-xs text-ink-amber-3">
											{{ groupsError }}
										</span>
										<span v-else-if="groups.length" class="text-p-xs text-ink-gray-5">
											{{ groups.length }} group{{ groups.length === 1 ? '' : 's' }} on
											the connected number
										</span>
									</div>
								</template>
								<input
									v-else-if="meta(field).fieldtype === 'Check'"
									v-model="pos[field]"
									type="checkbox"
									:true-value="1"
									:false-value="0"
									:disabled="!data.can_edit_pos"
									class="h-5 w-5 rounded border-outline-gray-3 text-ink-gray-8"
								/>
								<select
									v-else-if="meta(field).fieldtype === 'Link'"
									v-model="pos[field]"
									:disabled="!data.can_edit_pos"
									class="h-10 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none disabled:text-ink-gray-5"
								>
									<option :value="null">Not set</option>
									<option
										v-for="o in options[meta(field).options] || []"
										:key="o.name"
										:value="o.name"
									>
										{{ o.name }}
									</option>
								</select>
								<input
									v-else
									v-model="pos[field]"
									type="text"
									:disabled="!data.can_edit_pos"
									class="h-10 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none disabled:text-ink-gray-5"
								/>
								<p v-if="meta(field).description" class="mt-1 text-p-xs text-ink-gray-5">
									{{ meta(field).description }}
								</p>
							</div>
						</div>
					</div>
				</section>
			</div>

			<!-- ---------- The POS Profile behind this till ---------- -->
			<div v-else-if="tab === 'profile'" class="flex max-w-3xl flex-col gap-4">
				<p v-if="!profiles.length" class="rounded-lg bg-surface-amber-2 px-3 py-2 text-p-sm text-ink-amber-3">
					You are not on any POS Profile, so you cannot open a shift. Add one below, or
					ask somebody with permission to put you on an existing till.
				</p>

				<!-- Adding a till, rather than sending a shopkeeper to the desk for it.
				     A second counter or a new branch needs one, and the payment methods
				     and write-off accounts it cannot exist without are filled in from
				     the company — see `settings.create_profile`. -->
				<section class="rounded-lg border border-outline-gray-2 bg-surface-white">
					<header class="flex items-center justify-between border-b border-outline-gray-2 px-4 py-2.5">
						<div>
							<h2 class="text-p-sm font-semibold text-ink-gray-8">Add a till</h2>
							<p class="mt-0.5 text-p-xs text-ink-gray-5">
								You are put on it, so you can open a shift on it straight away.
							</p>
						</div>
						<Button
							variant="subtle"
							:label="addingTill ? 'Cancel' : 'New till'"
							@click="addingTill = !addingTill"
						/>
					</header>
					<div v-if="addingTill" class="flex flex-wrap items-end gap-2 p-4">
						<div class="min-w-[200px] flex-1">
							<label class="mb-1.5 block text-p-xs font-medium text-ink-gray-7">Name</label>
							<input
								v-model="newTillName"
								type="text"
								placeholder="Counter 2, Kitengela…"
								class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
							/>
						</div>
						<div class="min-w-[200px] flex-1">
							<label class="mb-1.5 block text-p-xs font-medium text-ink-gray-7">
								Sells from
							</label>
							<select
								v-model="newTillWarehouse"
								class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
							>
								<option :value="null">This shop's default</option>
								<option v-for="w in warehouseOptions" :key="w" :value="w">{{ w }}</option>
							</select>
						</div>
						<Button
							theme="gray"
							variant="solid"
							class="!font-bold"
							:loading="creatingTill"
							:disabled="!newTillName.trim()"
							label="Create"
							@click="createTill"
						/>
					</div>
				</section>

				<section v-if="profiles.length" class="rounded-lg border border-outline-gray-2 bg-surface-white">
					<header class="border-b border-outline-gray-2 px-4 py-2.5">
						<h2 class="text-p-sm font-semibold text-ink-gray-8">Which till</h2>
						<p class="mt-0.5 text-p-xs text-ink-gray-5">
							A till is a POS Profile. Every sale carries it, which is what the branch
							figures are grouped by.
						</p>
					</header>
					<div class="flex flex-col gap-2 p-4">
						<div
							v-for="p in profiles"
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
							<!-- The one-tap fix for "no POS profile available", which is the
							     single most confusing thing the till can say. -->
							<Button
								:variant="p.mine ? 'subtle' : 'solid'"
								:theme="p.mine ? 'gray' : 'gray'"
								:icon-left="p.mine ? LucideCheck : null"
								:label="p.mine ? 'Yours' : 'Use this till'"
								:disabled="!data.can_edit_profile || saving"
								@click="toggleAssign(p)"
							/>
						</div>
					</div>
				</section>

				<section
					v-if="activeProfile"
					class="rounded-lg border border-outline-gray-2 bg-surface-white"
				>
					<header class="border-b border-outline-gray-2 px-4 py-2.5">
						<h2 class="text-p-sm font-semibold text-ink-gray-8">{{ profileName }}</h2>
						<p class="mt-0.5 text-p-xs text-ink-gray-5">
							Changing the warehouse changes which stock every sale on this till draws
							down.
						</p>
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
									:disabled="!data.can_edit_profile"
									class="h-5 w-5 rounded border-outline-gray-3 text-ink-gray-8"
								/>
								<select
									v-else
									v-model="profileValues[f.key]"
									:disabled="!data.can_edit_profile"
									class="h-10 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none disabled:text-ink-gray-5"
								>
									<option :value="null">Not set</option>
									<option v-for="o in options[f.link] || []" :key="o.name" :value="o.name">
										{{ o.name }}
									</option>
								</select>
								<p v-if="f.help" class="mt-1 text-p-xs text-ink-gray-5">{{ f.help }}</p>
							</div>
						</div>
					</div>
				</section>
			</div>

			<!-- ---------- The signed-in user ---------- -->
			<div v-else class="flex max-w-3xl flex-col gap-4">
				<section class="rounded-lg border border-outline-gray-2 bg-surface-white">
					<header class="border-b border-outline-gray-2 px-4 py-2.5">
						<h2 class="text-p-sm font-semibold text-ink-gray-8">Your details</h2>
						<p class="mt-0.5 text-p-xs text-ink-gray-5">
							This is the account sales are recorded against, and the name that shows on
							a shift.
						</p>
					</header>
					<div class="flex flex-col gap-3 p-4">
						<div
							v-for="(df, field) in data.user_meta"
							:key="field"
							class="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-4"
						>
							<label class="text-p-sm font-medium text-ink-gray-7 sm:w-[200px] sm:shrink-0">
								{{ df.label }}
							</label>
							<div class="min-w-0 flex-1">
								<select
									v-if="df.fieldtype === 'Link'"
									v-model="user[field]"
									class="h-10 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
								>
									<option :value="null">Not set</option>
									<option v-for="o in options[df.options] || []" :key="o.name" :value="o.name">
										{{ o.name }}
									</option>
								</select>
								<input
									v-else
									v-model="user[field]"
									type="text"
									class="h-10 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
								/>
							</div>
						</div>
					</div>
				</section>

				<p class="px-1 text-p-xs text-ink-gray-5">
					Passwords, roles and permissions are deliberately not here — they belong to
					whoever administers the site, not to the till.
				</p>
			</div>
		</div>

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
