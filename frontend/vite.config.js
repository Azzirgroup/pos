import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import frappeui from 'frappe-ui/vite'
import path from 'path'

export default defineConfig({
	plugins: [
		frappeui({
			frappeProxy: true,
			lucideIcons: true,
			jinjaBootData: true,
			buildConfig: {
				indexHtmlPath: '../cosmestics/www/pos.html',
				emptyOutDir: true,
				sourcemap: true,
			},
		}),
		vue(),
	],
	resolve: {
		alias: {
			'@': path.resolve(__dirname, 'src'),
			// Demo catalog shared with the Python installer, so the seeded site and
			// the UI demo can never drift apart.
			'@data': path.resolve(__dirname, '../cosmestics/data'),
		},
	},
	optimizeDeps: {
		// The `frappe-ui` barrel reaches a handful of CJS-only packages (grid
		// layout → interactjs, socket.io → debug, TextEditor → prosemirror).
		// Vite's scanner doesn't discover them through the dependency, so in dev
		// they fail as `does not provide an export named 'default'` and the app
		// never mounts. Pre-bundling converts them to ESM up front. The
		// production rollup build resolves the interop on its own.
		include: [
			'feather-icons',
			'tailwind.config.js',
			'interactjs',
			'socket.io-client',
			'debug',
			'prosemirror-state',
			'prosemirror-view',
			'lowlight',
		],
	},
	build: {
		rollupOptions: {
			output: {
				/**
				 * Split the framework away from the app.
				 *
				 * Not to reduce the bytes — the same code is downloaded either way
				 * on a cold load — but to stop a deploy invalidating all of it.
				 * Everything lived in one ~536 kB chunk whose hash changed on any
				 * edit, so fixing one line of a Vue file made every till re-download
				 * Vue, the router and frappe-ui over a shop's connection.
				 *
				 * Split this way the vendor chunk changes only when a dependency
				 * does, which is rarely, and a normal deploy re-fetches the app
				 * chunk alone.
				 */
				manualChunks(id) {
					if (!id.includes('node_modules')) return
					// The decoder is already lazily imported and is large; keeping it
					// out of vendor means a desktop till on a USB scanner never
					// fetches it at all.
					if (id.includes('zxing-wasm')) return 'scanner'
					if (id.includes('frappe-ui')) return 'frappe-ui'
					if (
						id.includes('/vue/') ||
						id.includes('vue-router') ||
						id.includes('/@vue/') ||
						id.includes('pinia')
					) {
						return 'vue'
					}
					return 'vendor'
				},
			},
		},
	},
	server: {
		fs: {
			allow: [path.resolve(__dirname, '..')],
		},
	},
})
