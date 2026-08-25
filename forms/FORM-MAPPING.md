# Form field mapping — source of truth

**10DLC compliance (2026-08-11):** all three native forms now include an optional SMS/call
consent checkbox and link to `symm-privacy.html`, per Zoho's [mandatory website requirements
for 10DLC registration](https://help.zoho.com/portal/en/kb/zoho-voice/10dlc/articles/mandatory-website-requirements-for-10dlc-registration-compliance).
Contact's Zoho form already had a `Checkbox` field so the new option was added as a 2nd choice
on it; Trial and Checkout got a new `Checkbox` field added in the Zoho form builder (label
"Consent", single choice, link-name confirmed as `Checkbox` on the live published form). All
three now capture consent end-to-end.

## Email sender / recipient policy (set 2026-08-22, after DKIM)

symmbiotic.com DKIM was verified in Zoho Forms (1024-bit). That lifts Zoho's rule restricting
recipients to org users, so **email ALIASES like `advisors@` now work** as long as the From is a
symmbiotic.com address. **All INTERNAL notifications** on Contact, Trial, Checkout and Yield
Guarantee are now From `kyle@symmbiotic.com` → **advisors@ + aidan@ + natasha@ + kyle@**.

Do NOT switch an internal notification's From back to `notifications@zohoforms.com`: advisors@ will
start being rejected ("you can add only your organization's users as recipients").

**Still on `notifications@zohoforms.com` (customer-facing, deliberately unchanged):**
- Checkout → "Customer Confirmation" ("We received your Symm order request")
- Yield Guarantee → applicant autoresponder ("We received your Symm Yield Guarantee application")

These go to external customers, so switching their From to symmbiotic.com is a branding win but
carries real deliverability risk to Gmail/Outlook if DKIM/SPF/DMARC are not fully aligned. Decide
deliberately rather than by default. Zoho Books/Payments senders were NOT audited here.

---

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
| SMS/Call Consent | `Checkbox` | checkbox | "I consent to receive calls, emails, and text messages from Symm" — 2nd option on the same `Checkbox` field, added for [10DLC compliance](https://help.zoho.com/portal/en/kb/zoho-voice/10dlc/articles/mandatory-website-requirements-for-10dlc-registration-compliance), optional (not required) |
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
| SMS/Call Consent | `Checkbox` | checkbox | "I consent to receive calls, emails, and text messages from Symm" — 10DLC compliance, optional |

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
| SMS/Call Consent | `Checkbox` | checkbox | "I consent to receive calls, emails, and text messages from Symm" — 10DLC compliance, optional |

**Checkout prefill (URL params set by `symm-checkout.html` loadForm):**
`SingleLine1` (acres), `SingleLine4` (discount %), `Number` (acres), `Number1` (discount %),
`SingleLine2` (promo/advisor code).

---

## 4. Yield Guarantee apply  (Zoho form: **SymmYieldGuarantee**)
- formperma: `46W8wdfaky7eVBrNAWfBdFQ3VoFwS2MV02hlxJtdO0o`
- Page: `symm-yield-guarantee.html` (LIVE, linked from nav + footer sitewide plus a CTA on `index.html`).
- Built 2026-08-22 as a Zoho **CRM Form** (Forms → New Form → CRM Forms), so the Zoho CRM
  integration was created automatically and shows **Connected**. Module = Leads,
  Layout = Standard (`7476249000000091055`), Org = symm (`928049781`).
- Downstream: Forms→CRM Leads integration (auto) + notification to advisors@ + applicant
  autoresponder (no pricing or terms in the autoresponder). Both emails are LIVE.

**Link-names below are GROUND TRUTH**, read from the published form's DOM on 2026-08-22. Because
this was created as a CRM Form, Zoho assigned names by its own field order, NOT the convention the
other three forms follow. Notable surprises:
- There is **no `Name` composite**. CRM has separate First/Last, so they are two `SingleLine` fields.
- Primary Crops (a CRM multiselect) rendered as a **`Checkbox`** group, not `MultiSelect`.
- Consent to Contact (a CRM boolean) rendered as **`DecisionBox`**, not `Checkbox`.
- There are **four** dropdowns, and Role is `Dropdown3`, not `Dropdown`.

| Apply-form field | Zoho link-name | Type | Req | → Zoho CRM Leads field |
|---|---|---|---|---|
| Operation / farm name | `SingleLine` | text | **Yes (Zoho-enforced)** | Company |
| Last name | `SingleLine1` | text | **Yes (Zoho-enforced)** | Last Name |
| First name | `SingleLine2` | text | form-only | First Name |
| Email | `Email` | email | form-only | Email |
| Phone | `PhoneNumber` | tel | form-only | Phone |
| *(hidden)* Lead Source | `Dropdown` | select | — | Lead Source |
| *(hidden)* Lead Status | `Dropdown1` | select | — | Lead Status |
| State | `Dropdown2` | select | form-only | State |
| Tell us about your operation | `MultiLine` | textarea | No | Description |
| Role | `Dropdown3` | select | form-only | **Role** (custom picklist) |
| Primary crops | `Checkbox` | checkbox group, 17 options | form-only (≥1) | **Primary Crops** (custom multiselect) |
| Consent to be contacted | `DecisionBox` | boolean checkbox, value `true` | form-only | **Consent to Contact** (custom boolean) |
| Approx. total acreage | `Number` | number | form-only | **Total Acreage** (custom number) |
| Consent timestamp | `SingleLine3` | text **(hidden)** | — | **Consent Timestamp** (ISO string set by JS) |

`Company` and `Last Name` are the only two Zoho marks mandatory, so the native form MUST always
send `SingleLine` and `SingleLine1` or Zoho rejects the submission. Everything else is enforced
client-side on our page only.

**Fixed values are sent as hidden inputs from our page** (not set in the integration mapping),
because both are real form fields on the Zoho form:
- `Dropdown`  = `Yield Guarantee Apply Page` (confirmed present in the field's options)
- `Dropdown1` = `Not Contacted` (confirmed present in the field's options)

**State dropdown (`Dropdown2`) — FIXED 2026-08-22.** Zoho originally populated it with 3,954
worldwide province options (Papua New Guinea provinces sorted first), which made the Zoho-hosted
form unusable for a US grower. Replaced via field properties → Choices → Advanced → Import →
Add Manually with "Replace existing choices" checked. Verified on the published form: exactly
**51 options (50 states + DC)**, no duplicates, no leftovers.

**VERIFIED END-TO-END 2026-08-22.** Posted a test payload to `/records` (HTTP 200) and confirmed the
Lead reached CRM with every field intact: Company, First/Last Name, Email, Phone (auto-formatted),
Lead Source, Lead Status, State, Role, Primary Crops (multi-value, `Corn; Small grains`), Total
Acreage, Description, Consent Timestamp, and **Consent to Contact = checked**. Test leads and form
entries were deleted afterwards (CRM Recycle Bin / Forms Trash, not purged).

**`DecisionBox` value format:** send the STRING `"true"`, not a JSON boolean. Confirmed by
intercepting the Zoho-hosted form's own XHR, which sends `"DecisionBox":"true"`. Our page uses
`value="true"` on the checkbox so FormData produces the correct string. A JSON boolean `true` is
also accepted by the form, but the string is what Zoho itself sends, so prefer it. When consent is
unchecked the field is simply absent from the payload, which is correct.

### Emails (both LIVE and enabled, 2026-08-22)

**1. Internal notification.** From **`kyle@symmbiotic.com`**, subject
"New Yield Guarantee Application - Symm", body carries every field as merge tokens.
To: **aidan@ + natasha@ + kyle@ + advisors@ symmbiotic.com** (4 recipients).

`advisors@` is an email ALIAS, not a Zoho org user. It works because symmbiotic.com DKIM was
verified in Zoho Forms (1024-bit key, 2026-08-22): with a DKIM-verified custom-domain From, Zoho
permits non-user aliases as recipients. Before DKIM it was hard-blocked two ways ("you can add only
your organization's users as recipients" with the Zoho sender, and a DKIM gate that refused to save
a symmbiotic.com From). **Do not switch this From back to `notifications@zohoforms.com`** or
advisors@ will start being rejected again.

**2. Applicant autoresponder.** From `notifications@zohoforms.com`, To `${zf:Email}`,
subject "We received your Symm Yield Guarantee application". Body greets by first name
(`${zf:SingleLine2}`), confirms receipt for their operation (`${zf:SingleLine}`), and says a Field
Advisor will review and reach out. **Contains no pricing and no terms**, per the memo.

**STILL TODO:** deploy the relay so the `/yieldguarantee` route exists in Catalyst
(`cd catalyst && catalyst deploy`, needs interactive login), then link the page into nav/footer
after a real end-to-end submission is confirmed.

**Primary Crops options (must match the CRM picklist exactly, 17):** Tree nuts · Citrus · Pome and
stone fruit · Berries · Grapes · Leafy greens and brassicas · Tomatoes and peppers · Cucurbits and
melons · Onions and garlic · Potatoes and root vegetables · Corn · Soybeans and pulses · Small
grains · Cotton · Hay and pasture · Hemp and hops · Other.
Note: labels use "and", never `&`.

**CRM-side notes:** the five custom Lead fields exist and are verified. `Required` is deliberately
OFF at the CRM level (enforced on the form instead) so the dialer, batch imports, and manual entry
are not blocked. See memory `yield-guarantee-apply-form` for the full rationale.

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
- Checkbox / MultiSelect = array of selected option label(s). The relay arrays any field matching
  `/^(Checkbox|MultiSelect)\d*$/`, so numbered variants (`Checkbox1`, `MultiSelect2`) work too.
- Number fields = numeric.
- A 200 response means the entry was created and all downstream automation (Books estimate,
  notifications, customer email) fires exactly as with the old iframe.

## 10DLC / TCR consent wording (set 2026-08-24)

Zoho/TCR require **exact** opt-in wording on every form that collects a phone number, plus
mandatory verbiage in the Privacy Policy. Registered entity is **Source Technologies LLC**;
registered **brand is Symmbiotic**, so the brand name in the consent line is "Symmbiotic".
Registered use case is **customer care**, so the message type is "customer care-related or
one-on-one communication messages". Do not describe a message type we do not send.

The visible label on all four forms is now, verbatim:

> By clicking here you consent to receive customer care-related or one-on-one communication
> messages from Symmbiotic. Message frequency may vary. Standard Message and Data Rates may
> apply. Reply STOP to opt out. Reply Help for help. [Privacy Policy] [Terms of Service]

**IMPORTANT: the checkbox `value` was deliberately NOT changed.** It remains
`I consent to receive calls, emails, and text messages from Symm`, because Zoho Forms validates
a Checkbox submission against the options configured on the form. Sending a value that is not
a configured option risks the consent not being recorded. TCR reviews the on-page label, not the
posted value, so only the label was rewritten. If you ever want the stored value to match the
new wording, add the new option in the Zoho form builder FIRST, then change the HTML.

**This was attempted on 2026-08-25 and is NOT possible.** Zoho Forms hard-caps each choice-option
string at **150 characters** (`maxlength="150"` on the option input in the choice editor). The TCR
sentence is 230 characters, so Zoho silently truncates it mid-word at
`...Message frequency may vary. Standa`. A truncated option is worse than no change: it is not the
TCR wording, nothing on our site posts it, and it renders as a stray extra consent checkbox on the
publicly reachable Zoho-hosted form URL. The options added during that attempt were removed again
and all three forms verified back to their original sets.

**Settled design, do not revisit:** the stored value is a short stable audit marker
(`I consent to receive calls, emails, and text messages from Symm`); the TCR-required wording lives
in the visible on-page label. These intentionally differ. TCR audits the opt-in screen the user
sees, not the database string. All three HTML `value` attributes were verified on 2026-08-25 to
match the live Zoho options exactly, so consent records correctly.

Yield Guarantee needs no sync at all: its consent is a `DecisionBox` boolean storing `"true"`, so
there is no option wording to keep aligned.

The Privacy Policy carries TCR's two mandatory paragraphs verbatim in section 03 (Calls and text
messages). Do not reword them. A `symm-terms.html` page exists because TCR requires a Terms URL
alongside the Privacy Policy URL in the consent line.
