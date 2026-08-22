# Next up

Handoff notes.

## Done since the last handoff

### 60. The Classic Cosmetics review

Seven things the shop asked for, in one pass. Nothing here is speculative — each
maps to a line in their review document.

**Three roles, this app's own.** `cosmestics/permissions.py` defines
`Cosmestics Purchase Manager`, `Cosmestics Store Keeper` and
`Cosmestics Analytics`; `install.ensure_roles` creates them on every migrate,
with `desk_access = 0` so handing one out does not hand out ERPNext. `System
Manager` holds all three implicitly, so a fresh site is never locked out.

**They have to be assigned before anything gated works.** Nobody but a System
Manager can post a purchase, confirm one, or open the dashboard until somebody
grants the roles in the desk. That is the intended state, and it is also the
first thing that will look like a bug.

**Purchasing is now a two-hand flow** — `cosmestics/api/buying.py` and a
rewritten `views/Purchasing.vue`. A manager posts a purchase; it saves as a
**draft** Purchase Invoice (`update_stock = 1`, nothing received, nothing
owed). A store keeper opens it, corrects the quantities against what actually
turned up, and confirms — and confirming is what *submits* it. The split is
enforced server-side: `update_purchase` lets a manager change anything and lets
a store keeper change **quantities only**.

`reopen_purchase` handles "the manager should be able to edit what was received
that day": ERPNext will not edit a submitted document, so it cancels and inserts
an amendment. **The name changes** (`…-1`) — anything that quotes a purchase
number to a supplier needs to know that.

**Two doors became one.** `documents.NOT_CREATABLE` now lists `purchase-invoice`,
and `_create_spec` refuses every key on that map — which covers `create_form`,
`link_options` and `create_document` in one place, so the hidden button and the
refused write cannot come apart. Raising a Purchase Invoice from the generic
document form used to submit on the spot, skipping the confirmation entirely.

**Deliveries opens on today.** The old rolling fortnight is still there behind
"Recent" — it is what catches a Friday drop nobody closed off — but the day is
now the view, with a pager either side of it. Rows open into a detail sheet, and
carry View / Edit / Label / Delete. The edit sheet is the only place a status can
be set freely (the row buttons still offer just the next legal move), which is
how a delivery marked delivered by mistake goes back to Pending.

`delete_delivery` refuses anything already dispatched — that is a record of a
rider leaving with a parcel and a message the customer has already had.

**Deliveries carry a customer name.** The doctype always had the field; nothing
asked for it, so a phone order typed in by hand read "Walk-in" on the worklist.

**Gone:** the Delivery Trips tab (the shop runs one rider, one parcel), and the
till's "Request material" button is now "Request for item".

## Older

### 59. `can't multiply sequence by non-int of type 'float'` on create

The *second* half of "creating a material request fails". Item 58 fixed a 500
raised after a successful save; this one is a real refusal to create, and the
two looked identical from the till.

Every value from `DocumentFormSheet` arrives as a **string**. An
`<input type="number">` bound with `v-model` yields one — Vue does not convert
it — and JSON carries it across unchanged, so a quantity of five reaches the
server as `"5"`. Frappe casts a document's fields to their fieldtype when it
*saves*, which is too late: `set_missing_values` runs first and reaches

    # erpnext/stock/get_item_details.py:532
    out.stock_qty = out.qty * out.conversion_factor

which is `"5" * 1.0`.

`documents._typed` now casts by the field's **declared registry type** before
the value reaches the document — the same data that draws the form, so nothing
doctype-specific is written into it, and it covers every creatable type at once
rather than only the one that was reported. Cast on the server and not in the
browser because this endpoint is reachable directly.

A value that will not parse is passed through **untouched, not zeroed**: `flt`
would turn a typo into 0, and a quantity that silently became nothing is far
worse than one ERPNext refuses by name.

`master._set_opening_price` had the same latent shape and now uses `flt`.

### 58. "Internal Server Error after save or submit" on a Material Request

Found and fixed. The request was being created correctly every time — the 500
came *after* it, from the notification hook, and it looked like a failure of the
thing that had just worked.

`on_material_request_submit` called

    frappe.enqueue(..., enqueue_after_commit=True)

inside a `try`, on the assumption that the `try` covered it. It does not.
`enqueue_after_commit` does not enqueue anything: it registers the call on
`frappe.db.after_commit`, which Frappe runs **after** the `COMMIT` statement,
long outside that function and outside any `except` it has. A Redis that is
down, full or unreachable therefore threw from inside `db.commit()` during
request teardown — with the Material Request already committed.

So `queue_material_request_notice` now registers a callback that does its own
enqueuing, wrapped. Same discipline for the two new notices. **If you add
another `enqueue_after_commit=True` anywhere in this app, its failure reaches
the user as a 500 on a document that saved.** Use the same shape.

### 57. The material-request notice carries the document, not a spreadsheet

The staff group used to get the table as text plus a CSV. A CSV opens in
nothing on a phone, which is where the group is read, so the attachment is now
the **PDF of the request itself** — the same thing the shop would have printed
and handed over.

Group sends could not attach a PDF before: `whatsapp_integration`'s document
send takes a `phone_number` and cannot address a group at all. `publish_pdf`
renders and publishes it (public, like the integration's own attachments — the
bridge fetches it over plain HTTP in a separate request), and `send_file`
already knew how to put a file into a group with `chat_id`.

The message names the requesting operator and the customer account as well as
the items, and both it and the print format are **configurable rather than
shipped**: `material_request_template` (Jinja, rendered with `doc`, `operator`,
`customer`, `items`, `link`) and `material_request_print_format` in POS
Settings. A template that throws falls back to the built-in wording and logs —
a message in the wrong words beats no message.

`Cosmetics Stock Request` is the print format the installer creates. It is
created **once and then left alone**, like the delivery label: a shop that has
adjusted its own wording should not have it reset on every migrate.

### 56. Stock balances beside the lines of a material request

A request is an argument that something is needed, made by somebody who cannot
see the shelf they are asking about — that is why they are asking. The form now
shows what the shop holds beside each line, red at zero and amber when the
quantity asked for exceeds it.

Declared by the registry (`"show_stock": {"warehouse_field": …}`), not by the
form component, so `DocumentFormSheet` still knows nothing about any particular
doctype. `stock.item_stock` is a new endpoint rather than the existing
`warehouse_qtys` because that one returns nothing when no warehouse is chosen,
and a Purchase request never has one — it answers "here" *and* "anywhere", which
are different answers ("none here but forty in the back" is not "none").

