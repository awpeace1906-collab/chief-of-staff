# Connect Google (one-time setup)

Chief of Staff talks to Google Calendar and Gmail directly, with its own sign-in. Google requires each app to have a Google Cloud project; for a personal install, that project is yours. About 15 minutes, free.

Access: `calendar.readonly`, `gmail.readonly`, and `gmail.send`. The send permission is used for one thing only: emailing the morning brief to you. The app has no code path that emails anyone else (that waits for approvals in v0.4). Changing calendars comes later and will ask for more access then.

## 1. Create the project

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and sign in with the Google account the agent will read.
2. Project picker → **New project** → name it `Chief of Staff` → Create.

## 2. Turn on the two APIs

**APIs & Services → Library**, search and **Enable** each:
- Google Calendar API
- Gmail API

## 3. Consent screen

**APIs & Services → OAuth consent screen** (labeled **Google Auth Platform** in newer consoles):
1. User type **External** → app name `Chief of Staff`, your email as support and developer contact.
2. **Scopes:** add `.../auth/calendar.readonly`, `.../auth/calendar.events`, `.../auth/gmail.readonly` and `.../auth/gmail.send`. `calendar.events` is used only to carry out calendar proposals you approved, and never invites anyone.
3. **Test users:** add that same Google account.

**Testing vs production.** While the app is in *Testing*, Google expires its sign-in after **7 days**, so you'd reconnect weekly. To avoid that, set the publishing status to **In production**. Gmail read access is a "restricted" scope, so Google will show an "unverified app" warning when you sign in. For a personal app used only by you, click through it (**Advanced → Go to Chief of Staff**). Verification is only needed for apps offered to the public; the public Chief of Staff product will need it, a personal install doesn't. Check the console's current wording; Google adjusts these screens often.

## 4. Create the OAuth client

**APIs & Services → Credentials → Create credentials → OAuth client ID**:
- Application type: **Web application**
- Name: `Chief of Staff`
- **Authorized redirect URIs**, add the one(s) you'll use:
  - Running on your own computer: `http://127.0.0.1:8700/oauth/google/callback`
  - Running on a server behind a tunnel: `https://<your-domain>/oauth/google/callback`

Copy the **Client ID** and **Client secret**.

## 5. Give them to Chief of Staff

Never paste these into a chat. Put them in the app's environment:

```bash
# app/.env (git-ignored) or your server's environment
GOOGLE_CLIENT_ID=...apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=...
COS_API_TOKEN=<any long random string>
```

If you use the server/tunnel redirect, also set it in memory (`memory.json` → `google.redirectUri`) or `COS_GOOGLE_REDIRECT`, so it matches what you registered in step 4.

## 6. Connect

1. Start the app: `cos serve`.
2. Open `http://127.0.0.1:8700/oauth/google/start?token=<COS_API_TOKEN>` in your browser.
3. Sign in, allow access. You'll see "Google connected."
4. Check: `cos google status` and `cos agenda --days 7`.

## Already connected before v0.4?

The app now adds the calendar write permission (`calendar.events`), which it uses to carry out approved proposals. `cos google status` shows `"canWriteCalendar": false` until you connect again at `/oauth/google/start`. Until then, approved calendar proposals stay approved and the error notice says so.

## Already connected before v0.3?

v0.3 added the send permission. `cos google status` shows `"canSend": false` until you connect again at `/oauth/google/start`; until then the brief is saved and shown but not emailed.

## Digest intake address

The agent reads mail sent to a plus-address such as **you+<agent>@gmail.com** (`google.intakeAddress` in memory). Gmail delivers plus-addresses to your normal inbox; nothing to set up. Optional: a Gmail filter (`to:you+<agent>@gmail.com` → apply label `<Agent>/Intake`, skip inbox) keeps forwarded digests out of your way. Check with `cos mail intake`.

## Disconnect

`cos google disconnect` revokes the app's access and deletes the stored token. You can also remove it at [myaccount.google.com/permissions](https://myaccount.google.com/permissions).

## Where the token lives

In the `secrets` table of `cos.db`, which is created owner-read/write only. It is never included in `cos export`. Keep the data directory on an encrypted disk (FileVault on a Mac; encrypted volume on a server).
