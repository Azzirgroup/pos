<script setup>
import { computed, ref, watch } from 'vue'
import { Button, Spinner } from 'frappe-ui'
import { listOutbound, resendOutbound, resendOutboundWindow } from '@/data/api'
import DateField from './DateField.vue'
import LucideRefreshCw from '~icons/lucide/refresh-cw'
import LucideSend from '~icons/lucide/send'
import LucideCircleCheck from '~icons/lucide/circle-check'
import LucideCircleAlert from '~icons/lucide/circle-alert'

/**
 * What WhatsApp actually took, day by day — and a way to send again what it
 * did not.
 *
 * The senders are best-effort on purpose: a notification must never fail a
 * sale. The cost is that a morning when the bridge is down passes in silence,
 * and nothing afterwards says which statements and receipts never arrived.
 * This is that record, and the button that finishes the job.
 */
const emit = defineEmits(['notify'])

const today = new Date().toISOString().slice(0, 10)
const date = ref(today)
/**
 * The part of the day being asked about.
 *
 * Blank is the whole day, which is the common case. A shop that knows when the
 * trouble was — "between nine and one, when WhatsApp was down" — narrows to it
 * rather than reading a day of messages to find the gap.
 */
const fromTime = ref('')
const toTime = ref('')
const data = ref(null)
const loading = ref(false)
const busy = ref('')

const windowArgs = computed(() => ({
	fromDate: date.value,
	toDate: date.value,
	fromTime: fromTime.value || null,
	toTime: toTime.value || null,
}))

async function load() {
	loading.value = true
	try {
		data.value = await listOutbound(windowArgs.value)
	} catch (e) {
		emit('notify', { message: e.message || 'Could not read the message log', tone: 'bad' })
	} finally {
		loading.value = false
	}
}

let timer = null
watch(
	windowArgs,
	() => {
		// Debounced: a time box fires on every digit, and the half-typed ones in
		// between are a query nobody asked for.
		clearTimeout(timer)
		timer = setTimeout(load, 250)
	},
	{ immediate: true, deep: true },
)

/** Said on the button, so it cannot send more than what is on screen. */
const windowLabel = computed(() => {
	if (!fromTime.value && !toTime.value) return 'all day'
	return `${fromTime.value || '00:00'}–${toTime.value || '23:59'}`
})

function wholeDay() {
	fromTime.value = ''
	toTime.value = ''
}

const rows = computed(() => data.value?.rows || [])
const counts = computed(() => data.value?.counts || {})
const resendable = computed(() => data.value?.resendable || 0)

async function resendAll() {
	if (!resendable.value) return
	busy.value = 'all'
	try {
		const res = await resendOutboundWindow(windowArgs.value)
		emit('notify', { message: res.message, tone: res.failed?.length ? 'bad' : 'good' })
		await load()
	} catch (e) {
		emit('notify', { message: e.message || 'Could not send them again', tone: 'bad' })
	} finally {
		busy.value = ''
	}
}

async function resendOne(row) {
	busy.value = row.name
	try {
		const res = await resendOutbound({ names: [row.name] })
		emit('notify', { message: res.message, tone: res.failed?.length ? 'bad' : 'good' })
		await load()
	} catch (e) {
		emit('notify', { message: e.message || 'Could not send it again', tone: 'bad' })
	} finally {
		busy.value = ''
	}
}

const tone = (status) =>
	status === 'Sent'
		? 'bg-surface-green-2 text-ink-green-3'
		: status === 'Failed'
			? 'bg-surface-red-2 text-ink-red-3'
			: 'bg-surface-amber-2 text-ink-amber-3'

const when = (at) => (at || '').slice(11, 16)
</script>

