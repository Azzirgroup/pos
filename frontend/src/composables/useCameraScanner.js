import { ref, shallowRef } from 'vue'
import { checksumOk } from '@/utils/barcode'

/**
 * How many frames must agree before a read is accepted. Two is enough: the
 * decoders are accurate per-frame, so this is guarding against the occasional
 * outlier rather than against a decoder that is generally wrong. Three would
 * make scanning noticeably slower for very little further gain.
 */
const CONFIRMING_FRAMES = 2

/**
 * Barcode scanning through the phone camera.
 *
 * Two backends, chosen at runtime:
 *
 * 1. `BarcodeDetector` — Chrome on Android exposes Google's on-device scanner.
 *    Far faster and more tolerant of blur and angle than any JS decoder, and it
 *    costs nothing in bundle size, so it is always preferred.
 * 2. `zxing-wasm` — everywhere else, notably iOS Safari and Firefox, which do
 *    not implement BarcodeDetector at all. Loaded lazily so the ~800 KB wasm is
 *    only fetched on devices that actually need it, and never by a desktop till
 *    using a USB scanner.
 *
 * Camera access needs a secure context (HTTPS or localhost). On plain HTTP
 * `getUserMedia` is undefined, which is reported as such rather than left as a
 * silent no-op.
 */

// Formats a cosmetics shop actually encounters. Narrowing the list measurably
// speeds up detection versus asking for every symbology.
const NATIVE_FORMATS = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39', 'itf', 'qr_code']
const ZXING_FORMATS = ['EAN-13', 'EAN-8', 'UPC-A', 'UPC-E', 'Code128', 'Code39', 'ITF', 'QRCode']

export function detectorSupported() {
	return typeof window !== 'undefined' && 'BarcodeDetector' in window
}

export function secureContextOk() {
	return typeof window !== 'undefined' && Boolean(navigator.mediaDevices?.getUserMedia)
}

/** Camera scanning is possible on any device with a camera and a secure origin. */
export function cameraScanSupported() {
	return secureContextOk()
}

let zxing = null
async function loadZxing() {
	if (zxing) return zxing
	const mod = await import('zxing-wasm/reader')
	// Point the loader at the bundled wasm. Without this it resolves against the
	// page URL, which under Frappe's /assets/<app>/frontend/ base is wrong, and
	// it would also require the CDN at runtime.
	const wasmUrl = (await import('zxing-wasm/reader/zxing_reader.wasm?url')).default
	mod.prepareZXingModule({ overrides: { locateFile: () => wasmUrl } })
	zxing = mod
	return zxing
}

