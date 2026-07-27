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
	server: {
		fs: {
			allow: [path.resolve(__dirname, '..')],
		},
	},
})
