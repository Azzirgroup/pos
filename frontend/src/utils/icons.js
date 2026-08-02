/**
 * Icon names the backend is allowed to send.
 *
 * The server decides what a tile *means* ("this is money", "this needs
 * attention"); it must not decide which icon set renders it. So endpoints send
 * a stable name and this file is the only place that knows about Lucide — swap
 * icon libraries and nothing in Python changes.
 *
 * An unknown name resolves to null and the tile renders without an icon, which
 * is the right failure: a missing picture is not worth a broken screen.
 */

import LucideAlert from '~icons/lucide/triangle-alert'
import LucideBan from '~icons/lucide/ban'
import LucideBoxes from '~icons/lucide/boxes'
import LucideCart from '~icons/lucide/shopping-cart'
import LucideClipboard from '~icons/lucide/clipboard-list'
import LucideFile from '~icons/lucide/file-text'
import LucideHourglass from '~icons/lucide/hourglass'
import LucideLandmark from '~icons/lucide/landmark'
import LucideLocation from '~icons/lucide/map-pin'
import LucideLock from '~icons/lucide/lock'
import LucideMoney from '~icons/lucide/banknote'
import LucidePackage from '~icons/lucide/package'
import LucidePencil from '~icons/lucide/pencil'
import LucideReceipt from '~icons/lucide/receipt-text'
import LucideScale from '~icons/lucide/scale'
import LucideTrendingUp from '~icons/lucide/trending-up'
import LucideTruck from '~icons/lucide/truck'
import LucideUndo from '~icons/lucide/undo-2'
import LucideUnlock from '~icons/lucide/lock-open'
import LucideStore from '~icons/lucide/store'
import LucideUsers from '~icons/lucide/users'
import LucideWallet from '~icons/lucide/wallet'

const ICONS = {
	alert: LucideAlert,
	ban: LucideBan,
	boxes: LucideBoxes,
	cart: LucideCart,
	clipboard: LucideClipboard,
	file: LucideFile,
	hourglass: LucideHourglass,
	landmark: LucideLandmark,
	location: LucideLocation,
	lock: LucideLock,
	money: LucideMoney,
	package: LucidePackage,
	pencil: LucidePencil,
	receipt: LucideReceipt,
	scale: LucideScale,
	store: LucideStore,
	'trending-up': LucideTrendingUp,
	truck: LucideTruck,
	undo: LucideUndo,
	unlock: LucideUnlock,
	users: LucideUsers,
	wallet: LucideWallet,
}

/** Accepts a name or an already-resolved component, so callers can pass either. */
export function resolveIcon(icon) {
	if (!icon) return null
	return typeof icon === 'string' ? ICONS[icon] || null : icon
}
