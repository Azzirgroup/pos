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
				/**
				 * **One vendor chunk, deliberately.**
				 *
				 * This first split frappe-ui, vue and the rest into separate chunks,
				 * which broke the app in production with
				 *
				 *     ReferenceError: can't access lexical declaration 'X'
				 *     before initialization       (frappe-ui Presence.js)
				 *
				 * frappe-ui and its own dependencies import each other. Put in
				 * different chunks that becomes a cycle *between chunks*, and the
				 * browser evaluates one before the other has initialised its
				 * bindings — a temporal dead zone error at load, on a screen that
				 * then never paints.
				 *
				 * Keeping every dependency in one chunk makes such a cycle
				 * impossible: it is all one module scope as far as the loader is
				 * concerned. The app still splits from the framework, which is where
				 * the caching win actually came from — a routine deploy re-fetches
				 * the app chunk, not Vue.
				 *
				 * Do not "optimise" this back into several vendor chunks without
				 * loading the built app in a browser. The build succeeds either way;
				 * only the runtime tells you.
				 */
				manualChunks(id) {
					if (id.includes('node_modules')) return 'vendor'
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
