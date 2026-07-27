import { createRouter, createWebHistory } from 'vue-router'

const routes = [
	{
		path: '/',
		name: 'Sell',
		component: () => import('@/views/Sell.vue'),
	},
]

export default createRouter({
	history: createWebHistory('/pos'),
	routes,
})
