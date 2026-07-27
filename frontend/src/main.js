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
