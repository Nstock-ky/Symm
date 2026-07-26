# Form field mapping — source of truth

**Why this file exists:** each site form now has THREE parts that must stay in sync. If you
add/rename/remove a field, update **all three**:
1. **Native form** — the HTML/CSS form on our page (our theme).
2. **Zoho form** — the backing form at forms.zoho.com (org `cropdefense1`) that stores the
   entry and drives downstream automation (Books estimate, notifications, emails).
3. **Relay** — the Catalyst function that forwards native submissions into the Zoho form.

**Naming convention:** native `<input name>` = the Zoho **field link-name** (e.g. `SingleLine1`),
so the relay is a 1:1 passthrough. Composite fields (Name, Address) use Zoho's sub-part names
(e.g. `Name_First`, `Address_City`) — confirm exact POST params against a live submission when
wiring the relay.

Edit checklist for ANY field change: [ ] native HTML  [ ] Zoho form builder  [ ] this file
[ ] relay (if field list changed)  [ ] downstream mapping (Books integration / notification /
customer email) if the field feeds it.

---

## 1. Contact  (Zoho form: **SymmContact**)
- formperma: `1hrbP4thHbSxXEX3-FV7AlaGVgvzE0DqhXMBYhuHSJw`
- Page: `symm-contact.html`
- Downstream: email notification + contact routing (advisors@ / info@). *(No Books integration.)*

| Label | Zoho link-name | Type | Notes |
|---|---|---|---|
| Name | `Name` (`Name_First`,`Name_Last`) | name | composite |
| Email | `Email` | email | |
| Phone | `PhoneNumber` | tel | |
| Operation Name | `SingleLine` | text | |
| State | `SingleLine1` | text | |
| Primary Crops | `SingleLine2` | text | |
| Total Acreage | `SingleLine3` | text | |
| How Can We Help | `Dropdown` | select | verify option values in builder |
| Consent | `Checkbox` | checkbox | "Symm may contact me about my request" |
| Message | `MultiLine` | textarea | |

---

## 2. Trial  (Zoho form: **SymmTrial**)
- formperma: `8hf5iDh9YFVKAO2yZqR-sJRjmV7zqbozDNPH1-1WXww`
- Page: `symm-trial.html`
- Downstream: email notification.

| Label | Zoho link-name | Type | Notes |
|---|---|---|---|
| Name | `Name` (`Name_First`,`Name_Last`) | name | composite |
| Email | `Email` | email | |
| Phone | `PhoneNumber` | tel | |
| Operation Name | `SingleLine` | text | |
| Primary Crops | `SingleLine1` | text | |
| Total Acreage | `SingleLine2` | text | |
| Goals and Notes | `MultiLine` | textarea | |

---

## 3. Checkout  (Zoho form: **SymmCheckout**)
- formperma: `MLs4KdlpWZLP2sGA71KvakzyO3DIy44s8VrgA4_e2FU`
- Page: `symm-checkout.html`
- Downstream: **Forms→Books Quotes/estimate integration** + internal notification (aidan@) +
  customer "Field Advisor" confirmation email. See memory `checkout-estimate-pipeline`.
  Do NOT rename the hidden fields without updating the Books integration mapping.

| Label | Zoho link-name | Type | Notes |
|---|---|---|---|
| Name | `Name` (`Name_First`,`Name_Last`) | name | composite → Books Customer Name (Last) |
| Address | `Address` (`Address_AddressLine1`,`Address_AddressLine2`,`Address_City`,`Address_Region`,`Address_ZipCode`,`Address_Country`) | address | composite |
| Phone | `PhoneNumber` | tel | |
| Email | `Email` | email | → Books Email |
| Primary Crop | `SingleLine` | text | |
| Total Acreage | `SingleLine1` | text | prefilled from calculator |
| Notes for Advisor | `MultiLine` | textarea | |
| Promo or Advisor Code | `SingleLine2` | text | prefilled if stored code |
| Product | `SingleLine3` | text **(hidden)** | value "Symm Program" → Books **Item Name** |
| Volume Discount Percent | `SingleLine4` | text **(hidden)** | prefilled |
| Order Quantity | `Number` | number **(hidden)** | = acres → Books **Item quantity** |
| Discount Value | `Number1` | number **(hidden)** | = discount % (captured for sales) |

**Checkout prefill (URL params set by `symm-checkout.html` loadForm):**
`SingleLine1` (acres), `SingleLine4` (discount %), `Number` (acres), `Number1` (discount %),
`SingleLine2` (promo/advisor code).

---

## Relay → Zoho submission format (ground truth, captured 2026-07-26)

The Catalyst relay forwards each submission as a **JSON POST**:

```
POST https://forms.zohopublic.com/cropdefense1/form/<FormName>/formperma/<perma>/records
Content-Type: application/json
Referer: <the form's formperma URL>
```

Body shape (keys = field link-names above):
```json
{
  "Name":    { "Name_First": "…", "Name_Last": "…" },
  "Address": { "Address_AddressLine1": "…", "Address_AddressLine2": "…",
               "Address_City": "…", "Address_Region": "…",
               "Address_ZipCode": "…", "Address_Country": "…" },
  "Email": "…", "PhoneNumber": "…",
  "SingleLine": "…", "SingleLine1": "…", "MultiLine": "…",
  "Number": 100, "Number1": 10,
  "Checkbox": ["Symm may contact me about my request"]
}
```
- Composite fields (Name, Address) = nested objects; the inner keys are the FULL sub-names.
- Checkbox = array of selected option label(s).
- Number fields = numeric.
- A 200 response means the entry was created and all downstream automation (Books estimate,
  notifications, customer email) fires exactly as with the old iframe.
