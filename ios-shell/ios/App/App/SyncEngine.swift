import Foundation
import Security

/// One API call waiting to be replayed against the server.
struct SyncOp: Codable, Equatable {
    var path: String       // e.g. "/api/messages"
    var method: String     // GET, POST, PATCH, PUT, DELETE
    var body: Data?        // JSON body, if any
}

/// Replays queued API calls when the app wakes in the background (silent push or BG task).
///
/// The server address is `cos.api.base` in UserDefaults (falling back to the server url the shell was
/// built with). The API token lives in the Keychain under `cos.api.token`, never in UserDefaults and
/// never in the WebView's localStorage.
actor SyncEngine {
    static let shared = SyncEngine()

    static let queueKey = "cos.sync.queue"
    static let baseKey = "cos.api.base"
    static let tokenKey = "cos.api.token"

    private let defaults = UserDefaults.standard
    private let session: URLSession = {
        let cfg = URLSessionConfiguration.default
        cfg.timeoutIntervalForRequest = 20
        return URLSession(configuration: cfg)
    }()

    // MARK: Queue

    func enqueue(_ op: SyncOp) {
        var q = load()
        q.append(op)
        save(q)
    }

    func pending() -> [SyncOp] { load() }

    private func load() -> [SyncOp] {
        guard let data = defaults.data(forKey: Self.queueKey) else { return [] }
        return (try? JSONDecoder().decode([SyncOp].self, from: data)) ?? []
    }

    private func save(_ q: [SyncOp]) {
        defaults.set(try? JSONEncoder().encode(q), forKey: Self.queueKey)
    }

    // MARK: Run

    /// Replays every queued op, keeps the ones that fail, then pings /api/status to keep the session warm.
    func runOnce() async {
        guard let base = Self.baseURL() else { return }
        let token = Keychain.get(Self.tokenKey)
        var kept: [SyncOp] = []
        for op in load() {
            if Task.isCancelled { kept.append(op); continue }
            if await !send(op, base: base, token: token) { kept.append(op) }
        }
        save(kept)
        _ = await send(SyncOp(path: "/api/status", method: "GET", body: nil), base: base, token: token)
    }

    private func send(_ op: SyncOp, base: URL, token: String?) async -> Bool {
        guard let url = URL(string: op.path, relativeTo: base) else { return false }
        var req = URLRequest(url: url)
        req.httpMethod = op.method
        if let token, !token.isEmpty { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let body = op.body {
            req.httpBody = body
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        do {
            let resp = try await fetch(req)
            guard let http = resp as? HTTPURLResponse else { return false }
            return (200..<300).contains(http.statusCode)
        } catch {
            return false
        }
    }

    /// async wrapper over dataTask (URLSession's own async API needs iOS 15; the shell targets iOS 13).
    private func fetch(_ req: URLRequest) async throws -> URLResponse? {
        try await withCheckedThrowingContinuation { cont in
            session.dataTask(with: req) { _, resp, error in
                if let error { cont.resume(throwing: error) } else { cont.resume(returning: resp) }
            }.resume()
        }
    }

    // MARK: Configuration

    static func baseURL() -> URL? {
        if let s = UserDefaults.standard.string(forKey: baseKey), let u = URL(string: s) { return u }
        // Fall back to server.url from capacitor.config.json, copied into the app bundle by `cap sync`.
        guard let file = Bundle.main.url(forResource: "capacitor.config", withExtension: "json"),
              let data = try? Data(contentsOf: file),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let server = json["server"] as? [String: Any],
              let s = server["url"] as? String else { return nil }
        return URL(string: s)
    }

    /// Set the server address and API token once (from a settings sheet or the debugger).
    static func configure(base: String?, token: String?) {
        if let base { UserDefaults.standard.set(base, forKey: baseKey) }
        if let token { Keychain.set(tokenKey, token) }
    }
}

/// Minimal Keychain wrapper for one string per key.
enum Keychain {
    private static func query(_ key: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: Bundle.main.bundleIdentifier ?? "chiefofstaff",
         kSecAttrAccount as String: key]
    }

    static func get(_ key: String) -> String? {
        var q = query(key)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let data = out as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func set(_ key: String, _ value: String) {
        SecItemDelete(query(key) as CFDictionary)
        guard !value.isEmpty else { return }
        var q = query(key)
        q[kSecValueData as String] = Data(value.utf8)
        q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock  // readable in the background after first unlock
        SecItemAdd(q as CFDictionary, nil)
    }
}
