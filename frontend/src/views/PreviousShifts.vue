<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Button, FormControl } from 'frappe-ui'
import { listRecentShifts } from '@/data/api'
import { fmtMoney, fmtMoneyShort } from '@/utils/format'
import PageHeader from '@/components/PageHeader.vue'
import StatTiles from '@/components/StatTiles.vue'
import ShareSheet from '@/components/ShareSheet.vue'
import { useRowActions } from '@/composables/useRowActions'
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

/** Columns exist for the share message; the page itself renders cards. */
const SHARE_COLUMNS = [
	{ label: 'Closed', key: 'closed', type: 'text' },
	{ label: 'Till', key: 'pos_profile', type: 'text' },
	{ label: 'Cashier', key: 'user', type: 'text' },
	{ label: 'Taken', key: 'grand_total', type: 'currency' },
	{ label: 'Paid out', key: 'paid_out', type: 'currency' },
	{ label: 'Difference', key: 'difference', type: 'currency' },
]

const { shareOpen, sharePayload, shareRow, shareList } = useRowActions({
	columns: SHARE_COLUMNS,
	title: (row) => `Shift ${row.name}`,
})

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
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col overflow-hidden">
		<PageHeader
			title="Previous shifts"
			subtitle="Closed tills, what they were short, and against whom">
			<template #actions>
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
				<Button variant="subtle" :icon-left="LucideRefreshCw" :loading="loading" @click="load" />
			</template>
		</PageHeader>

		<StatTiles :stats="stats" />

		<div class="min-h-0 flex-1 overflow-auto px-4 pb-4">
			<div v-if="loading && !rows.length" class="grid h-40 place-items-center">
				<p class="text-p-sm text-ink-gray-5">Loading…</p>
			</div>

			<div v-else-if="!rows.length" class="grid h-40 place-items-center px-6 text-center">
				<p class="text-p-sm text-ink-gray-5">
					No shifts have been closed yet. The first close will show up here.
				</p>
			</div>

			<div v-else class="grid items-start gap-3 lg:grid-cols-2 2xl:grid-cols-3">
				<article
					v-for="s in rows"
					:key="s.name"
					class="flex min-w-0 flex-col overflow-hidden rounded-lg border bg-surface-white"
					:class="
						s.shorts.length
							? 'border-outline-red-2'
							: 'border-outline-gray-2'
					"
				>
					<header class="flex items-start gap-3 border-b border-outline-gray-2 px-3 py-2.5">
						<div class="min-w-0 flex-1">
							<div class="truncate text-p-base font-medium text-ink-gray-9">
								{{ when(s.closed) }}
							</div>
							<div class="truncate text-p-xs text-ink-gray-5">
								{{ s.pos_profile }} · {{ s.user }}
							</div>
						</div>
						<div class="shrink-0 text-right">
							<div class="tabular text-p-lg font-semibold" :class="toneFor(s.difference)">
								{{
									Math.abs(s.difference) < 0.005
										? 'Balanced'
										: fmtMoney(Math.abs(s.difference))
								}}
							</div>
							<div v-if="Math.abs(s.difference) >= 0.005" class="text-p-xs text-ink-gray-5">
								{{ s.difference > 0 ? 'over' : 'short' }}
							</div>
						</div>
					</header>

					<div class="grid grid-cols-3 gap-2 px-3 py-2.5 text-p-xs">
						<div>
							<div class="text-ink-gray-5">Taken</div>
							<div class="tabular font-medium text-ink-gray-8">
								{{ fmtMoneyShort(s.grand_total) }}
							</div>
						</div>
						<div>
							<div class="text-ink-gray-5">Paid out</div>
							<div class="tabular font-medium text-ink-gray-8">
								{{ fmtMoneyShort(s.paid_out) }}
							</div>
						</div>
						<div>
							<div class="text-ink-gray-5">Opened</div>
							<div class="truncate font-medium text-ink-gray-8">{{ when(s.opened) }}</div>
						</div>
					</div>

					<!-- The shortfalls, with the name against each. This is the part
					     that has nowhere else to live: ERPNext's closing entry books
					     the difference but cannot say whose it is. -->
					<div
						v-if="s.shorts.length"
						class="border-t border-outline-gray-2 bg-surface-red-1 px-3 py-2.5"
					>
						<div class="mb-1.5 text-p-xs font-medium text-ink-red-3">
							{{ fmtMoney(s.short_total) }} short, against
							{{ s.assigned_to.length === 1 ? 'one person' : `${s.assigned_to.length} people` }}
						</div>
						<div
							v-for="short in s.shorts"
							:key="short.name"
							class="flex items-center gap-2 py-0.5 text-p-sm"
						>
							<LucideUserRound class="h-3.5 w-3.5 shrink-0 text-ink-gray-5" />
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
						v-else-if="s.expenses"
						class="flex items-center gap-2 border-t border-outline-gray-2 px-3 py-2 text-p-xs text-ink-gray-6"
					>
						<LucideBanknote class="h-3.5 w-3.5 shrink-0 text-ink-gray-5" />
						{{ fmtMoney(s.expenses) }} of till expenses, and it still balanced
					</div>

					<footer class="border-t border-outline-gray-2 px-3 py-1.5">
						<button
							class="text-p-xs font-medium text-ink-gray-6 hover:text-ink-gray-8"
							@click="shareRow(s)"
						>
							Share this shift
						</button>
					</footer>
				</article>
			</div>
		</div>

		<ShareSheet v-model="shareOpen" :payload="sharePayload" />
	</div>
</template>
