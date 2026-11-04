import UIKit
import BackgroundTasks
import UserNotifications
import Capacitor

@UIApplicationMain
class AppDelegate: UIResponder, UIApplicationDelegate {

    var window: UIWindow?

    /// Background task ids: the bundle id plus a suffix. Info.plist lists the same two under
    /// BGTaskSchedulerPermittedIdentifiers as $(PRODUCT_BUNDLE_IDENTIFIER).refresh / .process.
    static var bundleId: String { Bundle.main.bundleIdentifier ?? "chiefofstaff" }
    static var refreshTaskId: String { bundleId + ".refresh" }
    static var processTaskId: String { bundleId + ".process" }

    static let apnsTokenKey = "cos.apns.token"

    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {
        registerBackgroundTasks()
        reachServerFromApp()
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .badge, .sound]) { granted, _ in
            // Silent (content-available) pushes need only remote-notification registration, so register either way.
            DispatchQueue.main.async { application.registerForRemoteNotifications() }
            _ = granted
        }
        return true
    }

    func applicationDidEnterBackground(_ application: UIApplication) {
        scheduleRefresh()
        scheduleProcessing()
    }

    // MARK: Local network

    /// Ask iOS for local network access from the app itself (see SyncEngine.pingServer), then reload the
    /// web view once the server answers, in case its first load was blocked while the prompt was up.
    private func reachServerFromApp() {
        Task {
            for attempt in 0..<6 {
                if await SyncEngine.shared.pingServer() {
                    if attempt > 0 {
                        await MainActor.run {
                            (self.window?.rootViewController as? CAPBridgeViewController)?.webView?.reload()
                        }
                    }
                    return
                }
                try? await Task.sleep(nanoseconds: 5_000_000_000)  // the prompt may still be on screen
            }
        }
    }

    // MARK: Background tasks

    private func registerBackgroundTasks() {
        BGTaskScheduler.shared.register(forTaskWithIdentifier: Self.refreshTaskId, using: nil) { task in
            self.handle(task)
            self.scheduleRefresh()
        }
        BGTaskScheduler.shared.register(forTaskWithIdentifier: Self.processTaskId, using: nil) { task in
            self.handle(task)
        }
    }

    private func handle(_ task: BGTask) {
        let work = Task {
            await SyncEngine.shared.runOnce()
            task.setTaskCompleted(success: !Task.isCancelled)
        }
        task.expirationHandler = { work.cancel() }
    }

    func scheduleRefresh() {
        let request = BGAppRefreshTaskRequest(identifier: Self.refreshTaskId)
        request.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)  // no sooner than 15 minutes out
        try? BGTaskScheduler.shared.submit(request)
    }

    func scheduleProcessing() {
        let request = BGProcessingTaskRequest(identifier: Self.processTaskId)
        request.requiresNetworkConnectivity = true
        request.requiresExternalPower = false
        request.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)
        try? BGTaskScheduler.shared.submit(request)
    }

    // MARK: Remote notifications

    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        let hex = deviceToken.map { String(format: "%02x", $0) }.joined()
        UserDefaults.standard.set(hex, forKey: Self.apnsTokenKey)
        // Hand it to Capacitor so the JS `registration` event fires (COSNative.registerPush posts it to the server).
        NotificationCenter.default.post(name: .capacitorDidRegisterForRemoteNotifications, object: deviceToken)
    }

    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        NotificationCenter.default.post(name: .capacitorDidFailToRegisterForRemoteNotifications, object: error)
    }

    func application(_ application: UIApplication, didReceiveRemoteNotification userInfo: [AnyHashable: Any],
                     fetchCompletionHandler completionHandler: @escaping (UIBackgroundFetchResult) -> Void) {
        Task {
            await SyncEngine.shared.runOnce()
            completionHandler(.newData)
        }
    }

    // MARK: Capacitor hooks (kept from the generated file)

    func application(_ app: UIApplication, open url: URL, options: [UIApplication.OpenURLOptionsKey: Any] = [:]) -> Bool {
        return ApplicationDelegateProxy.shared.application(app, open: url, options: options)
    }

    func application(_ application: UIApplication, continue userActivity: NSUserActivity, restorationHandler: @escaping ([UIUserActivityRestoring]?) -> Void) -> Bool {
        return ApplicationDelegateProxy.shared.application(application, continue: userActivity, restorationHandler: restorationHandler)
    }

}
