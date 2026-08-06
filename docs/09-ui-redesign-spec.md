# 09 — UI Redesign Spec (execute against the running app)

**Goal:** replace the current technical-looking UI with a professional, seamless one
that a bookkeeper would trust with client books. The **visual source of truth** is the
reference mockup embedded at the bottom of this file — extract it to
`docs/ui-reference.html`, open it, and match it. This spec tells you the tokens,
components, screen structures, and — most important — the backend rule that makes it
feel finished.

## The #1 rule: names, never IDs or raw internals
The current UI leaks internal values (account IDs like `23`, raw JSON, un-formatted
numbers). **Users must never see an ID.** Everywhere a mapping/account/item/location is
shown, resolve it to its human name.

- Build a **resolution layer** (`app/services/resolve.py`): given a connection, fetch and
  cache display names — QBO **Account** names (query `select Id, Name, AccountType from Account`),
  **Item** names, and Square **location** names. Cache on the `connections`/`mappings` rows
  (add `display_names` JSON) refreshed on connect + daily.
- `mappings` should store, per slot, both the id (for posting) and the resolved **name + type**
  (for display). Templates render the name + a type chip, never the id.
- Add Jinja filters: `money` ( `$2,507.75`, negatives `−$17.77` in red, `tabular-nums` ),
  `acct(slot)` → resolved name, `acct_type(slot)` → Income|Liability|Expense|Bank.
- **Acceptance:** grep every template — no bare numeric id is ever rendered to a user; the
  Day detail and Mapping screens show only account names + type chips.

## Design tokens — drop into the base stylesheet
Use these exactly (validated palette). Put them in `:root` in the app's base CSS/template
so every screen references roles, not raw hex.
```css
--page:#f4f4f2; --surface:#ffffff; --surface-2:#fcfcfb;
--ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
--line:rgba(11,11,11,.09); --line-2:rgba(11,11,11,.06);
--brand:#12314f; --accent:#2a78d6; --accent-wash:#eaf1fb;   /* brand color is swappable in one place */
--good:#0ca30c; --good-wash:#e8f6e8; --good-ink:#0a7a15;
--warn:#b7791f; --warn-wash:#fdf3dd;
--crit:#d03b3b; --crit-wash:#fbe9e9;
--r:12px; --shadow:0 1px 2px rgba(11,11,11,.04),0 4px 16px rgba(11,11,11,.05);
```
- **Type:** `system-ui, -apple-system, "Segoe UI", sans-serif`. No serif/display face.
  Money & table numerics use `font-variant-numeric: tabular-nums`; hero/stat values use
  proportional figures.
- **Spacing:** 4px base; cards padded 18–20px; 14px gaps in grids; generous whitespace.
- **Radii:** 12px cards, 9px buttons/inputs, 20px pills. **Shadow:** the soft `--shadow` only.

