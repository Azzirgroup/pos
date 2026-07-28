# Next up

Handoff notes.

## Done since the last handoff

### 1. The reorder list — not a bug

`FAIL reorder lists items` was the dev server's unauthenticated `PermissionError`
falling through to the empty state. Confirmed two ways:

- unauthenticated, `get_reorder_items` and `modules.inventory` (a screen that
  demonstrably works) fail identically over HTTP, so nothing is specific to
  reorder;
- through the real type-transforming call path it returns 28 items whose keys
  match exactly what `views/Reorder.vue` renders.

No change to `Reorder.vue`. What *was* wrong is that `smoke.py::_annotations`
only covered the till endpoints, so "the screen is empty" and "the endpoint 500s
at the HTTP boundary" were indistinguishable from the browser. Every whitelisted
endpoint the front end calls is now in that list.

### 2. Transactional documents hub — `/documents/:key`

Eleven document types through one generic set of endpoints in
`api/documents.py`. The differences are data in `DOCUMENTS`; the behaviour is
written once. Labels and render types are read from the DocType, so a field
relabelled in the desk relabels here.

- List with period / status / party / search filters and paging.
- Row actions — submit, cancel, amend, duplicate, print, WhatsApp. Which ones
  are live is decided server-side and sent as `actions_by_docstatus`, so the row
  menu and the modal cannot disagree.
- Tabs per type: **List · Insights · Reports**. Reports is `views/Reports.vue`
  itself, with `embedded` and `only` props narrowing it to that type's reports.

The registry key (`sales-invoice`) is the security boundary: a caller-supplied
string never becomes a doctype name. `smoke.py` asserts an unregistered key is
refused, and that every field the registry names still exists.

`POS Invoice` is registered and will be empty on a Cosmestics-only site — this
app posts Sales Invoices with `is_pos` set, and the Channel column is where till
sales show up. That is honest, not broken.

### 3. Row detail modals — `components/DocumentModal.vue`

Header fields, child tables, totals and the same actions as the row menu. Lines
render through `DataTable`, so they inherit the existing colour rules rather
than growing new ones. `utils/tone.js` gained one narrow rule —
`NEGATIVE_ONLY_KEYS` — because a positive line amount is the normal case and
painting every one green would make a page of ordinary rows look like good news.

### 4. Cards — icons and colour

`StatTiles.vue` takes `icon`, `tone`, `hint`, `delta` and `delta_good`. The
backend sends a stable icon *name*; `utils/icons.js` is the only file that knows
about Lucide. Colour stays secondary: the value is readable in monochrome, the
delta prints its sign, and an unknown icon name renders no icon rather than
breaking the tile.

### 5. Dashboard — `/dashboard`

`api/dashboard.py` plus `views/Dashboard.vue`: eight KPI tiles each carrying a
comparison against the preceding window of equal length, a daily revenue trend,
payments collected by tender, best sellers, and three "needs attention" lists
(below reorder, overdue, negative stock).

Charts are `components/charts/`. Colour rules live in `utils/palette.js`, kept
separate from `tone.js` on purpose: `tone.js` says whether a number is good,
`palette.js` says which series it is. The categorical order is fixed rather than
cycled, and the four slots were validated as a set against the surface they
render on. Every chart has a table view behind the toggle in `ChartCard.vue`,
because two of the four slots sit below 3:1 contrast on white and colour must
never be the only way to read a value.

**`/` still redirects to `/pos`.** The till stays the landing screen — a cashier
opening a bookmark on a slow connection should not first pay for a dashboard's
worth of SQL. The rail's Dashboard entry now points at `/dashboard`, which it
previously did not (it pointed at `/`, which bounced straight back to the till).
Moving the landing page is a one-line change in `router.js` if that is wanted.

### 6. Prices could not be updated from a selection

Two separate causes, both fixed:

- **The button lied.** `:disabled` checked the selection *and* the value; the
  label only mentioned the selection. Select three items, enter no value, and
  you got a button reading "Preview on 3 items" that did nothing when clicked.
  It now names what is missing. The emptiness test is no longer `=== ''` either
  — a cleared number input can hand back `null`, which slipped through and
  applied a change of zero that reported as success.
- **Read and write could pick different rows.** An item can carry several Item
  Prices on one price list (a different UOM, or a future `valid_from`). The
  screen read the newest; `apply_bulk_change` took whatever
  `frappe.db.get_value` returned. When they disagreed the price *was* updated —
  just not the one on screen, so it looked like nothing happened. Both now go
  through `pricing._current_price_rows()`. One item on this site already has two
  rows for one list, so this was live, not theoretical.

`apply_bulk_change` also reports `unchanged` now: "0 updated" alone reads as a
broken screen when it usually means the prices were already right.

### 7. Colour and row treatment across every list

`tone.js` covers the columns that were still monochrome — percent-complete
(`per_received` and friends), due and schedule dates, and the debt keys — and
the status vocabulary is matched on word boundaries instead of whole strings, so
ERPNext's compound statuses ("Partly Paid and Discounted", "To Receive and
Bill") stop coming out grey. Two deliberate limits:

- **Identity columns are never coloured.** An item name or a warehouse gets no
  tint; a page where everything is coloured is one where nothing stands out.
- **Text colour is only derived for `STATUS_KEYS`.** Matching status words
  anywhere would have tinted a customer called "Paid Ltd" green.

