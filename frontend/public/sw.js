/**
 * Cache the app shell so a till on a bad connection still opens.
 *
 * ## What this can and cannot control
 *
 * A service worker may only control URLs beneath its own path. This one is
 * served from the built asset directory, so its scope is that directory — it
 * caches the JavaScript, CSS and icons, which is the great majority of the
 * bytes and the part that makes a cold load slow.
 *
 * It does **not** control `/pos` navigations, because nothing served from
 * `/assets/…` can. Widening the scope needs a `Service-Worker-Allowed: /`
 * header on this file, which is a web-server setting rather than something the
 * app can declare. Until that header exists, offline *navigation* will not work
 * even though the assets are cached.
 *
 * That limit is why this file is deliberately small: it does the part that
 * genuinely works and does not pretend to the part that does not.
 *
 * ## Strategy
 *
 * Cache-first for hashed build assets, because a hashed filename is immutable —
 * if the name matches, the bytes match, and there is no reason to revisit the
 * network. Everything else is left alone: API calls must never be served from a
 * cache, since a stale price or stock figure at a till is worse than a slow one.
 */

const CACHE = 'cosmetics-pos-v1'

/** Hashed build output — immutable, so safe to keep indefinitely. */
const IMMUTABLE = /\/assets\/cosmestics\/frontend\/assets\/.+\.(js|css|woff2?|png|svg)$/

self.addEventListener('install', (event) => {
	// Take over as soon as the new worker is ready rather than waiting for every
	// tab to close: a till is often left open for a whole day.
	event.waitUntil(self.skipWaiting())
})

self.addEventListener('activate', (event) => {
	event.waitUntil(
		(async () => {
			// Drop caches from previous builds; the hashed names mean nothing in an
			// old cache will ever be requested again.
			const names = await caches.keys()
			await Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n)))
			await self.clients.claim()
		})(),
	)
})

self.addEventListener('fetch', (event) => {
	const { request } = event

	// Only ever GET, and only ever the immutable build output. Anything else —
	// an API call above all — goes straight to the network.
	if (request.method !== 'GET') return
	if (!IMMUTABLE.test(new URL(request.url).pathname)) return

	event.respondWith(
		(async () => {
			const cached = await caches.match(request)
			if (cached) return cached

			const response = await fetch(request)
			// Only store a genuine success. Caching an opaque or error response
			// would pin a broken asset until the next deploy.
			if (response.ok && response.status === 200) {
				const cache = await caches.open(CACHE)
				cache.put(request, response.clone())
			}
			return response
		})(),
	)
})