## Components (build each as a reusable partial/macro)
1. **App shell** — left **sidebar** (brand mark + nav: Dashboard, Reconciliation, Connections,
   Account mapping, Clients, Settings) on `--brand`; **top bar** with an **org switcher**
   (also the bookkeeper's client-switcher) + help + avatar. Content max-width ~1080px.
2. **KPI stat tile** — label (uppercase, muted) · value (25px, 700) · meta line (with a green
   `▲ x%` delta or a tie-out check). Row of 4.
3. **Status pill** — icon/dot + label, never color alone. `Posted`=good, `Needs review`=warning,
   `Syncing`=accent. Reserve status colors; never reuse for anything decorative.
4. **Data table** — uppercase muted headers, hairline row rules, hover wash, right-aligned
   `tabular-nums` money columns, negatives red. Rows clickable → day detail.
5. **Sparkbars** — thin bars, 3px rounded tops, 6px gaps, `--accent`, hover title. (Daily sales.)
6. **Connect card** — brand logo tile + name + description + a **connected state** (green check +
   what's connected) or a primary **Connect** button. Plus a 3-step progress strip and a trust
   footer (encryption · read-only · disconnect anytime).
7. **Receipt/statement** (day detail) — line rows each with a bold label + a muted
   `→ Account Name (type)` sub-line; subtotal + grand-total rules; a green reconciliation strip
   ("Matches your Square deposit of $X exactly").
8. **Mapping table** — Square activity → resolved account name + type chip + Edit link.
9. **Buttons** — primary (`--accent`, white), ghost (surface + hairline). **Type chips** —
   Income (blue), Liability (violet), Expense (orange), Bank (green) washes.

## Screens → existing templates
Rebuild each current template to the mockup:
- **Dashboard** (`/`) — greeting; 4 KPI tiles (Net sales MTD, Sales tax collected, Tips payable,
  Deposits reconciled X/Y with tie-out); daily-sales sparkbars; "Recent days" table. Show the
  **Needs review** state when a day has one — it's the core value moment.
- **Day detail** (`/days/{date}`) — statement layout (component 7) with account-name sublines and
  the reconciliation strip. No raw JSON (keep a "view raw payload" behind a dev-only toggle).
- **Connections / onboarding** (`/connect`) — component 6. The OAuth redirect stays, but the UX is
  the Plaid/Stripe pattern: connected cards, 3-step strip, "auto-matched N accounts", trust footer.
  A not-yet-connected card shows a single primary **Connect** button.
- **Account mapping** (`/mapping`) — component 8; names + type chips only; the "tax = exactly what
  Square collected" reassurance line.
- **Settings** — connection status (reconnect), deposit/fee prefs, plan.

## Interaction & a11y
- Status meaning always carries an icon/label, not hue alone (colorblind-safe).
- Money right-aligned and tabular; dates human ("Mon, Jul 27").
- Keyboard focus states on nav/rows/buttons; row hover; responsive down to tablet.
- Keep htmx actions (dry-run/run/re-run) but style them as ghost buttons in the day view.

## Definition of done
1. All five screens match `docs/ui-reference.html` in layout, spacing, and color.
2. No user-facing screen shows a numeric ID or raw JSON (dev toggle excepted).
3. Account/item/location names are resolved via the resolution layer and cached.
4. `money`/`acct`/`acct_type` filters used everywhere; negatives red; tabular numerics aligned.
5. Status pills use icon+label; brand color lives in one CSS variable.
6. Existing tests still pass; add a template test asserting no bare mapping id renders on Day detail.

---

## Appendix — reference mockup (extract to `docs/ui-reference.html`)
The complete, self-contained reference UI. Save the block below as `docs/ui-reference.html`
and match it screen-for-screen.

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DailyLedger — pro UI mockup</title>
<style>
:root{
  --page:#f4f4f2; --surface:#ffffff; --surface-2:#fcfcfb;
  --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
  --line:rgba(11,11,11,0.09); --line-2:rgba(11,11,11,0.06);
  --brand:#12314f; --brand-ink:#0f2740; --accent:#2a78d6; --accent-wash:#eaf1fb;
  --good:#0ca30c; --good-wash:#e8f6e8; --good-ink:#0a7a15;
  --warn:#b7791f; --warn-wash:#fdf3dd; --crit:#d03b3b; --crit-wash:#fbe9e9;
  --r:12px; --shadow:0 1px 2px rgba(11,11,11,.04),0 4px 16px rgba(11,11,11,.05);
}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);
  font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
.app{display:grid;grid-template-columns:232px 1fr;min-height:100vh}
/* ---- sidebar ---- */
.side{background:var(--brand);color:#cdd7e2;padding:20px 14px;display:flex;flex-direction:column;gap:4px}
.brand{display:flex;align-items:center;gap:10px;color:#fff;font-weight:700;font-size:16px;padding:6px 10px 18px}
.brand .logo{width:26px;height:26px;border-radius:7px;background:linear-gradient(135deg,#3d8bfd,#2a78d6);
  display:grid;place-items:center;color:#fff;font-weight:800;font-size:15px}
.nav{display:flex;align-items:center;gap:10px;padding:9px 10px;border-radius:9px;color:#c3cdd9;
  cursor:pointer;font-weight:500;font-size:13.5px}
.nav:hover{background:rgba(255,255,255,.06);color:#fff}
.nav.active{background:rgba(255,255,255,.12);color:#fff}
.nav .ic{width:16px;height:16px;opacity:.9}
.side .foot{margin-top:auto;padding:10px;border-top:1px solid rgba(255,255,255,.1);font-size:12px;color:#93a1b2}
/* ---- topbar ---- */
.main{display:flex;flex-direction:column;min-width:0}
.top{height:60px;background:var(--surface);border-bottom:1px solid var(--line);
  display:flex;align-items:center;justify-content:space-between;padding:0 24px;position:sticky;top:0;z-index:5}
.orgsw{display:flex;align-items:center;gap:9px;padding:7px 12px;border:1px solid var(--line);border-radius:9px;
  font-weight:600;cursor:pointer;background:var(--surface-2)}
.orgsw .dot{width:22px;height:22px;border-radius:6px;background:#e7dfd2;display:grid;place-items:center;font-size:12px}
.top .right{display:flex;align-items:center;gap:16px;color:var(--ink-2)}
.avatar{width:30px;height:30px;border-radius:50%;background:#dfe6ef;color:#33506f;display:grid;place-items:center;font-weight:700;font-size:12px}
/* ---- tabs (mockup nav) ---- */
.tabs{display:flex;gap:4px;padding:14px 24px 0;background:var(--page)}
.tab{padding:8px 14px;border-radius:8px 8px 0 0;font-weight:600;font-size:13px;color:var(--muted);cursor:pointer}
.tab.active{color:var(--ink);background:var(--surface);box-shadow:var(--shadow)}
.wrap{padding:22px 24px 40px;max-width:1080px}
.view{display:none}.view.active{display:block}
h1{font-size:20px;margin:0 0 3px;letter-spacing:-.01em}
.sub{color:var(--ink-2);margin:0 0 20px;font-size:13.5px}
/* ---- cards ---- */
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);box-shadow:var(--shadow)}
.card.pad{padding:18px 20px}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:18px}
.kpi{padding:15px 16px}
.kpi .lab{color:var(--muted);font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.03em}
.kpi .val{font-size:25px;font-weight:700;letter-spacing:-.02em;margin-top:7px}
.kpi .meta{font-size:12.5px;color:var(--ink-2);margin-top:4px;display:flex;align-items:center;gap:5px}
.up{color:var(--good-ink);font-weight:600}
/* ---- table ---- */
table{width:100%;border-collapse:collapse}
th{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:600;
  text-align:left;padding:11px 14px;border-bottom:1px solid var(--line)}
td{padding:12px 14px;border-bottom:1px solid var(--line-2);font-size:13.5px}
tr:last-child td{border-bottom:none}
tbody tr{cursor:pointer}
tbody tr:hover{background:var(--surface-2)}
.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.date b{font-weight:600}.date span{color:var(--muted);font-size:12px;margin-left:6px}
.neg{color:var(--crit)}
/* ---- pills ---- */
.pill{display:inline-flex;align-items:center;gap:6px;padding:3px 9px 3px 7px;border-radius:20px;
  font-size:12px;font-weight:600;line-height:1.4}
.pill .d{width:6px;height:6px;border-radius:50%}
.pill.ok{background:var(--good-wash);color:var(--good-ink)}.pill.ok .d{background:var(--good)}
.pill.rev{background:var(--warn-wash);color:var(--warn)}.pill.rev .d{background:var(--warn)}
.pill.sync{background:var(--accent-wash);color:#1c5cab}.pill.sync .d{background:var(--accent)}
.tie{display:inline-flex;align-items:center;gap:5px;color:var(--good-ink);font-weight:600;font-size:12.5px}
.tie svg{width:14px;height:14px}
/* ---- sparkbars ---- */
.spark{display:flex;align-items:flex-end;gap:6px;height:64px;padding-top:6px}
.spark .b{flex:1;background:var(--accent);border-radius:3px 3px 0 0;min-height:4px;opacity:.9}
.spark .b:hover{opacity:1}
/* ---- connect ---- */
.steps{display:flex;gap:8px;margin-bottom:20px}
.step{flex:1;padding:12px 14px;border:1px solid var(--line);border-radius:10px;background:var(--surface);display:flex;gap:10px;align-items:center}
.step .num{width:22px;height:22px;border-radius:50%;background:#eef0f2;color:var(--muted);display:grid;place-items:center;font-size:12px;font-weight:700}
.step.done .num{background:var(--good-wash);color:var(--good-ink)}
.step.done .num::after{content:"✓"}
.step.done .snum{display:none}
.step .t{font-weight:600;font-size:13px}.step .s{color:var(--muted);font-size:12px}
.conn{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:16px}
.connect-card{padding:18px;display:flex;flex-direction:column;gap:12px}
.cc-top{display:flex;align-items:center;gap:12px}
.cc-logo{width:44px;height:44px;border-radius:10px;display:grid;place-items:center;font-weight:800;color:#fff;font-size:18px}
.cc-qb{background:#2ca01c}.cc-sq{background:#0b0b0b}
.cc-name{font-weight:700;font-size:15px}.cc-desc{color:var(--muted);font-size:12.5px}
.btn{border:none;border-radius:9px;padding:10px 14px;font-weight:600;font-size:13.5px;cursor:pointer}
.btn.primary{background:var(--accent);color:#fff}
.btn.ghost{background:var(--surface-2);border:1px solid var(--line);color:var(--ink)}
.connected{display:flex;align-items:center;gap:8px;color:var(--good-ink);font-weight:600;font-size:13px;
  background:var(--good-wash);padding:9px 12px;border-radius:9px}
.reassure{display:flex;gap:18px;color:var(--muted);font-size:12.5px;margin-top:6px;flex-wrap:wrap}
.reassure span{display:flex;align-items:center;gap:6px}
/* ---- mapping ---- */
.type{display:inline-block;padding:2px 8px;border-radius:6px;font-size:11.5px;font-weight:600}
.type.inc{background:#eaf1fb;color:#1c5cab}.type.liab{background:#f3edfb;color:#5b3aa7}
.type.exp{background:#fbeee6;color:#a5542a}.type.bank{background:#e8f6e8;color:var(--good-ink)}
.acct{font-weight:600}.arrow{color:var(--muted);padding:0 6px}
.linkish{color:var(--accent);font-weight:600;cursor:pointer;font-size:12.5px}
/* ---- day detail ---- */
.dd-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}
.dd-title{font-size:18px;font-weight:700}
.receipt td{padding:11px 14px}
.receipt .lbl{color:var(--ink)}
.receipt .acctname{color:var(--muted);font-size:12px}
.receipt .sub td{border-top:1px solid var(--line);font-weight:600}
.receipt .grand td{border-top:2px solid var(--ink);font-weight:700;font-size:15px}
.recon{display:flex;align-items:center;gap:10px;background:var(--good-wash);color:var(--good-ink);
  padding:12px 16px;border-radius:10px;font-weight:600;margin-top:16px}
.backlink{color:var(--accent);font-weight:600;cursor:pointer;font-size:13px;margin-bottom:10px;display:inline-block}
.muted{color:var(--muted)}
.section-h{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:700;margin:0 0 10px}
</style>
</head>
<body>
<div class="app">
  <!-- sidebar -->
  <aside class="side">
    <div class="brand"><div class="logo">D</div>DailyLedger</div>
    <div class="nav active"><span class="ic">▦</span>Dashboard</div>
    <div class="nav"><span class="ic">⇄</span>Reconciliation</div>
    <div class="nav"><span class="ic">◗</span>Connections</div>
    <div class="nav"><span class="ic">≡</span>Account mapping</div>
    <div class="nav"><span class="ic">◔</span>Clients</div>
    <div class="nav"><span class="ic">⚙</span>Settings</div>
    <div class="foot">Synced today 7:15 AM · all systems normal</div>
  </aside>

  <div class="main">
    <!-- topbar -->
    <div class="top">
      <div class="orgsw"><span class="dot">☕</span>EverBean Coffee Co <span class="muted">▾</span></div>
      <div class="right">
        <span class="muted">Help</span>
        <div class="avatar">AR</div>
      </div>
    </div>

    <!-- mockup tab switcher -->
    <div class="tabs">
      <div class="tab active" data-v="dash">Dashboard</div>
      <div class="tab" data-v="day">Day detail</div>
      <div class="tab" data-v="connect">Connect accounts</div>
      <div class="tab" data-v="map">Account mapping</div>
    </div>

    <!-- ============ DASHBOARD ============ -->
    <div class="wrap view active" id="dash">
      <h1>Good morning, Andrew</h1>
      <p class="sub">Your July sales are posting to QuickBooks automatically. Everything's reconciled.</p>

      <div class="grid4">
        <div class="card kpi"><div class="lab">Net sales · July</div><div class="val">$17,267</div>
          <div class="meta"><span class="up">▲ 8.2%</span> vs last week</div></div>
        <div class="card kpi"><div class="lab">Sales tax collected</div><div class="val">$760.89</div>
          <div class="meta">Owed to Colorado DOR</div></div>
        <div class="card kpi"><div class="lab">Tips payable</div><div class="val">$2,186</div>
          <div class="meta">Held as liability</div></div>
        <div class="card kpi"><div class="lab">Deposits reconciled</div><div class="val">7 / 7</div>
          <div class="meta"><span class="tie"><svg viewBox="0 0 20 20" fill="none"><path d="M4 10l4 4 8-9" stroke="#0a7a15" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>tied to the penny</span></div></div>
      </div>

      <div class="card pad" style="margin-bottom:18px">
        <div class="section-h">Daily net sales · last 7 days</div>
        <div class="spark">
          <div class="b" style="height:68%" title="Jul 24 · $2,434"></div>
          <div class="b" style="height:100%" title="Jul 25 · $3,773"></div>
          <div class="b" style="height:82%" title="Jul 26 · $3,087"></div>
          <div class="b" style="height:55%" title="Jul 27 · $2,086"></div>
          <div class="b" style="height:54%" title="Jul 28 · $2,034"></div>
          <div class="b" style="height:55%" title="Jul 29 · $2,071"></div>
          <div class="b" style="height:47%" title="Jul 30 · $1,783"></div>
        </div>
      </div>

      <div class="card">
        <div style="padding:15px 16px 6px" class="section-h">Recent days</div>
        <table>
          <thead><tr>
            <th>Date</th><th>Status</th><th class="n">Net sales</th><th class="n">Sales tax</th>
            <th class="n">Tips</th><th class="n">Gift cards</th><th class="n">Deposit</th><th>Reconciled</th>
          </tr></thead>
          <tbody>
            <tr class="rowday">
              <td class="date"><b>Mon, Jul 27</b></td>
              <td><span class="pill ok"><span class="d"></span>Posted</span></td>
              <td class="n">$2,067.93</td><td class="n">$92.89</td><td class="n">$254.88</td>
              <td class="n">$98.35</td><td class="n">$2,507.75</td>
              <td><span class="tie"><svg viewBox="0 0 20 20" fill="none"><path d="M4 10l4 4 8-9" stroke="#0a7a15" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>✓</span></td>
            </tr>
            <tr>
              <td class="date"><b>Sun, Jul 26</b></td>
              <td><span class="pill ok"><span class="d"></span>Posted</span></td>
              <td class="n">$3,071.28</td><td class="n">$137.17</td><td class="n">$394.44</td>
              <td class="n">−$26.19</td><td class="n">$3,562.88</td>
              <td><span class="tie">✓</span></td>
            </tr>
            <tr>
              <td class="date"><b>Sat, Jul 25</b></td>
              <td><span class="pill ok"><span class="d"></span>Posted</span></td>
              <td class="n">$3,714.52</td><td class="n">$163.69</td><td class="n">$455.53</td>
              <td class="n">$0.00</td><td class="n">$4,213.09</td>
              <td><span class="tie">✓</span></td>
            </tr>
            <tr>
              <td class="date"><b>Fri, Jul 24</b></td>
              <td><span class="pill rev"><span class="d"></span>Needs review</span></td>
              <td class="n">$2,415.52</td><td class="n">$107.37</td><td class="n">$335.41</td>
              <td class="n">−$122.90</td><td class="n">$2,735.43</td>
              <td><span class="muted" style="font-size:12.5px">over/short $41.20</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ============ DAY DETAIL ============ -->
    <div class="wrap view" id="day">
      <span class="backlink" data-v="dash">‹ Back to dashboard</span>
      <div class="dd-head">
        <div>
          <div class="dd-title">Monday, July 27, 2026</div>
          <div class="sub" style="margin:2px 0 0">164 orders · posted to QuickBooks at 7:15 AM</div>
        </div>
        <span class="pill ok" style="font-size:13px"><span class="d"></span>Posted &amp; reconciled</span>
      </div>

      <div class="card pad">
        <div class="section-h">Sales receipt — as posted to QuickBooks</div>
        <table class="receipt">
          <tbody>
            <tr><td class="lbl">Gross product sales<div class="acctname">→ Sales of Product Income</div></td><td class="n">$2,085.70</td></tr>
            <tr><td class="lbl">Discounts<div class="acctname">→ Discount Income</div></td><td class="n neg">−$17.77</td></tr>
            <tr><td class="lbl">Tips collected<div class="acctname">→ Tips Payable (liability)</div></td><td class="n">$254.88</td></tr>
            <tr><td class="lbl">Gift cards sold<div class="acctname">→ Gift Card Outstanding (liability)</div></td><td class="n">$240.00</td></tr>
            <tr><td class="lbl">Gift cards redeemed<div class="acctname">→ Gift Card Outstanding (liability)</div></td><td class="n neg">−$141.65</td></tr>
            <tr><td class="lbl">Sales tax collected<div class="acctname">→ Square Sales Tax Payable · exact match to Square</div></td><td class="n">$92.89</td></tr>
            <tr class="sub"><td>Total collected</td><td class="n">$2,514.05</td></tr>
            <tr><td class="lbl muted">Less gift card redemptions</td><td class="n neg">−$141.65</td></tr>
            <tr class="grand"><td>Deposited to Checking ••0017</td><td class="n">$2,507.75</td></tr>
          </tbody>
        </table>
        <div class="recon">
          <svg viewBox="0 0 20 20" width="18" height="18" fill="none"><path d="M4 10l4 4 8-9" stroke="#0a7a15" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
          Matches your Square deposit of $2,507.75 exactly. Sales tax posted to the penny.
        </div>
      </div>
    </div>

    <!-- ============ CONNECT ============ -->
    <div class="wrap view" id="connect">
      <h1>Connect your accounts</h1>
      <p class="sub">Two clicks. We handle the rest — no spreadsheets, no copy-paste, no accountant required.</p>

      <div class="steps">
        <div class="step done"><div class="num"><span class="snum">1</span></div><div><div class="t">Connect Square</div><div class="s">Your sales data</div></div></div>
        <div class="step done"><div class="num"><span class="snum">2</span></div><div><div class="t">Connect QuickBooks</div><div class="s">Where it posts</div></div></div>
        <div class="step done"><div class="num"><span class="snum">3</span></div><div><div class="t">Auto-mapped</div><div class="s">9 accounts matched</div></div></div>
      </div>

      <div class="conn">
        <div class="card connect-card">
          <div class="cc-top"><div class="cc-logo cc-sq">□</div><div><div class="cc-name">Square</div><div class="cc-desc">Point of sale</div></div></div>
          <div class="connected"><svg viewBox="0 0 20 20" width="16" height="16" fill="none"><path d="M4 10l4 4 8-9" stroke="#0a7a15" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>Connected · EverBean Coffee Co · 2 locations</div>
          <div class="cc-desc">Read-only access to sales, payments &amp; payouts.</div>
        </div>
        <div class="card connect-card">
          <div class="cc-top"><div class="cc-logo cc-qb">qb</div><div><div class="cc-name">QuickBooks Online</div><div class="cc-desc">Accounting</div></div></div>
          <div class="connected"><svg viewBox="0 0 20 20" width="16" height="16" fill="none"><path d="M4 10l4 4 8-9" stroke="#0a7a15" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>Connected · SixFolks Partners LLC</div>
          <div class="cc-desc">We post daily sales receipts. You stay in control.</div>
        </div>
      </div>

      <div class="card pad">
        <div class="section-h">We set this up for you automatically</div>
        <div style="display:flex;align-items:center;justify-content:space-between">
          <div style="color:var(--ink-2)">Found your Square item template and matched all 9 accounts — sales, tax, tips, gift cards, fees, and rounding. Nothing to configure.</div>
          <button class="btn ghost">Review mapping</button>
        </div>
      </div>

      <div class="reassure">
        <span>🔒 Bank-level encryption</span>
        <span>👁 Read-only where possible</span>
        <span>⟲ Disconnect anytime</span>
        <span>✓ SOC 2 practices</span>
      </div>
    </div>

    <!-- ============ MAPPING ============ -->
    <div class="wrap view" id="map">
      <h1>Account mapping</h1>
      <p class="sub">Where each part of your Square sales lands in QuickBooks. Auto-detected — edit any row if your books differ.</p>
      <div class="card">
        <table>
          <thead><tr><th>Square activity</th><th>Posts to QuickBooks account</th><th>Type</th><th></th></tr></thead>
          <tbody>
            <tr><td>Gross product sales</td><td><span class="acct">Sales of Product Income</span></td><td><span class="type inc">Income</span></td><td class="n"><span class="linkish">Edit</span></td></tr>
            <tr><td>Discounts</td><td><span class="acct">Discount Income</span></td><td><span class="type inc">Income</span></td><td class="n"><span class="linkish">Edit</span></td></tr>
            <tr><td>Sales tax collected</td><td><span class="acct">Square Sales Tax Payable</span></td><td><span class="type liab">Liability</span></td><td class="n"><span class="linkish">Edit</span></td></tr>
            <tr><td>Tips collected</td><td><span class="acct">Tips Payable</span></td><td><span class="type liab">Liability</span></td><td class="n"><span class="linkish">Edit</span></td></tr>
            <tr><td>Gift cards sold &amp; redeemed</td><td><span class="acct">Gift Card Outstanding</span></td><td><span class="type liab">Liability</span></td><td class="n"><span class="linkish">Edit</span></td></tr>
            <tr><td>Processing fees</td><td><span class="acct">Square Fees</span></td><td><span class="type exp">Expense</span></td><td class="n"><span class="linkish">Edit</span></td></tr>
            <tr><td>Rounding differences</td><td><span class="acct">Over &amp; Short</span></td><td><span class="type exp">Expense</span></td><td class="n"><span class="linkish">Edit</span></td></tr>
            <tr><td>Daily deposit</td><td><span class="acct">Checking ••0017</span></td><td><span class="type bank">Bank</span></td><td class="n"><span class="linkish">Edit</span></td></tr>
          </tbody>
        </table>
      </div>
      <p class="sub" style="margin-top:14px">Sales tax uses <b>exactly what Square collected</b>, not a QuickBooks re-estimate — so what you remit always matches what you took in.</p>
    </div>

  </div>
</div>
<script>
  const tabs=document.querySelectorAll('.tab'), views=document.querySelectorAll('.view');
  function show(v){views.forEach(x=>x.classList.toggle('active',x.id===v));
    tabs.forEach(t=>t.classList.toggle('active',t.dataset.v===v));window.scrollTo(0,0);}
  document.querySelectorAll('[data-v]').forEach(el=>el.addEventListener('click',()=>show(el.dataset.v)));
  document.querySelectorAll('.rowday').forEach(r=>r.addEventListener('click',()=>show('day')));
</script>
</body>
</html>
```
