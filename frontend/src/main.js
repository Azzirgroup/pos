import './index.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { FrappeUI, setConfig, frappeRequest } from 'frappe-ui'

import App from './App.vue'
import router from './router'

const app = createApp(App)

setConfig('resourceFetcher', frappeRequest)

app.use(FrappeUI)
app.use(createPinia())
app.use(router)

// Mount first, hydrate boot after. The shell must paint even when the network
// is slow or the backend is down — a till that shows a blank screen because a
// boot call is hanging is worse than one running on stale defaults.
app.mount('#app')

/**
 * Register the asset-shell service worker.
 *
 * Production only: in `yarn dev` a worker caching hashed assets would serve
 * yesterday's build back after every edit.
 *
 * Registered at its own directory scope, which is all a worker served from
 * `/assets/…` is permitted. Asking for a wider scope throws a SecurityError
 * unless the server sends `Service-Worker-Allowed`, so this does not ask — the
 * assets get cached, and offline *navigation* waits for that header to exist.
 *
 * `updateViaCache: 'none'` matters more than it looks: this file is served
 * from the same `/assets/…` mount as the hashed build output, which the
 * server sends with a long `max-age` — correct for a file whose name changes
 * every build, wrong for this one, whose name never does. Without this
 * option, a browser can keep running yesterday's worker, cache-first-serving
 * hashes a new deploy already deleted, for as long as that header says —
 * surviving a normal reload. This forces every registration check straight to
 * the network regardless of that header, which is what actually makes a new
 * deploy take effect promptly.
 *
 * A plain runtime path, not `new URL(..., import.meta.url)`: the worker is
 * copied verbatim from `public/` and is not a module the bundler resolves, so
 * asking Rollup to trace it only produces a warning and the wrong URL.
 *
 * Failure is swallowed on purpose. A worker is an optimisation; a till that
 * refuses to start because caching is unavailable would be a much worse bug
 * than a slow first load.
 */
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
	window.addEventListener('load', () => {
		navigator.serviceWorker
			.register('/assets/cosmestics/frontend/sw.js', { updateViaCache: 'none' })
			.catch((e) => console.warn('[pos] service worker not registered:', e.message))
	})
}

// In `yarn dev` the page is served by vite rather than Jinja, so window.boot is
// absent and has to be fetched. Production gets it inlined by jinjaBootData.
if (import.meta.env.DEV && !window.boot) {
	Promise.race([
		frappeRequest({ url: '/api/method/cosmestics.www.pos.get_context_for_dev' }),
		new Promise((_, reject) => setTimeout(() => reject(new Error('boot timeout')), 3000)),
	])
		.then((data) => {
			window.boot = data
		})
		.catch((e) => {
			console.warn('[pos] dev boot unavailable, running with defaults:', e.message)
			window.boot = {}
		})
}
