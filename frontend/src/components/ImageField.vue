<script setup>
import { computed, ref } from 'vue'
import LucideImagePlus from '~icons/lucide/image-plus'
import LucideTrash2 from '~icons/lucide/trash-2'

/**
 * A product photo, uploaded from the counter.
 *
 * ## Why it uploads immediately
 *
 * The value this field holds is a URL, not a file — that is what `Item.image`
 * stores and what the till later renders. So the bytes have to reach the server
 * before the form is saved, and the field emits the URL it got back. A new item
 * has no document to attach to yet, which is fine: `upload_file` will store a
 * File on its own, and the insert that follows points at it.
 *
 * ## Why the file is public
 *
 * The till renders these in a grid, and a private File is served only through a
 * permission check the `<img>` tag cannot pass — every photo would come back
 * 403. A product photo is not confidential; it is the picture on the shelf.
 *
 * ## What it refuses
 *
 * Anything that is not an image, and anything over `MAX_MB`. A shop uploading
 * straight from a phone camera sends 4–8MB files without thinking about it, and
 * sixty of those in one grid is a till that takes a minute to paint on the
 * shop's connection. The limit is stated up front rather than after the wait.
 */
const props = defineProps({
	modelValue: { type: String, default: '' },
	label: { type: String, default: 'Photo' },
	/** Attach to this document when it already exists — an edit rather than a new record. */
	doctype: { type: String, default: '' },
	docname: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'error'])

const MAX_MB = 5

const input = ref(null)
const busy = ref(false)
const problem = ref('')

const preview = computed(() => props.modelValue || '')

function choose() {
	problem.value = ''
	input.value?.click()
}

async function onPicked(event) {
	const file = event.target.files?.[0]
	// Cleared straight away so picking the same file twice still fires a change.
	event.target.value = ''
	if (!file) return

	if (!file.type.startsWith('image/')) {
		problem.value = 'That is not an image'
		return
	}
	if (file.size > MAX_MB * 1024 * 1024) {
		problem.value = `That photo is ${(file.size / 1024 / 1024).toFixed(1)}MB — keep it under ${MAX_MB}MB`
		return
	}

	busy.value = true
	problem.value = ''
	try {
		const body = new FormData()
		body.append('file', file, file.name)
		body.append('is_private', '0')
		body.append('optimize', '1')
		if (props.doctype && props.docname) {
			body.append('doctype', props.doctype)
			body.append('docname', props.docname)
			body.append('fieldname', 'image')
		}

		// Frappe's own upload endpoint rather than one of this app's: it already
		// handles storage, naming collisions, image optimisation and the File
		// record, and none of that is worth reimplementing.
		const res = await fetch('/api/method/upload_file', {
			method: 'POST',
			headers: { 'X-Frappe-CSRF-Token': window.csrf_token || '' },
			body,
		})
		const payload = await res.json().catch(() => ({}))
		if (!res.ok) {
			throw new Error(
				(payload._server_messages && JSON.parse(payload._server_messages)[0]) ||
					payload.exception ||
					'Upload failed',
			)
		}
		const url = payload.message?.file_url
		if (!url) throw new Error('The server did not return a file')
		emit('update:modelValue', url)
	} catch (e) {
		const said = String(e.message || e)
		problem.value = /failed to fetch/i.test(said) ? 'No connection — the photo did not upload' : said
		emit('error', problem.value)
	} finally {
		busy.value = false
	}
}

function clear() {
	problem.value = ''
	emit('update:modelValue', '')
}
</script>

<template>
	<div class="flex flex-col gap-1">
		<span class="text-p-xs text-ink-gray-5">{{ label }}</span>

		<div class="flex items-center gap-3">
			<!-- The photo itself is the button: tapping it replaces it, which is what
			     somebody looking at a wrong picture wants to do. -->
			<button
				type="button"
				class="grid h-16 w-16 shrink-0 place-items-center overflow-hidden rounded-lg border border-outline-gray-2 bg-surface-gray-2 transition-colors hover:border-outline-gray-3"
				:disabled="busy"
				:aria-label="preview ? 'Replace the photo' : 'Add a photo'"
				@click="choose"
			>
				<img v-if="preview" :src="preview" alt="" class="h-full w-full object-cover" />
				<LucideImagePlus v-else class="h-5 w-5 text-ink-gray-5" />
			</button>

			<div class="flex min-w-0 flex-col gap-1">
				<div class="flex items-center gap-2">
					<button
						type="button"
						class="rounded-md border border-outline-gray-2 bg-surface-white px-2.5 py-1.5 text-p-xs font-medium text-ink-gray-7 transition-colors hover:bg-surface-gray-2 disabled:opacity-50"
						:disabled="busy"
						@click="choose"
					>
						{{ busy ? 'Uploading…' : preview ? 'Replace' : 'Add a photo' }}
					</button>
					<button
						v-if="preview && !busy"
						type="button"
						class="grid h-7 w-7 place-items-center rounded-md text-ink-gray-5 transition-colors hover:bg-surface-red-2 hover:text-ink-red-3"
						aria-label="Remove the photo"
						@click="clear"
					>
						<LucideTrash2 class="h-3.5 w-3.5" />
					</button>
				</div>
				<p v-if="problem" class="text-p-xs text-ink-red-3">{{ problem }}</p>
				<p v-else class="text-p-xs text-ink-gray-5">JPG or PNG, under {{ MAX_MB }}MB</p>
			</div>
		</div>

		<input ref="input" type="file" accept="image/*" class="hidden" @change="onPicked" />
	</div>
</template>
