import frappeUIPreset from 'frappe-ui/tailwind'

export default {
	presets: [frappeUIPreset],
	content: [
		'./index.html',
		'./src/**/*.{vue,js,ts,jsx,tsx}',
		'./node_modules/frappe-ui/src/**/*.{vue,js,ts,jsx,tsx}',
		'../node_modules/frappe-ui/src/**/*.{vue,js,ts,jsx,tsx}',
		'./node_modules/frappe-ui/frappe/**/*.{vue,js,ts,jsx,tsx}',
		'../node_modules/frappe-ui/frappe/**/*.{vue,js,ts,jsx,tsx}',
	],
	// No `!text-*`/`!bg-*` safelist here (unlike Frappe CRM). Every such class in
	// frappe-ui is a static literal that the content scanner above already picks
	// up, and safelisting the pattern generated ~36k unused rules — 97% of the
	// CSS bundle. A till on a slow connection pays for every one of them.
	theme: {
		extend: {
			// Touch-target floor for the counter: nothing tappable below 44px.
			minHeight: { touch: '44px' },
			minWidth: { touch: '44px' },
		},
	},
	plugins: [],
}