`cellTone(key, value, row)` now takes the row, because some rules cannot be
right without it: a due date is only late if something is still owed, and "every
past due date is red" would light up a paid-up customer's whole history.

Rows band (zebra) rather than relying on hairlines, hover is a step darker than
either band, and cancelled documents are dimmed. Row background is resolved to
one class string in `rowClass()` rather than via Tailwind's `odd:`/`even:`
variants — as separate utilities the stripe and the attention tint have equal
specificity, so the winner would have been stylesheet order. `Pricing.vue` and
`Reorder.vue` keep their own tables but were given the same treatment.

This also fixed an invisible hover: `hover:bg-surface-gray-1` on a page whose
background is `surface-gray-1` was a no-op on every full-page list.

### 8. Barcodes — `/barcodes`

`api/barcodes.py` mints a real **EAN-13** for stock that arrived without one,
writes it to the item's own `Item Barcode` table, and offers a printable label
sheet. The leading digit is **2**, the range GS1 reserves for a shop's own
items, so a generated code can never collide with one printed on a supplier's
carton.

The check digit is asserted in `smoke.py` against four published barcodes rather
than against this module's own arithmetic — a self-consistent implementation of
the wrong formula passes any test written from the same misunderstanding, and
the failure would only surface at a counter when a scanner refuses to beep.

The till needs no change: `catalog._barcodes` already serves `Item Barcode`, so
a generated code scans as soon as the catalog reloads. Note the list covers
`is_stock_item`, which includes raw materials — those get a code but will not
appear at the till, which only serves `is_sales_item`.

### 9. WhatsApp now uses the integration's real API

`notifications.py` called `whatsapp_integration.service.rest` — the low-level
transport — and reimplemented the reply parsing on top of it. That was the bug:
the bridge answers with several different shapes, and the stricter local reading
logged messages it had actually delivered as failures.

Everything now goes through `whatsapp_integration.api.whatsapp.whatsapp`:

- `send_quick_message_via_whatsapp` for text — adds phone normalisation and
  sender-account selection;
- `send_document_via_whatsapp` for documents, which attaches the **real PDF**
  rendered through the document's own print format. The documents hub sends
  that by default now, with the text summary as the caption. A customer sent an
  invoice should receive the invoice, not a paraphrase.
- `get_whatsapp_senders` so the send dialog can pick a sender.

`_succeeded()` now mirrors the integration's own interpretation exactly, and
`smoke.py` pins all eight response shapes. `service.rest` is kept only as a
fallback for installs predating the high-level module. Their `msgprint` is muted
so this app's toast is the only feedback.

**Worth knowing:** `send_document_via_whatsapp` publishes the PDF as a *public*
File so the bridge can fetch it. The URL is unguessable but not
access-controlled. That is the integration's design, not this app's, but it is a
real consideration for customer invoices.

## Conventions already established

- Colour rules live in `frontend/src/utils/tone.js` — extend, don't duplicate.
  Chart series colour is `utils/palette.js`; keep the two apart.
- Tables go through `components/DataTable.vue`, which already does status
  badges, numeric alignment and row tinting via `row.below` / `row.below_cost`.
- Module sub-tabs are data in `frontend/src/data/navigation.js`; every entry
  must have a matching route in `router.js`.
- `Select` from frappe-ui has **no `label` prop**, and silently drops options
  whose value is falsy. Use `FormControl type="select"`, and a real sentinel
  (`'__all__'`) for "All …" options.
- Whitelisted API arguments **must** carry type annotations — this site enables
  `require_type_annotated_api_methods`. `setup/smoke.py::_annotations` guards it,
  and now covers every endpoint the front end calls.
- Endpoints do **not** call `frappe.db.commit()`. Frappe commits a successful
  whitelisted POST on the way out, and committing inside puts the action beyond
  the reach of a smoke test that rolls back. (`api/pricing.py` and
  `api/reorder.py` still commit — that is why `_pricing` genuinely writes prices
  despite the rollback. Worth fixing.)

## Verifying

    bench --site <site> execute cosmestics.setup.smoke.run

Rolls back, safe against a live site. Currently 164/164. Add checks there for
anything new rather than testing by hand — three separate bugs reached the
browser because a test exercised a narrower path than the UI does.

## Still worth doing

- **Nothing here has been seen in a browser.** The backend is covered by the
  smoke test and the bundle builds, but no screen has been loaded on an
  authenticated site. Do that before trusting the layouts.
- **`tone.js` has no automated coverage.** There is no JS test runner in this
  repo and adding one would be a second verification path alongside
  `bench execute`. The status vocabulary was written against the `status`
  options actually declared by the eleven registered DocTypes, but nothing
  stops it drifting.
- `api/pricing.py` and `api/reorder.py` commit inside the endpoint; the smoke
  test's "nothing persisted" is not true for prices.
- `apply_bulk_change` writes with `ignore_permissions=True`, so anyone who can
  reach the screen can rewrite prices. Left alone deliberately — tightening it
  while fixing a "cannot update prices" report could only have made more things
  fail — but it should be revisited.
- The document hub has no bulk actions. Submitting twenty draft invoices is
  still twenty clicks. The same is true of barcodes across a large catalog:
  the list caps at 500 items.
- Charts are light-mode only — the app never sets frappe-ui's
  `[data-theme="dark"]`. Re-stepping for a dark surface is a change to
  `utils/palette.js` and nothing else.