### 55. Deliveries are documents now

`Cosmestics Delivery` — one order, one address, one status — alongside the
existing `Cosmestics Delivery Trip`, which is the *run*. The distinction is the
whole design: a shop asking "what is going out today" is asking about drops, and
a child row on a trip cannot be listed, filtered or printed on its own.

Carries the seven fields the shop asked for: rider (a `Cosmestics Rider` link,
creatable from the field itself mid-sale), contact number pulled from the
customer and editable, address plus landmark plus an optional pin, courier, the
dispatch timestamp, the status, and the handling note.

Decisions worth keeping:

- **Not submittable.** The whole life of a delivery is its status moving, and a
  submitted document that must still change needs `allow_on_submit` on every
  field it has. Nothing here touches stock or a ledger — the invoice behind it
  did both — so a docstatus would be protecting nothing.
- **`dispatched_at` is stamped by the transition**, never typed. A time entered
  afterwards is the time somebody remembered, and the reason to record a
  dispatch is to be able to say how long a drop took.
- **The notice fires from `on_update`, not from the API.** A status changed in
  the desk therefore behaves exactly like one changed at the till.
- **Riders are their own tiny master.** Not a Supplier (a boda rider will never
  be billed) and not an Employee (needs a company, a joining date and a payroll
  answer the shop does not have).
- Sales create them **Pending**. Dispatching stamps a time and messages the
  customer, and neither should happen as a side effect of ringing up a sale.

`Cosmetics Delivery Label` is the carton slip — big, mostly address, with a
signature line, to replace writing on the box in marker pen.

### 54. Receivables came out of the closing sheet

`/credit`, on the till strip beside Delivery. It was a tab inside the sheet
whose primary action is "Close shift", so a cashier taking a payment
mid-morning was one mis-tap from ending the day — the same mistake that moved
Expenses out to its own page.

**A row is a customer, not an invoice.** Somebody walks in and says "I've come
to pay"; they do not know which invoice they mean and neither does the cashier.
Leading with invoices makes that a guessing game whose wrong answers scatter one
customer's payments across documents in no order, and the ageing report becomes
fiction.

So `credit.pay_customer` allocates **oldest first**, as the shop asked and as
ERPNext's own ageing assumes. One Payment Entry with several reference rows, not
one entry per invoice: the customer handed over one amount. Overpayment stays on
the entry as an unallocated advance and is reported rather than refused. The
sheet previews the split before anything posts, and a cashier who *does* know
which invoice they mean can still tap it and pay that one.

### 53. Three smaller things the shop asked for

- **Dashboard tiles stopped cutting numbers off.** `valueSize` shrank the figure
  but `truncate` was still on the element, so the smallest step was a floor
  rather than a fix and a seven-figure total still clipped on a two-column
  phone. It wraps now (`break-words`, so it splits between thousands groups). A
  tile one line taller is a nuisance; a revenue card that will not say what the
  revenue was is a bug.
- **Split payments list every tender, credit included.** The split rows named
  cash, the M-Pesa channels and card explicitly, so a shop's own modes (Bank
  Transfer, a voucher) could be a whole sale and not half of one — and the list
  went stale whenever the server's did. It reads `props.methods` now, with
  "On account (credit)" appended.
- **A reversal tells the customer.** `on_sales_invoice_submit` acts only on
  credit notes and messages the number on file, plus the manager. Amounts are
  printed positive and the method is named: a customer told "refunded" who then
  finds nothing in their hand is what naming cash-versus-account prevents.

### 52. `bench execute smoke.run` does **not** roll back everything

The docstring's promise — "Safe to run against a live site: the transaction is
always rolled back" — is false, and has been since the suite started closing a
shift. `close_shift` submits a POS Closing Entry, whose `on_submit` calls
ERPNext's `consolidate_pos_invoices`, which calls `create_merge_logs`, which
ends in `finally: frappe.db.commit()`. In Sales Invoice mode there is nothing to
merge — `closing_entry.pos_invoices` is empty — so the function loops over
nothing and commits anyway.

Everything created before that point is therefore permanent. Measured on a fresh
site: one run left **28 Sales Invoices, 6 POS Opening/Closing Entry pairs, 9
Journal Entries and 9 shift movements** behind. Proven directly — count
invoices, open a shift, sell, close, roll back, count again: one leaked.

