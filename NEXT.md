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

### 10. Till fixes

- **M-Pesa is three channels, not one.** Send Money, Paybill and Withdraw settle
  into different accounts, so booking them all against one Mode of Payment left
  the shift unable to reconcile. Three new fields in Cosmestics POS Settings,
  each falling back to the generic M-Pesa mode when blank — a shop that has not
  filled them in must still be able to sell. The till asks "how did it come in?"
  only after M-Pesa is chosen, because that is the order the cashier knows it in.
- **Receipts.** `pos.receipt_url` renders through ERPNext's print engine, so the
  receipt carries the letterhead and tax lines and matches what the desk prints.
  The button appears after a sale and names the invoice.
- **Stock count on item cards.** The dot said "low" but never how low.
- **Shift, branch and warehouse in the header**, from `session.context()`. The
  warehouse resolution deliberately mirrors `submit_sale`, and `smoke.py` asserts
  the two agree — a header claiming one warehouse while the sale draws from
  another is worse than showing nothing.
- **Tenders come from the server** (`pos.get_payment_methods`). A shop with no
  card machine was previously offered a Card button that threw when pressed.

### 11. Buy from neighbour — a setup gap, not a code bug

The `Neighbour Shop` supplier group exists on this site but contains **zero
suppliers**, so the till had nothing to offer and the feature looked dead.
`catalog` now returns a `sourcing` block saying which of the two it is
(unconfigured vs. configured-but-empty), and `smoke.py` asserts that block
agrees with the neighbour list. **To actually enable it: add the shops you buy
from as Suppliers in the `Neighbour Shop` group.**

### 12. Dashboard tabs — `/dashboard`

Overview (charts) plus five department tabs: **Sales** (filter by branch),
**Branches**, **Warehouses** (filter by warehouse), **Procurement**,
**Accounts**. The five all return `{stats, sections}` and share one renderer, so
a sixth department is an endpoint and a tab entry, not another screen.

**A branch is a POS Profile.** Every till sale already carries `pos_profile`, so
this needs no new field on any document and cannot disagree with what the shift
screens report. Sales with no profile are reported under "Not on a till" rather
than dropped — off-till invoices are real revenue, and excluding them silently
would make the branch totals disagree with the sales tab.

Procurement answers the "where do material requests go" question: the requests
section carries a **Goes to** column (`set_warehouse`), and the
received-but-not-billed section surfaces payables that are otherwise invisible.

### 13. Master data quick-add — the "New" button in the header

`api/master.py` covers Customer, Supplier, Item, Warehouse and Account. It is
deliberately **not** a reimplementation of ERPNext's forms: each type exposes the
fields a shop actually fills in, everything else is left to ERPNext's defaults,
and the confirmation links to the desk for the rest. A partial form that gets
finished beats a complete one nobody does, and it cannot drift.

As in `documents.py`, the registry key is the boundary — no caller-supplied
string becomes a doctype name. Link options are fetched per field so each
dropdown is scoped to what that field can hold; a generic "search any doctype"
endpoint would be a way to read any table in the system.

Smoke asserts every declared field exists on its DocType, and that a supplier
created in the neighbour group actually reaches the till.

### 14. Recent sales at the till

`pos.recent_sales` plus a sheet on the till. Defaults to this cashier's own
sales — "did that go through?" is almost always about the sale just rung up, and
everyone else's invoices bury it. Tapping a row reprints its receipt.

### 15. An intermittent checkout failure, and how to see it coming

One smoke run failed inside `submit_sale` with:

    'SalesInvoice' object has no attribute 'posa_delivery_charges'

Nothing in this app was wrong. posawesome reads that custom field on every Sales
Invoice, and the field existed in the database while the **cached DocType meta**
did not yet contain it — so the controller's attribute access died on submit,
after the customer had paid. A later run passed.

`smoke.py::_custom_fields_visible` now compares declared Custom Fields against
the cached meta for the sales doctypes, so this shows up as a named failure
instead of a mystery at the counter. **The fix when it happens is
`bench --site <site> clear-cache`.** This is the most likely explanation for the
reported "error when I complete the sale".

### 16. The M-Pesa channels are real Modes of Payment

`M-Pesa Send Money`, `M-Pesa Paybill` and `M-Pesa Withdraw` are now created by
the installer as separate Mode of Payment records, each mapped to a company
account and added to every POS Profile's payment methods. Three settings fields
point at them, so a shop can retarget any channel at an account it already
reconciles against.

They are separate records, not three labels on one, because a shift that cannot
tell them apart cannot be reconciled — the money is in three different places
and the closing entry would see one number. The opening-float screen now lists
each channel, deduplicated, so a cashier is never asked to count the same drawer
twice.

`after_migrate` runs `setup_prerequisites()`, so existing sites get them on the
next `bench migrate` — no patch needed.

**One thing to finish by hand:** all three are mapped to the company's default
bank account, because that is the only safe automatic choice. Point each at its
own account (the till wallet, the paybill account, the agent float) and the
shift will reconcile them separately, which is the whole point of splitting
them.

### 17. Buying from a neighbour can no longer fail

Two changes, because the old behaviour refused the purchase — and therefore the
sale — when the shop next door was not already a Supplier:

- The installer seeds one real neighbour (`Neighbour Shop (Walk-in)`) so the
  list is never empty, but only when the group has no suppliers of its own.
- `sourcing._ensure_supplier` now **creates** an unknown shop in the neighbour
  group instead of throwing. The customer is at the counter and the goods have
  already changed hands; refusing because nobody filled in a master list
  beforehand blocks a sale that has, in every practical sense, happened. The
  list fills itself in as the shop actually trades.

### 18. The shift chip updates when the shift does

The header loaded the till context once on mount, so opening a shift left it
reading "No shift" until a reload. It now comes from `stores/till.js`, which the
till screen refreshes after opening or closing — the two components that care
are not related, so shared state was the fix rather than prop-drilling. A failed
refresh deliberately leaves the last known value on screen rather than blanking
the chip.

### 19. Creating documents in the app

Sales Order, Purchase Order and Material Request can now be raised with their
lines, saved as a draft or submitted. It runs off the same registry as
everything else: a type becomes creatable by gaining a `create` block describing
its header and its lines, and `components/DocumentFormSheet.vue` renders
whatever the server declares. **Nothing about any specific doctype is written in
the front end** — making a fourth type creatable is a registry entry and no
change to any Vue file.

Decisions worth keeping:

- **Rate is left blank by default.** The server runs ERPNext's own
  `set_missing_values`, so a line prices itself from the price list. Typing a
  rate overrides that — which is what you want when a supplier quotes something
  different, and not what you want by accident.
- **Draft is the primary button, submit is secondary.** Submitting is the
  irreversible one; a purchase order raised in a hurry is usually worth a second
  look before it reaches the supplier.
- **Material Request lines inherit the destination and date from the header.**
  ERPNext validates both per row, but asking twice on a form this small is
  noise. `line_from_header` in the registry expresses that, and smoke asserts
  the inheritance actually lands on the line.
- Only fieldnames the form declared are copied onto the document, so a value the
  browser was never offered cannot be smuggled in. Link options are scoped to
  the field being filled, as in `master.py`.

Smoke creates all three for real, reads them back, and checks the lines survived
and were priced. It does **not** assert a rate on Material Request lines: a
request asks for stock to be moved or bought and carries no rate, so asserting
one would be testing a fact about ERPNext that is not true. (It did, at first,
and failed — which is the check working.)

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

Rolls back, safe against a live site. Currently 251/251. Add checks there for
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
