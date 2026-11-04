# iPhone app (iOS shell)

The iPhone app is a thin native shell, built with Capacitor 6, around the same web app the PWA runs. It lives in `ios-shell/` at the repo root as its own Node project. It adds four things the PWA can't do:

| Native feature | What it does | Where |
|---|---|---|
| Silent push | The server wakes the app after each hourly check | `AppDelegate.swift`, server `cos/push.py` ([apns.md](apns.md)) |
| Background sync | Replays queued API calls and keeps the session warm, on a push or a background refresh | `SyncEngine.swift` |
| Calendar (EventKit) | Reads and adds events on the phone's own calendars | `CalendarPlugin.swift` |
| Voice | Records a voice note; the server transcribes it with local Whisper | `VoicePlugin.swift`, server `cos/voice.py` |

Pages in the web app reach these through `window.COSNative` (`app/cos/web/static/voice-ios.js`). That script does nothing in a browser, so the PWA is unchanged.

## The server URL

The shell does **not** bundle the web app. Its WebView loads the live server, so relative `/api/...` calls and the sign-in cookie work exactly as in the PWA. A change to the web app goes live without a new iPhone build; only Swift changes need one.

The URL is set when you sync, from `COS_SERVER_URL` (default `http://localhost:8700`):

| Where the app runs | `COS_SERVER_URL` |
|---|---|
| Simulator, server on the same Mac | `http://localhost:8700` |
| iPhone on the same Wi-Fi as the Mac | `http://<Mac's LAN IP>:8700` |
| Hosted | `https://<your host>` (production must be HTTPS) |

`ios-shell/www/index.html` is only the "Can't reach your Chief of Staff server" fallback page.

Run a development server on the Mac:

```bash
cd app && python3.12 -m venv .venv && source .venv/bin/activate   # Python 3.12 or newer
pip install -e '.[push,voice]'
COS_SECURE_COOKIE=0 COS_API_TOKEN=<your key> COS_SCHEDULER=0 cos serve   # port 8700
```

`COS_SECURE_COOKIE=0` is for plain-`http` development only. By default the sign-in cookie is marked Secure (HTTPS only), and the iOS WebView drops Secure cookies on `http://localhost`, so sign-in loops back to the access key page. A hosted HTTPS server keeps the default.

## Build it (on a Mac)

Needs Node 18+, Xcode 15+ and CocoaPods (`brew install cocoapods`). Push and running on a phone need a paid Apple Developer account.

```bash
cd ios-shell
npm install
COS_SERVER_URL=http://localhost:8700 npx cap sync ios   # also runs pod install
npx cap open ios                                         # opens Xcode
```

The project is already set up:
- The four Swift files are in the App target.
- `Main.storyboard`'s Bridge View Controller uses `MainViewController`, which registers the Calendar and Voice plugins. Capacitor 6 doesn't register plugins compiled into the app by itself.
- `Info.plist` has the calendar and microphone usage strings, `UIBackgroundModes` (`remote-notification`, `fetch`, `processing`), and `BGTaskSchedulerPermittedIdentifiers`. The task ids are `$(PRODUCT_BUNDLE_IDENTIFIER).refresh` and `.process`, so they follow the bundle id.

Set the bundle id in `ios-shell/capacitor.config.ts` (`appId`) and in Xcode (App target → General → Bundle Identifier). It must match the App ID in the Apple Developer portal.

## In Xcode

1. In the left sidebar (the Project navigator), click the blue **App** project, then the **App** target under TARGETS.
2. Go to **Signing & Capabilities**:
   - Choose your **Team** and check **Automatically manage signing**.
   - Click **+ Capability** and add **Push Notifications**.
   - Click **+ Capability** again and add **Background Modes**. Check **Remote notifications**, **Background fetch** and **Background processing**.
3. Check the setup:
   - Open `App/Base.lproj/Main.storyboard`, select the view controller, and open the Identity inspector (right sidebar). Custom Class should be `MainViewController`, Module `App`.
   - Select each new `.swift` file. In the File inspector, **Target Membership: App** should be checked.
4. Run it in the Simulator (pick a simulator in the toolbar, then ▶) for the UI and sign-in. Then plug in your iPhone, pick it in the toolbar, and run again. The first time, trust the developer certificate on the phone under Settings → General → VPN & Device Management.

## Background sync settings

`SyncEngine` uses these:
- The server address: `cos.api.base` in UserDefaults, falling back to the server URL the app was synced with.
- The API token: `cos.api.token`, stored in the **Keychain**, never in UserDefaults or the WebView's localStorage.

Set them once with `SyncEngine.configure(base:token:)`. For now that's from the Xcode debugger; a small native settings sheet is planned.

## Check it on the iPhone

- **Push:** `/api/push/status` shows at least one token. Then `POST /api/check/run` from the Mac should wake the phone.
- **Calendar:** in Safari → Develop → [your iPhone] → the app's page, run `COSNative.calendarAccess('full')`, then `COSNative.createEvent({title, start, end})`. The event appears in the Calendar app.
- **Voice:** run `COSNative.startRecording()`, speak, then `COSNative.stopRecording()`. It returns the text from `/api/voice/transcribe`.
- **Background:** lock the phone, trigger a check, then open the app and confirm the data is fresh.

## Limits

- Silent pushes are best effort, and iOS throttles them. Background refresh only speeds things up; opening the app is what reliably gets fresh data.
- EventKit only sees calendars synced to the phone. Google and Microsoft on the server stay the source of truth.
- Apple rejects plain web wrappers. The native features are what make the app acceptable for the App Store.
