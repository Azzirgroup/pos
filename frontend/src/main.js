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
 * Failure is swallowed on purpose. A worker is an optimisation; a till that
 * refuses to start because caching is unavailable would be a much worse bug
 * than a slow first load.
 */
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
	window.addEventListener('load', () => {
		navigator.serviceWorker
			.register('/assets/cosmestics/frontend/sw.js')
			.catch((e) => console.warn('[pos] service worker not registered:', e.message))
	})
}

/**
 * Cache the build assets so a cold load on a bad connection is not a blank
 * screen.
 *
 * Registered without an explicit scope, so it takes the directory it is served
 * from — the built asset folder. That is all it can claim: a worker may only
 * control URLs beneath its own path, and widening it to `/pos` needs a
 * `Service-Worker-Allowed` header the app cannot set from here.
 *
 * So this speeds up loading and does not make the app work offline. Registering
 * with `{ scope: '/pos' }` would simply throw, which is worse than being clear
 * about the limit.
 *
 * Failure is ignored on purpose: an unregistered worker costs a slower load,
 * and a till must never fail to start over a cache.
 */
if ('serviceWorker' in navigator && import.meta.env.PROD) {
	window.addEventListener('load', () => {
		// A plain runtime path, not `new URL(..., import.meta.url)`: the worker is
		// copied verbatim from `public/` and is not a module the bundler resolves,
		// so asking Rollup to trace it only produces a warning and the wrong URL.
		navigator.serviceWorker
			.register('/assets/cosmestics/frontend/sw.js')
			.catch((e) => console.warn('[pos] asset cache unavailable:', e.message))
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
