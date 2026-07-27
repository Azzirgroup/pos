import { ref, shallowRef } from 'vue'

/**
 * Barcode scanning through the phone camera.
 *
 * Uses the native `BarcodeDetector` API, which Chrome on Android implements on
 * top of Google's on-device scanner. That is deliberately the only backend: it
 * is far faster and more tolerant of blur and angle than a JS/WASM decoder, and
 * it costs nothing in bundle size. Safari and Firefox do not implement it, so
 * `supported` is false there and the caller shows the HID-scanner hint instead.
 *
 * Camera access needs a secure context (HTTPS or localhost). On plain HTTP
 * `getUserMedia` is undefined, which is reported as a permission problem rather
 * than left as a silent no-op.
 */

// Formats a cosmetics shop actually encounters. Narrowing the list measurably
// speeds up detection versus asking for every symbology.
const FORMATS = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39', 'itf', 'qr_code']

export function detectorSupported() {
	return typeof window !== 'undefined' && 'BarcodeDetector' in window
}

export function secureContextOk() {
	return typeof window !== 'undefined' && Boolean(navigator.mediaDevices?.getUserMedia)
}

export function useCameraScanner(onScan) {
	const active = ref(false)
	const error = ref(null)
	const torchOn = ref(false)
	const torchAvailable = ref(false)
	const video = shallowRef(null)

	let stream = null
	let detector = null
	let raf = null
	let lastCode = null
	let lastAt = 0

	async function start(videoEl) {
		error.value = null

		if (!detectorSupported()) {
			error.value = 'unsupported'
			return
		}
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
					// making each detect pass expensive.
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

		detector = new window.BarcodeDetector({ formats: FORMATS })
		active.value = true
		loop()
	}

	async function loop() {
		if (!active.value || !video.value) return

		try {
			const codes = await detector.detect(video.value)
			if (codes.length) emit(codes[0].rawValue)
		} catch {
			// A transient decode failure is normal between frames; keep scanning.
		}

		raf = requestAnimationFrame(loop)
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
		torchOn.value = false
		if (video.value) video.value.srcObject = null
	}

	return { active, error, torchOn, torchAvailable, start, stop, toggleTorch }
}
