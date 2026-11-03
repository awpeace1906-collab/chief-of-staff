# Push to the iPhone app (APNs)

After each hourly check, the server sends a silent push (`content-available`) to every registered iPhone so the app can refresh in the background. The app is the iOS shell ([ios.md](ios.md)). Without this setup, everything else still works; the phone just isn't woken.

## 1. Make a key (Apple Developer portal, once)

1. Go to [developer.apple.com](https://developer.apple.com/account) → Certificates, Identifiers & Profiles → **Keys** → **+**.
2. Name it (e.g. "Chief of Staff push"), check **Apple Push Notifications service (APNs)**, then Continue → Register.
3. **Download the `.p8` file.** Apple lets you download it only once. Keep it safe.
4. Note the **Key ID** (shown on the key's page) and your **Team ID** (Membership details, or top right of the portal).

Also make sure the App ID for your bundle id has **Push Notifications** turned on (Identifiers → your App ID).

## 2. Tell the server

Keep the key **on the server, never in the repo**. Environment:

```bash
APNS_KEY_ID=ABC123DEFG                 # the key's Key ID
APNS_TEAM_ID=XYZ987TEAM                # your Team ID
APNS_BUNDLE=com.yourdomain.chiefofstaff   # the app's bundle id (the push topic)
APNS_KEY_PATH=/secure/path/AuthKey_ABC123DEFG.p8
APNS_ENV=sandbox                       # sandbox for builds run from Xcode; anything else = production
```

Builds you run from Xcode get **sandbox** device tokens, so use `APNS_ENV=sandbox` while developing. TestFlight and App Store builds use production. A token sent to the wrong environment gets `400 BadDeviceToken` and is dropped.

Install the push extra: `pip install -e '.[push]'` (PyJWT with crypto, and httpx with HTTP/2).

## 3. Check it

```bash
curl -H "Authorization: Bearer $COS_API_TOKEN" http://127.0.0.1:8700/api/push/status
# {"configured": true, "tokens": 1}
```

`configured` means all four `APNS_*` variables are set. `tokens` counts registered iPhones. The app registers itself when the web app calls `COSNative.registerPush()`, which posts to `POST /api/push/register`.

Then `POST /api/check/run`; the phone should wake.

## How it behaves

- Device tokens are kept in the server's secrets table. They never go into settings, `/api/export` or memory.
- The provider token (an ES256 JWT) is made from the key and reused for about 50 minutes.
- Pushes are `apns-push-type: background`, `apns-priority: 5`, payload `{"aps": {"content-available": 1}}`.
- Tokens Apple reports as dead (`410`, or `400 BadDeviceToken`) are removed. Other failures keep the token for next time.
- A push failure never fails the check; it's written to the audit log as `push.failed`.
- iOS decides when (and whether) to deliver silent pushes, and throttles them. Opening the app is what reliably refreshes it.
