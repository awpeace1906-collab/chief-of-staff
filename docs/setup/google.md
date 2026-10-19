# Connect Google (one-time setup)

Chief of Staff talks to Google Calendar and Gmail directly, with its own sign-in. Google requires each app to have a Google Cloud project; for a personal install, that project is yours. About 15 minutes, free.

Access is **read-only**: `calendar.readonly` and `gmail.readonly`. Sending mail and changing calendars come later, after approvals exist, and will ask for broader access then.

## 1. Create the project

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and sign in as awpeace1906@gmail.com.
2. Project picker → **New project** → name it `Chief of Staff` → Create.

## 2. Turn on the two APIs

**APIs & Services → Library**, search and **Enable** each:
- Google Calendar API
- Gmail API

## 3. Consent screen

**APIs & Services → OAuth consent screen** (labeled **Google Auth Platform** in newer consoles):
1. User type **External** → app name `Chief of Staff`, your email as support and developer contact.
2. **Scopes:** add `.../auth/calendar.readonly` and `.../auth/gmail.readonly`.
3. **Test users:** add awpeace1906@gmail.com.

**Testing vs production.** While the app is in *Testing*, Google expires its sign-in after **7 days**, so you'd reconnect weekly. To avoid that, set the publishing status to **In production**. Gmail read access is a "restricted" scope, so Google will show an "unverified app" warning when you sign in. For a personal app used only by you, click through it (**Advanced → Go to Chief of Staff**). Verification is only needed for apps offered to the public; the public Chief of Staff product will need it, Andrew's own install doesn't. Check the console's current wording; Google adjusts these screens often.

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

If you use the server/tunnel redirect, also set it in config (`config/tower.json` → `google.redirectUri`) or `COS_GOOGLE_REDIRECT`, so it matches what you registered in step 4.

## 6. Connect

1. Start the app: `cos serve`.
2. Open `http://127.0.0.1:8700/oauth/google/start?token=<COS_API_TOKEN>` in your browser.
3. Sign in, allow access. You'll see "Google connected."
4. Check: `cos google status` and `cos agenda --days 7`.

## Digest intake address

Tower reads mail sent to **awpeace1906+tower@gmail.com** (`google.intakeAddress` in config). Gmail delivers plus-addresses to your normal inbox; nothing to set up. Optional: a Gmail filter (`to:awpeace1906+tower@gmail.com` → apply label `Tower/Intake`, skip inbox) keeps forwarded digests out of your way. Check with `cos mail intake`.

## Disconnect

`cos google disconnect` revokes the app's access and deletes the stored token. You can also remove it at [myaccount.google.com/permissions](https://myaccount.google.com/permissions).

## Where the token lives

In the `secrets` table of `cos.db`, which is created owner-read/write only. It is never included in `cos export`. Keep the data directory on an encrypted disk (FileVault on a Mac; encrypted volume on a server).
