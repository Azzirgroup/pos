import { createApp } from 'vue'
import App from './App.vue'
import { addToCart, openCart } from './store'

/**
 * The shop's Vue layer. One app, mounted once; its pieces are teleported into
 * the places the server-rendered page leaves for them (header, product page,
 * checkout / account / order pages), plus the overlays (cart drawer, sign-in).
 */
// The server renders plain fallbacks into the spots the app fills (so the
// page works before, or without, the script). Clear them so the app replaces
// rather than duplicates them.
for (const sel of ['#cc-header-actions', '#cc-add', '#cc-page']) {
	const el = document.querySelector(sel)
	if (el) el.innerHTML = ''
}

const root = document.createElement('div')
root.id = 'cc-app'
document.body.appendChild(root)
createApp(App).mount(root)

// Buttons rendered by the server (product cards, "Cart" tab) work by delegation,
// so no card needs its own Vue instance.
document.addEventListener('click', (e) => {
	const add = e.target.closest('[data-add-to-cart]')
	if (add) {
		e.preventDefault()
		if (!add.disabled) addToCart(add.getAttribute('data-add-to-cart'), 1)
		return
	}
	if (e.target.closest('[data-open-cart]')) {
		e.preventDefault()
		openCart()
	}
})
