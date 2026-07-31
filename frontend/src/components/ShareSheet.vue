<script setup>
import { ref, computed, watch } from 'vue'
import { Button, Dialog } from 'frappe-ui'
import { shareOnWhatsapp, getWhatsappGroups } from '@/data/api'
import LucideSend from '~icons/lucide/send'
import LucideUsers from '~icons/lucide/users'
import LucideSmartphone from '~icons/lucide/smartphone'
import LucideCopy from '~icons/lucide/copy'

/**
 * Sharing a row, from any list.
 *
 * The message is composed by the caller and shown here before it goes, because
 * the rows on screen have already been filtered, formatted and labelled by the
 * person looking at them — a summary rebuilt from the server would not match
 * what they were pointing at.
 *
 * Editable for the same reason. "Please chase this one" on the end of a
 * generated summary is most of what a shared row is actually for.
 */
const props = defineProps({
	modelValue: { type: Boolean, default: false },
	/** { title, message, doctype, name } — doctype/name send the real PDF. */
	payload: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'sent'])

const to = ref('')
const message = ref('')
const sending = ref(false)
const result = ref(null)
const groups = ref([])
const groupsLoaded = ref(false)
const target = ref('number')

watch(
	() => props.modelValue,
	async (open) => {
		if (!open) return
		to.value = ''
		target.value = 'number'
		message.value = props.payload?.message || ''
		result.value = null

		// Fetched on first open rather than on mount: most sessions never share
		// anything, and this is a round trip to a bridge that idles.
		if (!groupsLoaded.value) {
			groupsLoaded.value = true
			try {
				const res = await getWhatsappGroups()
				groups.value = res?.groups || []
			} catch {
				groups.value = []
			}
		}
	},
)

/** Switching between a number and a group clears the recipient: the two are not
 *  interchangeable, and a leftover phone number sent to `/send` as a group JID
 *  fails by delivering nowhere at all. */
function pickTarget(key) {
	target.value = key
	to.value = ''
}

const asDocument = computed(() => Boolean(props.payload?.doctype && props.payload?.name))
const canSend = computed(() => to.value.trim().length > 0 && message.value.trim().length > 0)

async function send() {
	if (!canSend.value) return
	sending.value = true
	result.value = null
	try {
		const res = await shareOnWhatsapp({
			to: to.value.trim(),
			message: message.value,
			doctype: props.payload?.doctype || null,
			name: props.payload?.name || null,
		})
		result.value = { ok: res.sent, message: res.message }
		if (res.sent) {
			emit('sent', res)
			setTimeout(() => emit('update:modelValue', false), 900)
		}
	} catch (e) {
		result.value = { ok: false, message: e.message || 'Could not send' }
	} finally {
		sending.value = false
	}
}

/**
 * The fallback that always works.
 *
 * WhatsApp is not configured on every site, and a share dialog that can only
 * fail is worse than none. Copying the text lets someone paste it wherever they
 * were going to send it anyway.
 */
const copied = ref(false)
async function copy() {
	try {
		await navigator.clipboard.writeText(message.value)
		copied.value = true
		setTimeout(() => (copied.value = false), 1500)
	} catch {
		copied.value = false
	}
}
</script>

<template>
	<Dialog
		:model-value="modelValue"
		:options="{ title: payload?.title || 'Share', size: 'lg' }"
		@update:model-value="emit('update:modelValue', $event)"
	>
		<template #body-content>
			<div class="flex flex-col gap-4">
				<!-- Number or group. A group JID is not something anybody can type
				     from memory, so it is always picked from a list. -->
				<div class="flex gap-1 rounded-lg bg-surface-gray-2 p-1">
					<button
						v-for="t in [
							{ key: 'number', label: 'Phone number', icon: LucideSmartphone },
							{ key: 'group', label: 'Group', icon: LucideUsers },
						]"
						:key="t.key"
						class="flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-2 text-p-sm font-medium transition-colors"
						:class="
							target === t.key
								? 'bg-surface-white text-ink-gray-9 shadow-sm'
								: 'text-ink-gray-6 hover:text-ink-gray-8'
						"
						@click="pickTarget(t.key)"
					>
						<component :is="t.icon" class="h-4 w-4" />
						{{ t.label }}
					</button>
				</div>

				<input
					v-if="target === 'number'"
					v-model="to"
					type="tel"
					inputmode="tel"
					placeholder="2547…"
					class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 placeholder-ink-gray-4 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
				/>
				<template v-else>
					<select
						v-if="groups.length"
						v-model="to"
						class="h-11 w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 text-p-base text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
					>
						<option value="">Choose a group…</option>
						<option v-for="g in groups" :key="g.id" :value="g.id">{{ g.name }}</option>
					</select>
					<p v-else class="rounded-lg bg-surface-amber-2 px-3 py-2 text-p-sm text-ink-amber-3">
						No groups available — WhatsApp is not configured on this site.
					</p>
				</template>

				<div>
					<label class="mb-1.5 block text-p-sm font-medium text-ink-gray-7">Message</label>
					<textarea
						v-model="message"
						rows="8"
						class="w-full rounded-lg border border-outline-gray-2 bg-surface-gray-2 px-3 py-2 font-mono text-p-sm text-ink-gray-9 focus:border-outline-gray-4 focus:bg-surface-white focus:outline-none"
					/>
					<p v-if="asDocument" class="mt-1.5 text-p-xs text-ink-gray-5">
						The {{ payload.doctype }} PDF goes with this as an attachment — what they
						receive is the document, not a description of it.
					</p>
				</div>

				<p
					v-if="result"
					class="rounded-lg px-3 py-2 text-p-sm"
					:class="
						result.ok
							? 'bg-surface-green-2 text-ink-green-3'
							: 'bg-surface-red-2 text-ink-red-3'
					"
				>
					{{ result.message }}
				</p>
			</div>
		</template>
		<template #actions>
			<div class="flex gap-2">
				<Button
					theme="gray"
					variant="solid"
					class="flex-1"
					:icon-left="LucideSend"
					:loading="sending"
					:disabled="!canSend"
					label="Send"
					@click="send"
				/>
				<Button
					variant="subtle"
					:icon-left="LucideCopy"
					:label="copied ? 'Copied' : 'Copy text'"
					@click="copy"
				/>
			</div>
		</template>
	</Dialog>
</template>