This is not "prices only" (item 51's known `pricing.py` / `reorder.py` commits).
It is every document the suite raises up to the last `close_shift`. **Do not run
the suite against a live shop until this is fixed.** The likely fix is to stop
short of submitting the closing entry — build and validate it, then roll back —
since submitting is the one step whose side effects escape the transaction.

### 51. More than one cashier on a shift

ERPNext models a till shift as one person's: `POS Opening Entry` has a single
`user`, `check_open_pos_exists` allows one open entry per POS Profile, and
`POS Closing Entry.validate_sales_invoices` rejects any invoice whose `owner` is
not that person. The app already let a second cashier *sell* against a shared
shift (`_shared_open_shift`, and `_shift_invoices` dropping ERPNext's `owner`
filter) — but nobody had closed one, and it could not be done. The sales were
banked, the cashiers had gone home, and the drawer would not close.

**The roster.** `Cosmestics Shift Cashier` is a child table added to both POS
entries as the Custom Field `cosmestics_cashiers`. The opening entry declares who
is on the counter; the closing entry keeps a copy, because that is the document
somebody actually reads afterwards.

**One control, not two.** ERPNext's `user` cannot be removed — it is `reqd` and
read by the closing entry, the cancellation guard and every standard POS report —
so it is hidden by a Property Setter and *derived*: `before_validate` sets it to
the first roster row. Filling in the table is the whole interaction, in the desk
and at the till. Row order is therefore load-bearing; `_set_roster` puts the
opener first.

Three ERPNext checks are widened, via `extend_doctype_class` mixins in
`cosmestics/overrides/`:

| Check | Was | Now |
| --- | --- | --- |
| `POS Closing Entry.validate_sales_invoices` | `owner == self.user` | owner is on the roster |
| `POS Opening Entry.check_user_already_assigned` | the opener only | everyone on the roster |
| `POS Opening Entry.check_poe_is_cancellable` | the opener's sales | every sale on the shift |

Every other guard ERPNext applies is untouched and still runs. Both fall back to
`self.user` alone when there is no roster, so a site that never uses this is
unaffected by the override existing.

**A leak fixed on the way.** `_user_profiles()` asked "does this user have any
POS Profile User rows *anywhere*", so a user with none fell through to every
enabled profile on the site — the more carefully a shop listed its cashiers, the
more tills a new employee could reach. The test is now per profile: a profile
that lists users requires membership, one that lists nobody stays open to all.

**At the till**, the opening sheet gained an "Others on this till" picker, fed by
`shift.list_cashiers` and re-asked whenever the till changes, since two counters
can permit different staff. The closing sheet names who it is settling for.
`open_shift` validates the list server-side — a roster row is what lets somebody
settle money against this drawer, so an unchecked one would be a way onto any
counter.

Covered by `smoke.py::_shared_shift`: eight checks, ending in a two-cashier shift
that closes and a closing entry carrying both names.

**The desk picker is scoped to the till.** The child table's `user` is a plain
Link, so the grid offered every account on the site — Guest and the support login
among them — for the field that decides who may settle money against a drawer.
Worse than untidy: `_set_roster` refuses anyone the profile does not permit, so
the picker was suggesting answers the server would reject on save.
`shift.cashier_query` is now a search query filtered by the chosen POS Profile's
`applicable_for_users`, wired through `doctype_js` on both POS entries
(`public/js/pos_shift_cashiers.js`). Changing the till clears rows already
picked, since two counters can permit different staff. A profile that lists
nobody still offers every enabled System User — the same "open to anyone"
convention `_user_profiles` reads.

### 50. Selling by the dozen, and opening a shift honestly

**UOM at the till.** `get_catalog` now returns every unit an item may be sold
in, from ERPNext's own UOM Conversion Detail rows — nothing invents units. The
cart line carries the unit and its conversion factor, the rate is "per one of
these", and `submit_sale` passes both so ERPNext computes `stock_qty`. Verified
end to end: one Dozen at factor 12 posted `stock_qty=12`, moved 12 off the
shelf, and priced at 12× the base.

Three details that are load-bearing:

- **An explicitly priced unit wins over multiplication.** A shop that prices a
  dozen separately is doing so precisely because it is not twelve singles.
- **Lines merge only within the same unit.** A dozen and a single are different
  rates; merging them would silently reprice one.
- **`cartQtys` counts stock units, not line quantities.** The shelf check
  compares against the shelf — counting a dozen as "1" would let a cashier sell
  twelve of the last three with no offer to source them.

**Opening a shift offers every tender the till accepts**, from the POS Profile,
the same list closing will ask to be counted. It used to fall back to three
hard-coded names, so a float counted into M-Pesa Paybill had nowhere to be
declared at opening and the shift closed short by exactly that much with nothing
on screen explaining why. Switching till mid-form re-seeds the floats, since two
counters can take different tenders.

**Not done: a receipt from a Material Request.** ERPNext has no
`make_purchase_receipt` on Material Request — the path is MR → Purchase Order →
Purchase Receipt, and *both* need a supplier the request does not carry, because
a request says what is needed rather than who from. That makes it a form
(supplier, then create) rather than a menu item, which is what "open a modal for
editing" is really asking for. Worth building as `DocumentFormSheet` seeded from
the request; it is not a mapper call.

### 49. Documents carry forward

Every document in the hub now offers what it naturally becomes next, through
ERPNext's own mappers rather than anything assembled here — the mapper knows
which lines are still outstanding, what to carry over and what to write back to
the source, and a hand-rolled copy is exactly the thing that drifts on upgrade.

    Sales Invoice     → Payment Entry      Purchase Invoice → Payment Entry
    Delivery Note     → Sales Invoice      Purchase Receipt → Purchase Invoice
    Sales Order       → Delivery Note      Purchase Order   → Purchase Receipt
                      → Sales Invoice                       → Purchase Invoice
    Material Request  → Stock Entry

Everything lands as a **draft**. A payment moves real money and a transfer moves
real stock, and unlike a till sale nobody is waiting at a counter — the person
handing over the cash submits it, having looked.

Three things running them found, none of which reading would have:

- **A Payment Entry against a bank account is refused without a reference.**
  Prefilled with the invoice number and today; the real cheque or M-Pesa code is
  typed before submitting.
- **Material Request → Purchase Order cannot work at all.** The mapper leaves
  the supplier blank and it is mandatory — a request says what is needed, not who
  from. Dropped rather than shipped broken.
- **`stock_entry` was only ever tested against a *transfer* request.** On a
  purchase request it fails inside ERPNext with "Could not find Stock Entry
  Type: Purchase". Now refused by name, saying that a purchase request is filled
  by ordering and receiving.

The suite gained seven checks — and they were initially placed after the
sale-dependent early return, so they silently did not run on a site with no
sellable stock. Carrying a document forward has nothing to do with stock; they
run near the top now.

### 48. Deleting a company took the default with it

Two failures reported together after a demo company was removed by SQL.

**"Please specify Company" on a Purchase Invoice.** `documents._company()` read
only `frappe.defaults.get_global_default("company")` — a `tabDefaultValue` row
that names the company, and therefore a row deleted alongside it. With no
default, `create_document` left `company` unset and ERPNext threw from three
frames inside `get_item_details`, which says nothing about what to fix. It now
tries the user default, the global default, `Global Defaults.default_company`,
and finally the only company on the site when there is exactly one — a
single-company shop that never set a default is unambiguous. If all four come
back empty it throws naming the setting, rather than letting the failure surface
as a broken form.

**"Language is not a field this screen can fill."** `_linked_doctypes()` walked
POS settings and profile fields but not `USER_FIELDS`, and `User.language` is a
Link. The settings screen drew a picker whose options endpoint then refused the
doctype it had just asked for. Fixed by including User in the walk — worth
noting the allow-list and the form are now derived from the same tuples, which
is what stops this recurring.

### 47. Shorts: what nobody was posting

The deferred item, settled by checking rather than assuming. **A POS Closing
Entry writes no GL entries at all** — closing a shift 500 short produced an
empty ledger against the closing entry, and the Short movement referenced it
while posting nothing itself. So the cash was gone from the drawer and still on
the books, permanently. There was nothing to double-count and nothing to
reclassify: the short simply had to post its own Journal Entry, which it now
does.

**Two accounts, because they are two different facts.** A shortfall somebody is
named for goes to the **Till Short Account** on their POS Profile — a receivable
from staff, and per-profile because one branch can carry losses while another
writes them off. What nobody is named for goes to the **Unattributed Short
Account** in settings, which is a write-off. One account holding both answers
neither question at month end. Both refuse rather than guess when unset, and a
Receivable/Payable account is refused outright — it needs a party this app has
no way to supply.

**The invariant: the amounts always add up to the difference.** Before, naming a
person filed the *entire* mode shortfall against them, so two names on one mode
meant twice the money owed, and naming nobody recorded nothing at all. Now
stated amounts are honoured first, anyone named without one shares what is left
evenly — rounding remainder included, so 100 across three is 33.34/33.33/33.33 —
and whatever remains becomes one unattributed short. Over-attribution is refused
rather than scaled to fit, because scaling hides which figure was wrong.

**A test that committed.** The first version of this closed a real shift, and
submitting a POS Closing Entry commits — which broke the suite's "nothing
persisted" guarantee for everything that ran before it and left eight purchase
invoices on the site. The split is pure arithmetic, so it is tested directly
now, and the neighbour test picks a supplier name the site has not seen instead
of a fixed one that fails for ever after a part-committed run.

### 46. A batch of eighteen, from a walkthrough

Sixteen landed. Two things worth recording about the ones that did:

- **`PillTabs`** replaced frappe-ui's `TabButtons` on six screens. That control
  is a compact segmented pill with half-pixel gaps — right for a two-way toggle,
  cramped for six departments, and visibly a different control sitting beside
  our own spaced tabs.
- **A Today tab** (`dashboard.today`) ignores the period control on purpose.
  Every other tab answers "how is the month going"; this one answers "what is
  happening now", and a thirty-day average cannot. Windowed on `posting_date`,
  so a shift that opened before midnight does not drag yesterday into today.
- **Credit sales can be paid at the till** (`api/credit.py`). The payment is an
  ordinary Payment Entry, because that is what ageing and reconciliation read —
  but a Payment Entry is invisible to `get_closing_summary`, which sees POS
  payment rows and till movements and nothing else. So a **Credit Payment**
  movement is recorded beside it, in the same direction a neighbour refund goes:
  money in, expectation up by exactly that much. Verified against a live shift —
  expected cash 0 → 5000 on a 5000 part payment, then settled in full, then
  refused when already settled.
- **`shift_activity`** serves an open shift as well as a closed one, which is
  the case the closing entry cannot: there is no closing document to read, so
  the figures come from the same `get_invoices` the live screen uses. Open
  shifts show "Not counted yet" rather than "Balanced" — a shift nobody has
  counted has no difference, and printing one reads as a till that was checked.
- **Barcode on the item form** joins `opening_price` as a virtual field:
  `VIRTUAL_FIELDS` is now read by `master.py` *and* by the smoke test, so adding
  a third cannot make the test fail for the wrong reason. A duplicate barcode is
  refused rather than left for ERPNext to raise — the same number on two items
  makes every scan of it ambiguous.

**Not done: multi-person shorts and their accounts.** Attribution across several
people is straightforward; the accounting is not. ERPNext's POS Closing Entry
already posts the reconciliation difference somewhere, so charging a named
person's account from here would **double-count it** unless it is a
reclassification of what that entry posted — which needs the account it actually
used, per site. Shipping that unverified is worse than not shipping it. What it
needs: a short account on POS Profile, a company-level account for the
unattributed remainder, `close_shift` taking `[{mode, person, amount}]` instead
of one name per mode, and a probe that proves the ledger nets to the difference
and not to twice it.

### 44. Saved quotes threw on render

`v-for` sat on the quote row button, and the Print/WhatsApp strip below it —
which reads the same `q` — sat *after* the closing tag, outside the loop. It
rendered once against a `q` that does not exist there and died with

    TypeError: can't access property "name", q is undefined

as soon as there was a single saved quote to list. Both are wrapped in one
element per quote now. **The build never had a chance of catching this**: the
template compiles perfectly, `q` is just an undefined lookup at runtime.

### 45. Speed: the round trip, not the query

Measured before changing anything. Warm server timings on this site:

    catalog.get_catalog        91 ms      dashboard.overview     112 ms
    modules.sales              13 ms      documents.list         18 ms
    shift.get_open_shift       11 ms      modules.purchasing     13 ms

Nothing there is worth optimising — the queries are already set-based and there
are no N+1s left. The cost a cashier in Nairobi actually feels is the *round
trip* to Frankfurt, a few hundred milliseconds, paid again every time a tab is
opened, including the tab that was open ten seconds ago.

So `data/cache.js` does **stale-while-revalidate** over a named list of read
endpoints: a cached answer returns immediately, a fresh one is fetched behind
it, and the screen corrects itself within one round trip. It also deduplicates
identical in-flight reads, so two components asking at once make one request.

Three rules, all load-bearing:

- **The list is explicit.** The cost of a wrong guess is asymmetric — a stale
  dashboard is a non-event, a stale drawer total is a cashier deciding on a
  number that is not true. Nothing under `pos.*`, `shift.*`, `returns.*` or
  `sourcing.*` is on it.
- **Anything not on the list is treated as a write and empties the cache**,
  including on failure. Invalidating by doctype instead would need a second map
  of which endpoint touches what, and the first missing entry serves stale data
  with no clue why.
- **Nothing that feeds an editable table is cached** (`pricing.get_prices`,
  `master.list_records`). A cache hands every caller the same object, so a
  screen mutating a row in place would rewrite what the next screen reads.

Separately, the till's own start-up was three requests in two sequential
awaits with no dependency between them; it is one `allSettled` now, one round
trip shorter, and still independent — a failed payment-methods lookup must not
cost the shift.

### 43. The price preview is where prices are edited

"One value for all items" was the whole model: pick a percentage, preview it,
apply it. That gets a supplier's brand-wide increase right and nothing else —
most of a brand goes up 8% and two lines go somewhere else, and the only way to
say that was three separate bulk runs.

The preview is now the working surface. Every "Now" cell is an input, the change
column and the below-cost warning recompute as you type, and an edited row can
be put back with one tap without discarding the rest. **Type each price** opens
the same table with nothing changed, for the case where there is no single
figure to apply at all — it runs the same endpoint at 0%, so cost and margin
come back resolved exactly as they do for a bulk change rather than through a
second code path.

Two details that matter more than they look:

- The typed value is held as a **string** and converted once, in the computed.
  Coercing on each keystroke rewrites the field under the cursor, so "12."
  becomes "12" and the decimal is unreachable.
- Apply sends **only the rows that differ**. Sending all of them had the shop
  told "3 updated, 47 already at that price" after editing three prices, which
  reads as though something went wrong.

### 42. A deploy under an open tab looked like a broken app

Every screen is a lazily imported hashed chunk, so a rebuild renames all of
them. A till left open across a deploy is running an index chunk that asks for
`Masters-BB8x8YCo.js` when the server now has `Masters-wNK3hWmT.js`, and the
navigation dies with "error loading dynamically imported module" — the tab looks
broken to a cashier who did nothing wrong, and the fix is a hard reload nobody
would guess.

**The report that followed it — "Items opens outside the app" — was a different
bug entirely, and a real one.** `/items` is the only route that names its record
type in `meta` rather than in the URL, and `Masters.vue` decided "nothing is
chosen" by looking for a `:key` route param. So arriving at Items immediately
`router.replace`d to `/masters/customer`: out of Inventory, onto Records, showing
customers. It now reads both, and only the bare index redirects.

`router.onError` now catches that one class of error and reloads. **In place,
not to the route that failed**: the first attempt navigated to
`` `/pos${to.fullPath}` ``, which means building the app's own base by hand, and
the report that came back was "it leaves the app". A reload cannot leave, the
address bar never changed, and the tap works the second time. A session flag
stops it looping, so a genuinely missing chunk still fails visibly.

Every stat tile now carries an icon — the ones written in the front end were the
ones without, because the server-built tiles have had them since they were
written. `utils/icons.js` gained `store`, `location` and `wallet`.

### 41. Seven things the shop asked for after using it

From a marked-up walkthrough. Small individually; three of them changed shared
components, so they landed everywhere at once rather than screen by screen.

- **The blue bulk-price button is black and bold.** `font-bold` alone did
  nothing: frappe-ui puts `font-medium` on the Button's size class and Tailwind
  emits `.font-medium` *after* `.font-bold`, so the override needs `!font-bold`.
  Checked in the built CSS rather than assumed — this is the failure mode where
  the build is green and the screen is unchanged.
- **Counts read green.** `cellTone` now takes the column's declared type,
  because `Number('500')` is a whole number whether it is five hundred shillings
  or five hundred bottles and nothing else could tell them apart. Money keeps
  the full vocabulary; a count is green when there is some and muted at zero.
  Stock on the shelf joined them — it was the only count left deliberately
  plain, which made a column of black cells with two red ones look like the
  absence of a rule. `reserved_qty` left `STOCK_KEYS` on the way past: zero
  reserved is the ordinary state, and amber on a column of zeroes is noise.
- **The stat tiles are framed in violet.** Violet is the one hue the status
  vocabulary does not use, so tinting every tile costs nothing — a red figure
  inside a violet card still reads as the exception. More gap, more padding.
- **Tile icons are coloured chips** rather than grey outlines, toned in
  agreement with the number above them.
- **The module tabs and master chips are spaced out** and the active one is
  violet. Same control in two files; both changed so they still match.
- **The hold button undoes itself.** With items in the cart it holds; with an
  empty cart and a held ticket it brings the last one back. The mistake it
  fixes happens with a customer at the counter, so the recovery has to be the
  control they just pressed, not a list of tickets to go and find. Ticket
  numbering became a counter on the way: it was `held.length + 1`, which went
  backwards on resume and handed a live ticket's number to the next hold —
  and `resume` takes the first match, so the wrong cart could come back.

### 38. Sending stock back next door, and getting the money

`return_to_neighbour` could send the goods back but had nothing to say about the
money, which is the half a cashier actually asks about. It now takes a
`refund_method`:

- **`account`** nets it off what we owe them. This needed one non-obvious flag:
  ERPNext defaults `update_outstanding_for_self` to 1, so the debit note carried
  its own negative outstanding and the original purchase still read as fully
  owed — the shop next door appearing to be owed money for goods back on their
  own shelf until somebody ran a payment reconciliation. Set to 0, the two net.
  ERPNext flips it back itself when the return is worth more than is still owed,
  which is the one case where netting cannot work.
- **`cash`** is them handing the money over the counter. The return is marked
  paid through a Mode of Payment, and a **`Neighbour Refund`** movement tells the
  open shift that cash came *in*.

`refund_mode` is the Mode of Payment, and that is deliberately the only thing
asked: the account follows from the Mode of Payment Account mapping every other
payment in the app already uses. `returnable()` offers only modes that have an
account mapped on the company — the rest would fall back to the default cash
account and quietly book an M-Pesa refund as notes in the drawer.

Cash is refused where there is no cash to give back: a purchase still on the tab
has none, and taking it anyway leaves the drawer over with nothing to explain it.
`returnable()` says so before the cashier picks, rather than throwing on submit.

**A third movement direction.** `PAID_OUT_TYPES` gained a sibling,
`CASH_IN_TYPES`, and `_paid_out_by_mode` — the one function both the closing
summary and `close_shift` read — now returns a *net* figure. Amounts stay
positive on the record; the type carries the direction, so validation can keep
refusing zero and below and a movement always reads as "this much moved".

`record_movement` still refuses `Neighbour Refund` from the client. The server
raises it through `post_movement`, alongside the return invoice that justifies
it — otherwise anyone with till access could add cash to the drawer's
expectation out of nothing.

Verified against a real shift: buy 100 paid → expected cash −100; return it for
cash → back to 0, ledger showing cash out then cash back, stock in then out, and
creditors netted. Eleven checks added to `smoke.py`.

### 39. A neighbour purchase marked paid was paying nothing

Found while building the refund. ERPNext leaves `paid_amount` to the desk form's
JavaScript, so `is_paid=1` set from the server submitted an invoice that
reported itself as paid, booked **no payment entry at all**, and — because
`is_paid` suppresses the outstanding update — left `outstanding_amount` at the
full total. The shop appeared to owe money it had already handed over, and the
cash never left the ledger.

Both `_make_purchase_invoice` and the cash refund now compute totals first and
set `paid_amount` explicitly. This is why `can_cash` can be trusted: it is
`grand_total − outstanding`, which was previously always zero.

### 40. The account refund said no after the fact

`ReturnSheet.vue` offered "On account" on every sale and let the server refuse it
on submit — and most till sales are walk-ins, where a credit is one nobody can
ever claim. `returnable_sale` now returns `can_credit` and `credit_reason`, the
button is disabled with the reason under it, and the sheet lands on Cash rather
than on an option that cannot be used.

### 33. Material requests never reached the WhatsApp group

Reported as "the group is configured but nothing arrives". Nothing in the chain
was missing — the hook fires, the job runs, the bridge answers. **One field was
wrong, in an app this one does not own.**

`whatsapp_integration/service/rest.py` builds its payload as
`{"number": to_number, …}`. waclient treats `number` as a phone number and
expects a group to arrive as **`chat_id`**. So a group JID sent that way is
never routed: the reply comes back with no `data`, and the integration logs

    WhatsApp Text API Error — Unexpected message format: None

which is what the Error Log on the affected site showed, against
`_enqueued_material_request_notice`. Item 26 recorded that `/api/send` accepts
`chat_id`; nothing had acted on it.

`notifications._send_to_group` now posts to waclient directly with `chat_id`,
and `send_to_staff_group` routes by the target: anything ending `@g.us` is a
group, anything else keeps going through the integration, which handles phone
normalisation and sender selection properly.

Two things came with it:

- **`notifications.status()`** — can this site deliver at all, and if not, which
  of the four reasons is it. Each needs a different fix, so they are reported
  separately rather than as one "not configured".
- **`notifications.send_material_request(name)`** — the retry. A queued job that
  failed left a shop nothing to do: the request is already submitted and cannot
  be submitted again.

**The till used to lie about it.** `request_transfer` reported success and the
toast said "sent to WhatsApp" unconditionally, when the message is only *queued*
after submit and on an unconfigured site goes nowhere. It now says either
"posting to the staff group" or names the reason nobody will see it.

Worth knowing: the two sites behave differently. `kaysalt.com` does not have
`whatsapp_integration` installed at all, so nothing sends there regardless;
`classiccosmetics.frappe.cloud` does, and is where the `chat_id` bug bites.

### 34. Returns, both directions

A customer bringing goods back is a sale running backwards, so it is a Sales
Invoice with `is_return=1` — `api/returns.py`. The refund route is the only real
decision and it changes the accounting, so it is the cashier's:

- **Cash** creates the credit note as a *POS* invoice inside the shift with a
  negative payment row. `get_closing_summary` sums the payment rows of every POS
  invoice in the window, so the expected drawer falls by exactly the refund with
  no separate movement — one would double-count it. Verified: 2000 → 1750 on a
  250 refund.
- **Credit** leaves it on the customer's account, and refuses a walk-in. A
  refund sitting against the shared walk-in customer is one nobody can claim.

`api/sourcing.py` gained the mirror for neighbours — a return Purchase Invoice
rather than a cancellation, because the goods genuinely were received and for a
while were on our shelf. Both sides track what has already gone back per line,
so two returns cannot exceed what was sold.

**`create_sales_return` crashed on a Lead.** `quotation_to` was hardcoded to
`"Customer"` while `party_name` took whatever the till passed, and this site has
the CRM app — so a Lead reached the field through ordinary use and died on
`Could not find Party: CRM-LEAD-…`, a link error naming a record that exists in
a different doctype. `_resolve_party` now derives the type from the record.

### 34. Speed — the N+1s

Three, all confirmed by counting statements rather than by eye:

- `shift.list_recent_shifts` ran `_movements()` **per shift**. Fifty shifts meant
  fifty round trips to draw one table — the page got slower the more history a
  shop had, which is backwards. `_movements_for()` does it in one.
- `customers.search` ran `_outstanding()` **per customer**, and that search fires
  as the cashier types. Twenty round trips per keystroke, at a counter.
- `dashboard.warehouses` called `_stock_position()` twice inline — once for a
  tile's value and again for its tone — running four SQL statements to render
  one number.

Query count is now **constant in the row count**: 6 for 25 shifts or for 5, 3 for
20 customers or for 5. Warm timings: shifts 5 ms, customer search 3 ms,
dashboard overview 31 ms.

### 35. The bundle splits — app from vendor, and no further

Everything was one ~536 kB chunk whose hash changed on any edit, so a one-line
Vue fix made every till re-download Vue, the router and frappe-ui. `manualChunks`
now puts **all** of `node_modules` in one vendor chunk, and a routine deploy
re-fetches the **43 kB app chunk** alone.

**It was first split four ways — vendor / vue / frappe-ui / scanner — and that
broke production.** The build succeeded; the app then died on load with

    ReferenceError: can't access lexical declaration 'X' before initialization
    …  frappe-ui Presence.js

frappe-ui and its own dependencies import each other. In separate chunks that is
a cycle *between chunks*, so the browser evaluates one before the other has
initialised its bindings — a temporal dead zone error, on a screen that never
paints. One chunk makes the cycle impossible, because it is a single module
scope as far as the loader is concerned.

The split that mattered was always app-from-framework; sub-dividing the
framework bought almost nothing and cost the app. Verified after the fix by
walking the emitted chunks' import graph: the vendor chunk imports no other
chunk, and there is no cycle among the 32.

**Do not re-split vendor without loading the built app in a browser.** This
failure is invisible to `yarn build` and to the smoke test — both pass.

### 36. Installable, with generated icons

`manifest.webmanifest` plus real PNGs at 192/512 (both plain and maskable), a
180px Apple touch icon and a 32px favicon — drawn pixel-by-pixel in Python and
downsampled 4x, because this machine has no rasteriser and no image library. An
SVG is there for anywhere vector art is taken.

**The service worker only caches assets.** It is served from the built asset
directory, and a worker may only control URLs beneath its own path — so it
cannot control `/pos` navigations. Widening it needs a `Service-Worker-Allowed: /`
header on that file, which is a web-server setting rather than something the app
can declare. So this speeds up loading and does **not** make the app work
offline. Registering with `{ scope: '/pos' }` would simply throw.

Frappe will not serve a `.js` file from `www/` at all — it is in
`UNSUPPORTED_STATIC_PAGE_TYPES` — so there is no in-app route that would fix the
scope either.

### 37. The app is called Cosmetics

Everything a person reads — app title, browser tab, top bar, error-log title,
README. Deliberately *not* renamed: the Python package, the module, and the two
DocTypes (`Cosmestics POS Settings`, `Cosmestics Shift Movement`), which hold
live data and key the asset path. So error messages naming those DocTypes keep
the old spelling **on purpose** — they point at a record that still exists under
it. A full rename is a maintenance-window job; see "Still worth doing".

### 27. Money that moves at the till without being a sale

Four of the six outstanding items were one change, because they all say the same
thing: cash leaves the drawer for reasons `get_invoices` knows nothing about. A
till expense, cash handed to the shop next door, a shortfall with somebody's name
against it. Each is another term in "what should be in the drawer", and that
expression is written in exactly two places — so it was changed in exactly two
places.

**`Cosmestics Shift Movement`** is the new DocType. One record per movement,
`movement_type` distinguishing them, because the closing screen has to add them
all up in one place; three doctypes would have meant three things to forget.

- `get_closing_summary` now computes `expected = opening + taken − paid_out`,
  and reports `paid_out` per mode rather than only applying it. A cashier asked
  to produce less than the sales say is owed the reason on the same line.
- `close_shift` subtracts the same term onto ERPNext's `payment_reconciliation`
  rows. Both had to move or the closing entry would disagree with the summary
  the cashier just approved.

**A short is the exception, and deliberately so.** It is excluded from
`paid_out`: a short is *discovered* by counting, so subtracting it from the
expectation would make the count agree with itself and the discrepancy would
vanish at the exact moment it was being recorded. It is attributed after the
closing entry submits, and only for modes that are genuinely short — a name
typed against a mode that then balanced is dropped rather than filed as a debt
that does not exist. An overage is never attributed; a surplus is not somebody's
debt and asking whose it is invites a guess.

**Only an expense posts its own ledger entry** — a Journal Entry debiting the
expense account and crediting the drawer, because the cash is genuinely gone and
a till that reconciles against a figure the general ledger does not know about is
a difference somebody chases at month end. A neighbour purchase is already a
Purchase Invoice written by `sourcing.receive_from_neighbours`; posting a second
document for the same money would double-count it, so that record only tells the
closing screen the cash left.

The till gained a **Shifts tab** in place of Held (which kept its toolbar button
and its count — the tab was a second door to the same sheet). Behind it: Count,
Money out, and Neighbours.

**Unpaid neighbour purchases** are modelled on `_credit_summary`, which already
solved the identical problem for credit sales — reported as their own block
rather than folded into the expected amounts, windowed on `creation` and not
`posting_date`. They are a debt this counter opened and nothing else in the app
surfaced them again.

**Sourcing now asks whether you paid.** Off by default: neighbouring shops
usually settle weekly, and a payment recorded that never happened leaves the
drawer short by exactly that much. `submit_sale` splits sourced lines by that
flag, because `paid` applies to a whole invoice — booking them together would
either invent a cash movement or hide one.

### 28. Running short mid-cart is the same decision as being out

The out-of-stock sheet used to open only when stock was already zero, so the
common case — six of the last two — failed at submit with the customer already
paying. The check is now against what the cart *would* hold, at every entrance:
the grid, the cell quantity control, and the `+` beside a cart line.

That last one needed `CartPanel` to stop writing to the store directly. It was
bound to `cart.inc`, which meant the control most likely to push a quantity past
the shelf count was the one that never asked. It emits upward now, so the
decision lives where the sheet does.

The sheet opens pre-filled with the **gap**, not with one — a cashier short by
four should not have to work that out under a queue — and says which of the two
situations they are in, since the fix differs.

### 29. A part-payment no longer requires finding the split screen

`canComplete` demanded `tendered >= total` for cash, so taking 400 of a 1000 bill
— the most ordinary thing that happens at a counter — left the button grey with
no explanation. The only way through was a split screen the cashier had no reason
to open.

Partial is now expressed the same way on every path: `owing` is computed for all
of them, anything left owing needs a named customer, and the customer picker
appears in the same place with the same wording whether or not a split is
involved. M-Pesa and card still settle exactly, because the amount is whatever
the machine took; a shortfall on those is entered as a split.

The backend already handled this correctly — verified directly, 400 cash + 200
M-Pesa against a 1000 bill leaves 400 outstanding — so nothing there changed.

The pay sheet also gained a **back button**, which steps out of split mode before
it closes the sheet. Closing outright would discard a tender already keyed in,
which is the one thing a back button must never do.

### 30. Settings — `/settings`

Three tabs: the shop's till configuration, the POS Profile behind this till, and
the signed-in user's own details. None of these are new settings; they were in
the desk, which is a place a shop manager either cannot reach or will not find.

Fields, labels and link targets are read from the DocTypes, so this screen cannot
describe a field that no longer exists. Writes are **allow-listed** rather than
passed through — the same boundary as `documents.py` and `master.py` — and
`link_options` is scoped to the doctypes these fields actually point at, because
a generic version would be a way to read any table on the site.

`assign_profile` is the one-tap fix for "no POS profile available", which is the
single most confusing thing the till can say. It refuses to remove the last user
from a profile: on ERPNext an empty user list means *everyone*, so removing the
last name silently widens access instead of narrowing it.

### 31. Row actions and WhatsApp share on every list

`DataTable` grew an `actions` prop and draws the trailing menu column itself, so
a list gains row actions by passing a function and changing nothing else.
`useRowActions` composes the message from **the columns the list is already
rendering** — same labels, same formatting, same filters — because a summary
rebuilt from raw fields would quietly show a different set of numbers than the
one being pointed at.

Sharing carries the real PDF where the row is a document (Sales, Purchasing) and
plain text where it is not (stock, accounts, reports, master data). Reorder keeps
its own table so it gets the list-level share only — which is the one that
matters there, since that list *is* a buying list. List shares cap at 20 rows and
say so: a silently truncated list reads as the complete answer.

### 32. Dashboard lists no longer scroll inside a page that scrolls

`DataTable` takes `scroll`, and the dashboard's cards pass `false`. They had a
`max-h` wrapper around a table that already owned its own scrolling, inside a
page that scrolled too — three bars and no indication which moved what. The
sticky header follows the same flag, since pinned inside a page-level scroller it
would sit against the top of a card that had already scrolled past. `items-start`
on the grids stops a three-row card being stretched to match a twelve-row one.

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

### 20. Modals were painting *under* the page

frappe-ui portals its Dialog to `<body>` but gives the overlay **no z-index at
all**, and `#app` sets none either — so `#app` never becomes a stacking context
and every positioned element inside it competes with the modal in the root
context. A sticky table header at `z-10` therefore painted straight over an open
dialog.

`index.css` now states the order once:

    ≤ 40  page chrome (sticky table headers, tab strips)
      50  bottom sheets and tooltips
      60  dialogs        (.dialog-overlay)
      70  toasts         (.pos-toast)

Toasts sit *above* dialogs deliberately: a toast reports what the dialog just
did, so it has to be readable while the dialog is still open. Every ad-hoc
`z-50` on a toast was replaced with the named `.pos-toast` class, so the scale
lives in one file rather than being re-guessed per screen.

### 21. Receipt prompt after a sale

An optional modal offering the receipt, with the invoice, the total and the
change or balance owed. It opens *after* the cart has cleared, so the next
customer can already be served behind it, and dismissing it loses nothing —
the sale is posted either way and the toolbar keeps a Receipt button.

"Stop asking on this till" is remembered in `localStorage`, per browser rather
than per user: whether there is a printer attached is a property of the counter,
not of the person standing at it.

### 22. Material requests were fetching correctly — nothing was raising them

There were zero Material Requests on the site, at every window and with the
company scope removed. What had no coverage at all was `stock.request_transfer`,
the only thing in the app that creates one — only its annotations were checked,
so "none are showing" and "the button that makes them is broken" looked the same.

It works. What did not was the list of branches to request *from*:
`catalog._warehouses` offered every non-group warehouse, which on this site meant
per-customer van warehouses and Work In Progress. It now offers only warehouses
that hold stock — a location with nothing in it cannot supply anything. Smoke
raises a real transfer request and asserts it then appears in the documents hub.

### 23. Item cards carry a picture

The item's own image where it has one, and a category-matched icon where it does
not (keyword-matched on group and brand, since every shop names its groups
differently). Kept to a 32px square, with the availability dot moved into its
corner so the two share one column: this grid earns its speed from density, and
a photo the layout is built around would cost more than it returns.

### 24. Master data has a home — `/masters`

It existed before as a "+ New" button beside the avatar, which is not a place to
add master data; it is a button you have to already know about. There is now a
**Records** entry in the rail with a screen per type, listing what already exists
with search alongside the create form. A create-only screen is how a shop ends up
with the same customer three times — and this site already has 997 customers.

### 25. Nine document types can be raised in the app

Sales Invoice, Purchase Invoice, Purchase Receipt, Delivery Note, Stock Entry and
Stock Reconciliation joined Sales Order, Purchase Order and Material Request. The
shared line spec is `_lines()`, written once so nine forms cannot drift apart.

Some carry a `hint` shown above the form, for the cases where the document does
something a reasonable person would guess wrong — a Stock Reconciliation *sets*
the balance rather than adding to it, and a Stock Entry wants From blank for a
receipt and To blank for an issue.

**Five types deliberately have no New button**, and now say so on screen instead
of just lacking one:

| Type | Why not |
|---|---|
| POS Invoice | ERPNext's offline till document; this app posts Sales Invoices |
| POS Opening / Closing Entry | Created by opening and closing a shift, so they reconcile against what was counted |
| Payment Entry | Raised against an invoice, so the money lands on the right one |
| Landed Cost Voucher | Spreads cost across receipts that already exist |

`smoke.py` asserts every registered type either creates or explains why — a
screen with no button and no reason is the thing that looks broken.

The test for this initially failed five of nine, because it hardcoded
`transaction_date` while the new types use `posting_date`. It now seeds each
payload from the form's own defaults, which is what the browser sends — so the
test exercises the same path the UI does rather than a narrower one.

### 26. Fetching WhatsApp groups from waclient

The bridge documents `GET https://waclient.com/api/get_groups` taking
`instance_id` and `access_token` — the same pair `/api/send` already uses. There
is also `GET /api/get_channels`, and `/api/send` accepts **`chat_id`** as an
alternative to `number`, which is the correct field for a group JID rather than
passing it as a phone number.

`notifications.list_groups()` calls it and normalises the reply to `[{id, name}]`.
The envelope varies — `data`, `groups`, or a bare list, with the JID under `id`,
`jid`, `chat_id` or nested in `id._serialized` — so the shape is discovered the
same way `_succeeded` treats send replies, and `smoke.py` pins six of those
shapes including two that must yield nothing.

The point is to stop anyone having to paste `120363012345678901@g.us` into
settings by hand. That is not a value a shop manager can find or verify, and a
wrong one fails by delivering nowhere at all.

**It cannot run on this site yet.** `whatsapp_integration` is in the app list and
its Python imports fine, but **its DocTypes were never installed** — there is no
`Whatsapp Settings` DocType and no Whatsapp Integration Module Def, so there is
nowhere for the credentials to live and every send has been failing at
`frappe.get_single("Whatsapp Settings")`.

To fix on the site:

    bench --site kaysalt.com install-app whatsapp_integration
    # then set instance id + access token in Whatsapp Settings

`smoke.py` previously asserted only that the package was *importable*, which
reported this site as healthy. It now checks that availability is reported
honestly and skips the rest with a reason rather than passing checks it cannot
really run — the same failure mode as the reorder investigation.

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

Rolls back, safe against a live site. Currently 347/347 — *when the site has
sellable stock*. It reports `5/5` and a SKIP line when nothing in the selling
warehouse has ten units of a `is_sales_item` item, which is site state, not a
regression: the whole sale-dependent half of the suite is skipped. Check the
SKIP line before reading a small pass count as a small suite.

Two failures this suite reported turned out to be **site state, not code**, and
both are worth recognising if they come back:

- A shift left open from a previous day. ERPNext refuses an `is_pos` invoice
  against an outdated opening entry, so the till cannot sell — and it fails at
  submit, after the customer has paid. `get_open_shift` now reports `outdated`
  and the till says so before anything is rung up.
- An active Workflow on Customer (from another app on the site) blocked customer
  creation, which breaks quick-add *and* credit sales. The test names it rather
  than dying on it. Add checks there for
anything new rather than testing by hand — three separate bugs reached the
browser because a test exercised a narrower path than the UI does.

## Still worth doing

- **The service worker's scope.** One `Service-Worker-Allowed: /` header on
  `/assets/cosmestics/frontend/sw.js` turns the asset cache into genuine offline
  capability and satisfies Chrome's install criteria. It is an nginx line, not
  an app change.
- **The app rename is half done, deliberately.** Everything visible says
  Cosmetics; the package, module and two DocTypes still say Cosmestics. Finishing
  it means renaming two tables that hold live records, the site's
  `installed_applications`, and the `/assets/cosmestics/` path — a maintenance
  window with a database backup, not a mid-session edit.
- **`sales_returns` and `neighbour_returns` reports existed before the returns
  themselves did.** They now have a creating path; worth remembering that a
  report is not a feature.
- **Nothing here has been seen in a browser.** The backend is covered by the
  smoke test and the bundle builds, but no screen has been loaded on an
  authenticated site. Do that before trusting the layouts. The shift sheet's
  three tabs and the settings screen are the two worth looking at first — they
  are the largest pieces of new markup and neither has been rendered.
- **The M-Pesa channels are still all mapped to the default bank account** (see
  item 16). Till expenses credit whichever account the mode resolves to, so
  splitting them properly matters more now than it did: an expense taken against
  a mode pointing at the wrong account books the cash out of the wrong place.
- **A neighbour purchase recorded from "Money out" does not link to its invoice.**
  It records that cash went to a named supplier, which is what the drawer needs,
  but settling last week's invoices this way leaves those invoices showing unpaid.
  Paying against the invoice is a Payment Entry and belongs in the documents hub.
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