export function useCameraScanner(onScan) {
	const active = ref(false)
	const error = ref(null)
	const torchOn = ref(false)
	const torchAvailable = ref(false)
	const engine = ref(null)
	const video = shallowRef(null)

	let stream = null
	let detector = null
	let raf = null
	let canvas = null
	let ctx = null
	let busy = false
	let lastCode = null
	let lastAt = 0
	/**
	 * The value the last frames agreed on, and how many frames have agreed.
	 *
	 * A camera decoding a blurred or angled label will occasionally return a
	 * confident but wrong value for a single frame, and the old code emitted the
	 * first thing it saw. Requiring consecutive frames to agree costs about a
	 * tenth of a second and removes that class of misread entirely: two
	 * independent frames producing the same wrong digits essentially does not
	 * happen, whereas one frame doing so happens often enough to notice at a
	 * counter.
	 */
	let candidate = null
	let agreeing = 0

	async function start(videoEl) {
		error.value = null

		if (!secureContextOk()) {
			// Almost always plain HTTP rather than a denied permission.
			error.value = 'insecure'
			return
		}

		try {
			stream = await navigator.mediaDevices.getUserMedia({
				video: {
					facingMode: { ideal: 'environment' },
					// Enough resolution to resolve a barcode across the frame without
					// making each decode pass expensive.
					width: { ideal: 1280 },
					height: { ideal: 720 },
				},
				audio: false,
			})
		} catch (e) {
			error.value = e?.name === 'NotAllowedError' ? 'denied' : 'nocamera'
			return
		}

		video.value = videoEl
		videoEl.srcObject = stream
		// iOS refuses to play an inline video without these set on the element.
		videoEl.setAttribute('playsinline', 'true')
		videoEl.muted = true
		await videoEl.play().catch(() => {})

		const track = stream.getVideoTracks()[0]
		torchAvailable.value = Boolean(track?.getCapabilities?.().torch)

		if (detectorSupported()) {
			detector = new window.BarcodeDetector({ formats: NATIVE_FORMATS })
			engine.value = 'native'
		} else {
			try {
				await loadZxing()
				canvas = document.createElement('canvas')
				// willReadFrequently: we call getImageData every frame.
				ctx = canvas.getContext('2d', { willReadFrequently: true })
				engine.value = 'wasm'
			} catch (e) {
				console.error('[scanner] zxing load failed', e)
				error.value = 'unsupported'
				stop()
				return
			}
		}

		active.value = true
		loop()
	}

	async function loop() {
		if (!active.value || !video.value) return

		// Skip a frame rather than queue work: the wasm decoder is slower than the
		// camera, and letting passes overlap turns a small lag into a freeze.
		if (!busy) {
			busy = true
			try {
				const code =
					engine.value === 'native' ? await detectNative() : await detectWasm()
				consider(code)
			} catch {
				// A transient decode failure is normal between frames; keep scanning.
			} finally {
				busy = false
			}
		}

		raf = requestAnimationFrame(loop)
	}

	async function detectNative() {
		const codes = await detector.detect(video.value)
		return codes.length ? codes[0].rawValue : null
	}

	async function detectWasm() {
		const v = video.value
		if (!v.videoWidth) return null

		// Decode a downscaled frame: barcode reading does not need full sensor
		// resolution, and halving the pixels roughly halves the decode time.
		const scale = Math.min(1, 800 / v.videoWidth)
		canvas.width = Math.round(v.videoWidth * scale)
		canvas.height = Math.round(v.videoHeight * scale)
		ctx.drawImage(v, 0, 0, canvas.width, canvas.height)

		const results = await zxing.readBarcodes(
			ctx.getImageData(0, 0, canvas.width, canvas.height),
			{ tryHarder: true, formats: ZXING_FORMATS, maxNumberOfSymbols: 1 },
		)
		return results.length ? results[0].text : null
	}

	/**
	 * Hold a read until a second frame confirms it.
	 *
	 * A frame that decodes nothing does not reset the tally — the label drifting
	 * out of focus for one frame is not disagreement, and treating it as such
	 * meant a hand-held phone rarely got two "consecutive" reads at all. Only a
	 * *different* value resets it, because that is the case where one of the two
	 * is genuinely wrong.
	 */
	function consider(code) {
		if (!code) return

		// A code that fails its own check digit was misread by the decoder. There
		// is nothing to confirm and nothing to look up.
		if (!checksumOk(code)) {
			candidate = null
			agreeing = 0
			return
		}

		if (code !== candidate) {
			candidate = code
			agreeing = 1
			return
		}

		agreeing += 1
		if (agreeing >= CONFIRMING_FRAMES) {
			candidate = null
			agreeing = 0
			emit(code)
		}
	}

	function emit(code) {
		if (!code) return
		const now = Date.now()
		// The camera re-reads the same label many times a second. Without this
		// guard one barcode held in frame would add dozens of lines to the cart.
		if (code === lastCode && now - lastAt < 1500) return
		lastCode = code
		lastAt = now

		if (navigator.vibrate) navigator.vibrate(40)
		onScan(code)
	}

	async function toggleTorch() {
		const track = stream?.getVideoTracks()[0]
		if (!track?.getCapabilities?.().torch) return
		torchOn.value = !torchOn.value
		try {
			await track.applyConstraints({ advanced: [{ torch: torchOn.value }] })
		} catch {
			torchOn.value = false
		}
	}

	function stop() {
		active.value = false
		if (raf) cancelAnimationFrame(raf)
		raf = null
		// Releasing every track is what turns the camera light off. Missing one
		// leaves the camera visibly running after the sheet closes.
		stream?.getTracks().forEach((t) => t.stop())
		stream = null
		detector = null
		busy = false
		// Cleared with the camera: a half-confirmed read from the last sheet must
		// not be completed by the first frame of the next one.
		candidate = null
		agreeing = 0
		torchOn.value = false
		if (video.value) video.value.srcObject = null
	}

	return { active, error, torchOn, torchAvailable, engine, start, stop, toggleTorch }
}
