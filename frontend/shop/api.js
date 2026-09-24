/**
 * Talking to the shop's endpoints (cosmestics.api.shop_*).
 *
 * Every call carries `X-Shop: 1` — the server refuses state-changing calls
 * without it, which is what stops another site posting to the shop with a
 * customer's cookie. If a staff member is signed in to the desk in the same
 * browser, Frappe also wants its CSRF token, which the page provides.
 */
const csrf = document.querySelector('meta[name="csrf-token"]')?.content

export class ApiError extends Error {
	constructor(message, status) {
		super(message)
		this.status = status
	}
}

function readError(data, status) {
	if (data?.message?.message) return data.message.message
	try {
		const msgs = JSON.parse(data?._server_messages || '[]')
		const last = msgs.length ? JSON.parse(msgs[msgs.length - 1]) : null
		if (last?.message) return strip(last.message)
	} catch (e) {
		/* fall through */
	}
	if (data?.exception) return strip(String(data.exception).split(':').slice(1).join(':')) || 'Something went wrong'
	if (status === 401) return 'Please sign in to continue'
	return status >= 500 ? 'The shop is having a moment. Please try again.' : 'Something went wrong'
}

function strip(html) {
	const d = document.createElement('div')
	d.innerHTML = html
	return (d.textContent || '').trim()
}

export async function call(method, params = {}, { post = false } = {}) {
	const url = `/api/method/cosmestics.api.${method}`
	const headers = { Accept: 'application/json', 'X-Shop': '1' }
	if (csrf) headers['X-Frappe-CSRF-Token'] = csrf
	let res
	try {
		if (post) {
			headers['Content-Type'] = 'application/json'
			res = await fetch(url, { method: 'POST', headers, body: JSON.stringify(params), credentials: 'same-origin' })
		} else {
			const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null))
			res = await fetch(`${url}?${qs}`, { headers, credentials: 'same-origin' })
		}
	} catch (e) {
		throw new ApiError(navigator.onLine ? 'Could not reach the shop. Try again.' : 'You are offline.', 0)
	}
	const data = await res.json().catch(() => ({}))
	if (!res.ok) throw new ApiError(readError(data, res.status), res.status)
	const msg = data.message
	if (msg && msg.ok === false) throw new ApiError(msg.message || 'Something went wrong', res.status)
	return msg
}

export const get = (method, params) => call(method, params)
export const post = (method, params) => call(method, params, { post: true })
