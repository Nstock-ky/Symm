# Symm form relay (Zoho Catalyst)

Serverless function that receives native-form submissions from the site and forwards
them into the matching Zoho form (`SymmContact` / `SymmTrial` / `SymmCheckout`), so all
downstream Zoho automation keeps working. See `../forms/FORM-MAPPING.md` for field details.

- Code: `functions/formrelay/index.js` (Advanced I/O, Node.js, Express).
- **No secrets required** — it posts to Zoho's public form endpoint (no API keys).
- Runs on Catalyst's cloud (project **Project-Rainfall**). Your computer only deploys it.

## One-time deploy (run in this `catalyst/` folder)

```bash
cd catalyst
catalyst login          # opens browser OAuth — this is the step only you can do
catalyst init           # select: Functions → link to "Project-Rainfall"
                        #   create an Advanced I/O function, Node.js stack, named: formrelay
```

`catalyst init` may overwrite our `functions/formrelay/index.js` and `package.json` with
starter stubs. If it does, restore ours:

```bash
git checkout catalyst/functions/formrelay/index.js catalyst/functions/formrelay/package.json
```

Then install deps and deploy:

```bash
cd functions/formrelay && npm install && cd ../..
catalyst deploy
```

After deploy, Catalyst prints the function URL, shaped like:
`https://<project>.<zone>.catalystserverless.com/server/formrelay`

The native forms POST to `<that URL>/contact`, `/trial`, or `/checkout`.

## Quick test after deploy (no site needed)

```bash
curl -X POST "<function-url>/contact" \
  -H "Content-Type: application/json" \
  -d '{"Name_First":"Relay","Name_Last":"Test","Email":"kyle@cropdefense.com","Checkbox":["Symm may contact me about my request"]}'
```
Expect `{"ok":true}` and a new entry in the Zoho SymmContact form. (Delete the test entry after.)

## If the test returns a non-200 / `zoho <status>`
The public endpoint may want the session cookie the relay already primes; if Zoho tightened
it, the fallback is to switch the relay to the Zoho Books/CRM API (needs a Self-Client OAuth
token in Catalyst env vars). We'll only do that if the public POST is rejected.