<template>
	<div class="flex max-w-3xl flex-col gap-4">
		<section class="rounded-lg border border-outline-gray-2 bg-surface-white">
			<header class="flex flex-wrap items-end gap-3 border-b border-outline-gray-2 px-4 py-3">
				<div class="mr-auto">
					<h2 class="text-p-sm font-semibold text-ink-gray-8">Messages</h2>
					<p class="mt-0.5 text-p-xs text-ink-gray-5">
						Every WhatsApp message this till tried to send, and what became of it.
					</p>
				</div>
				<DateField v-model="date" label="Day" :max="today" class="w-[170px]" />
				<Button
					variant="subtle"
					class="min-h-touch"
					:icon-left="LucideRefreshCw"
					:loading="loading"
					label="Refresh"
					@click="load"
				/>
			</header>

			<!-- Narrowing to the hours it went wrong. Left blank it is the whole
			     day, which is what most people want; an outage is easier to read
			     when the rest of the day is out of the way. -->
			<div class="flex flex-wrap items-end gap-2 border-b border-outline-gray-2 px-4 py-2.5">
				<label class="flex flex-col">
					<span class="mb-1.5 text-p-xs font-medium text-ink-gray-7">From</span>
					<input
						v-model="fromTime"
						type="time"
						class="min-h-touch rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9"
					/>
				</label>
				<label class="flex flex-col">
					<span class="mb-1.5 text-p-xs font-medium text-ink-gray-7">To</span>
					<input
						v-model="toTime"
						type="time"
						class="min-h-touch rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-sm text-ink-gray-9"
					/>
				</label>
				<Button
					v-if="fromTime || toTime"
					variant="ghost"
					class="min-h-touch"
					label="Whole day"
					@click="wholeDay"
				/>
				<span class="ml-auto self-center text-p-xs text-ink-gray-5">
					Showing {{ windowLabel }}
				</span>
			</div>

			<div class="flex flex-wrap items-center gap-3 border-b border-outline-gray-2 px-4 py-2.5">
				<span class="flex items-center gap-1.5 text-p-sm text-ink-gray-7">
					<LucideCircleCheck class="h-4 w-4 text-ink-green-3" />
					{{ counts.Sent || 0 }} sent
				</span>
				<span class="flex items-center gap-1.5 text-p-sm text-ink-gray-7">
					<LucideCircleAlert class="h-4 w-4 text-ink-red-3" />
					{{ (counts.Failed || 0) + (counts.Queued || 0) }} did not go
				</span>
				<!-- Says what it will actually do. Time-bound notices — a shift
				     summary, a void — are left out of "send them all" once they are
				     a day old, because sending Tuesday's figures on Friday is not a
				     late message but a wrong one. They can still be sent one at a
				     time from the row. -->
				<Button
					class="ml-auto min-h-touch"
					theme="gray"
					variant="solid"
					:icon-left="LucideSend"
					:loading="busy === 'all'"
					:disabled="!resendable"
					:label="resendable ? `Send ${resendable} again` : 'Nothing to send again'"
					:title="`Sends only what is shown — ${windowLabel}`"
					@click="resendAll"
				/>
			</div>

			<div v-if="loading && !rows.length" class="grid h-24 place-items-center">
				<Spinner class="h-4 w-4" />
			</div>
			<p v-else-if="!rows.length" class="px-4 py-8 text-center text-p-sm text-ink-gray-5">
				Nothing was sent {{ windowLabel === 'all day' ? 'on this day' : `between ${windowLabel}` }}.
			</p>

			<ul v-else class="divide-y divide-outline-gray-1">
				<li v-for="row in rows" :key="row.name" class="flex flex-wrap items-start gap-x-3 gap-y-1 px-4 py-3">
					<span class="tabular shrink-0 text-p-xs text-ink-gray-5">{{ when(row.at) }}</span>
					<div class="min-w-0 flex-1">
						<div class="flex flex-wrap items-center gap-2">
							<span class="text-p-sm font-medium text-ink-gray-9">{{ row.kind }}</span>
							<span v-if="row.subject" class="text-p-xs text-ink-gray-6">{{ row.subject }}</span>
							<span class="rounded px-1.5 py-0.5 text-p-xs font-medium" :class="tone(row.status)">
								{{ row.status === 'Sent' ? 'Sent' : 'Did not go' }}
							</span>
							<span v-if="row.has_file" class="text-p-xs text-ink-gray-5">· with a file</span>
						</div>
						<div class="mt-0.5 truncate text-p-xs text-ink-gray-5">
							{{ row.is_group ? 'Staff group' : row.to }}<span v-if="row.error"> · {{ row.error }}</span>
						</div>
						<p v-if="row.stale && row.status !== 'Sent'" class="mt-0.5 text-p-xs text-ink-amber-3">
							Older than a day — left out of “send again”, since it describes a
							moment that has passed. Send it on its own if you still want to.
						</p>
					</div>
					<Button
						v-if="row.status !== 'Sent'"
						variant="subtle"
						class="min-h-touch shrink-0"
						:icon-left="LucideSend"
						:loading="busy === row.name"
						label="Send"
						@click="resendOne(row)"
					/>
				</li>
			</ul>
		</section>

		<p class="px-1 text-p-xs text-ink-gray-5">
			A message shows as sent once WhatsApp accepts it. If the number is not on
			WhatsApp, or the phone never comes online, that is beyond what this can see.
		</p>
	</div>
</template>
