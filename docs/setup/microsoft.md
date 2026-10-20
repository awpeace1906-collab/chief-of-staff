# Connect Microsoft 365 (one-time setup)

Chief of Staff reads Outlook mail, the Outlook calendar, Microsoft To Do and OneDrive through Microsoft Graph, **read-only**. It works with a **personal Microsoft account**, including one you sign in to with a Gmail address (Andrew's is `awpeace1906@gmail.com`), and with work or school accounts if you allow them.

Claude's built-in Microsoft 365 connector only works with work or school accounts, which is why the app has its own connection.

Takes about 10 minutes. It's free and needs no Azure subscription.

## 1. Register the app

1. Go to **https://entra.microsoft.com** → **Applications → App registrations → New registration**. Sign in with the same Microsoft account. If it asks you to create a directory or tenant, choose the free option.
2. **Name:** `Chief of Staff`.
3. **Supported account types:** *Personal Microsoft accounts only*. Choose *Accounts in any organizational directory and personal Microsoft accounts* if you also want to connect a work or school account later.
4. **Redirect URI:** platform **Web**, address `https://<your app's address>/oauth/microsoft/callback`. For a local test, use `http://localhost:8700/oauth/microsoft/callback`.
5. **Register.** Copy the **Application (client) ID**.

## 2. Create a client secret

**Certificates & secrets → New client secret** → description `chief-of-staff`, expiry 24 months → **Add**. Copy the **Value** now, because it's shown only once.

## 3. Permissions

**API permissions → Add a permission → Microsoft Graph → Delegated permissions**. Add:
- `offline_access`, `openid`, `email`
- `User.Read`
- `Mail.Read`
- `Calendars.Read`
- `Tasks.Read`
- `Files.Read`

Personal accounts don't need admin consent; you approve these yourself when you connect.

## 4. Give them to Chief of Staff

```bash
# the server's environment (never in the repo)
MS_CLIENT_ID=<application (client) id>
MS_CLIENT_SECRET=<secret value>
MS_TENANT=consumers            # personal only; "common" if you chose personal + work/school
COS_MS_REDIRECT=https://<your app's address>/oauth/microsoft/callback
```

## 5. Connect

Open the app, sign in, then go to `https://<your app's address>/oauth/microsoft/start`. Pick your Microsoft account and approve. The page should then say "Microsoft 365 connected (you@…)".

Check it from the API or CLI:

```bash
cos microsoft status
cos microsoft calendars     # ids for mapping calendars to divisions
cos microsoft agenda --days 7
cos microsoft todo
```

## 6. Map calendars to divisions (optional)

By default your main Outlook calendar counts as **Me**. To map others, set `microsoft.divisions` in `config/tower.json` (or `PUT /api/settings/microsoft`):

```json
"microsoft": {
  "divisions": {
    "me": {"Outlook": "default"},
    "kids": {"School": "<calendar id from cos microsoft calendars>"}
  }
}
```

## What it's used for

- **Capture:** Outlook inbox and sent mail go through the same capture step as Gmail. Commitments land on the board with source "Outlook".
- **Brief:** Outlook events and open To Do tasks are added to the morning brief's inputs.
- Senders that the digest adapters mark *sensitive* or *ignore* are skipped, the same as for Gmail.

## Disconnect

`cos microsoft disconnect` (or `POST /api/microsoft/disconnect`) deletes the stored tokens. To revoke fully, remove "Chief of Staff" at https://account.live.com/consent/Manage.

## Where the token lives

In the app's SQLite file (`secrets` table, file mode 0600). It is never exported. Microsoft rotates the refresh token on every refresh, and the app stores the new one each time.

## Work account (burrell.edu)

A school or hospital tenant usually blocks third-party apps until IT approves them. Until then, keep the forwarding approach in [../features/digests.md](../features/digests.md): Outlook rules forward digests (no PHI) to the Tower inbox.
