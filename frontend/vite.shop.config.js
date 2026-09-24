import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

/**
 * The online shop's Vue layer — a separate build from the till.
 *
 * The shop's pages are rendered by Frappe (Jinja) so search engines and
 * WhatsApp link previews see real HTML. This bundle adds the interactive
 * parts on top: sign-in, the cart drawer, add-to-cart, checkout, M-Pesa and
 * order tracking. Plain Vue — no frappe-ui — so it wears the shop's own
 * stylesheet (templates/shop/shop.css), not the desk's.
 *
 * Fixed file names (shop.js / shop.css): the page adds ?v=<mtime> to bust
 * caches, so no manifest is needed.
 */
export default defineConfig({
	plugins: [vue()],
	// Not the till's public folder: its service worker and PWA icons belong to /pos.
	publicDir: false,
	define: { 'process.env.NODE_ENV': '"production"', __VUE_PROD_DEVTOOLS__: 'false' },
	resolve: { alias: { '@shop': path.resolve(__dirname, 'shop') } },
	build: {
		outDir: path.resolve(__dirname, '../cosmestics/public/shop'),
		emptyOutDir: true,
		cssCodeSplit: false,
		sourcemap: false,
		target: 'es2019',
		rollupOptions: {
			input: path.resolve(__dirname, 'shop/main.js'),
			output: {
				entryFileNames: 'shop.js',
				chunkFileNames: 'shop-[name].js',
				assetFileNames: 'shop.[ext]',
				inlineDynamicImports: true,
			},
		},
	},
})
