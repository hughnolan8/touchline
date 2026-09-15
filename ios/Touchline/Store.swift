import Foundation
import Security
import SwiftUI
import UserNotifications

struct Connection: Codable { let baseURL: String; let token: String }

enum BetNotifications {
    private static let seenBetIDKey = "touchline.seen-bet-id"

    static var seenBetID: Int {
        get { UserDefaults.standard.integer(forKey: seenBetIDKey) }
        set { UserDefaults.standard.set(newValue, forKey: seenBetIDKey) }
    }

    static func requestPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
    }

    static func seed(_ bets: [Simulation]) {
        guard let latest = bets.map(\.id).max(), latest > seenBetID else { return }
        seenBetID = latest
    }

    static func notifyNewBets(_ bets: [Simulation]) {
        let previous = seenBetID
        let newest = bets.map(\.id).max() ?? previous
        let newBets = bets.filter { $0.id > previous }.sorted { $0.id < $1.id }
        guard !newBets.isEmpty else {
            if newest > previous { seenBetID = newest }
            return
        }
        seenBetID = max(previous, newest)
        for bet in newBets {
            notify(bet)
        }
    }

    private static func notify(_ bet: Simulation) {
        let content = UNMutableNotificationContent()
        content.title = "Touchline placed a paper bet"
        content.body = "\(bet.title): \(bet.marketTitle), \(bet.stake.money) at \(bet.odds.formatted(.number.precision(.fractionLength(2))))"
        content.sound = .default
        let request = UNNotificationRequest(identifier: "touchline-bet-\(bet.id)", content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }

    static func reset() {
        UserDefaults.standard.removeObject(forKey: seenBetIDKey)
        UNUserNotificationCenter.current().removeAllPendingNotificationRequests()
    }
}

enum Vault {
    private static let service = "com.touchline.mobile.connection"
    static func load() -> Connection? {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service, kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess, let data = result as? Data else { return nil }
        return try? JSONDecoder().decode(Connection.self, from: data)
    }
    static func save(_ value: Connection) throws {
        let data = try JSONEncoder().encode(value)
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service]
        SecItemDelete(query as CFDictionary)
        var item = query
        item[kSecValueData as String] = data
        item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        guard SecItemAdd(item as CFDictionary, nil) == errSecSuccess else { throw APIError.message("Unable to save the connection securely.") }
    }
    static func clear() { SecItemDelete([kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service] as CFDictionary) }
}

enum APIError: LocalizedError {
    case cancelled
    case message(String)
    var errorDescription: String? {
        switch self {
        case .cancelled: "Connection was interrupted. Keep Touchline open and try again."
        case .message(let text): text
        }
    }
}

@MainActor final class AppStore: ObservableObject {
    @Published var dashboard: Dashboard?
    @Published var bets: [Simulation] = []
    @Published var nextCursor: Int?
    @Published var connected = false
    @Published var offline = false
    @Published var busy = false
    @Published var error: String?
    private var connection: Connection?
    private let session: URLSession
    private let cacheURL: URL
    private var refreshing = false

    init(session: URLSession = .shared) {
        self.session = session
        cacheURL = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0].appendingPathComponent("touchline-summary.json")
        connection = Vault.load(); connected = connection != nil
        if connected, let data = try? Data(contentsOf: cacheURL) {
            dashboard = try? Wire.decoder.decode(Dashboard.self, from: data)
            offline = dashboard != nil
        }
    }
    static func validateURL(_ text: String) throws -> URL {
        guard let url = URL(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
              url.scheme == "https", url.host != nil, url.user == nil, url.password == nil,
              url.query == nil, url.fragment == nil, url.path.isEmpty || url.path == "/" else {
            throw APIError.message("Enter the HTTPS origin of your app backend, without a path.")
        }
        return url
    }
    func connect(url: String, token: String) async {
        busy = true; error = nil
        defer { busy = false }
        do {
            let base = try Self.validateURL(url).absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
            let secret = token.trimmingCharacters(in: .whitespacesAndNewlines)
            guard secret.count >= 32 else { throw APIError.message("Enter the owner token provided during backend setup.") }
            connection = Connection(baseURL: base, token: secret)
            let value: Dashboard = try await request("/api/v1/summary")
            try Vault.save(connection!)
            dashboard = value; connected = true; offline = false
            BetNotifications.requestPermission()
            BetNotifications.seed(value.recent)
            try? Wire.encoder.encode(value).write(to: cacheURL, options: [.atomic, .completeFileProtection])
        } catch { connection = nil; self.error = error.localizedDescription }
    }
    func request<T: Decodable>(_ path: String, method: String = "GET", body: Data? = nil) async throws -> T {
        guard let connection, let url = URL(string: connection.baseURL + path) else { throw APIError.message("Connect your backend first.") }
        var req = URLRequest(url: url); req.httpMethod = method; req.httpBody = body; req.timeoutInterval = 30
        req.setValue("Bearer \(connection.token)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: req)
        } catch let error as URLError where error.code == .cancelled {
            throw APIError.cancelled
        }
        guard let http = response as? HTTPURLResponse else { throw APIError.message("Unexpected server response.") }
        if http.statusCode == 401 { throw APIError.message("Access token was rejected. Reconnect with the current owner token.") }
        if http.statusCode == 503 { throw APIError.message("The engine database is temporarily unavailable. Automatic runs will resume when service is restored.") }
        if http.statusCode == 409 { throw APIError.message("Settings changed elsewhere. Close this sheet, refresh, and try again.") }
        guard (200..<300).contains(http.statusCode) else {
            throw APIError.message(http.statusCode == 422 ? "Check the values and entry window before saving." : "Backend unavailable (HTTP \(http.statusCode)). Please try again.")
        }
        return try Wire.decoder.decode(T.self, from: data)
    }
    func refresh() async {
        guard connected, !refreshing else { return }
        refreshing = true
        defer { refreshing = false }
        do {
            let value: Dashboard = try await request("/api/v1/summary")
            dashboard = value; offline = false; error = nil
            BetNotifications.notifyNewBets(value.recent)
            try? Wire.encoder.encode(value).write(to: cacheURL, options: [.atomic, .completeFileProtection])
        } catch APIError.cancelled {
            // iOS cancels in-flight work when the app becomes inactive. Keep the
            // last successful state instead of presenting that as a backend failure.
        } catch { offline = true; self.error = error.localizedDescription }
    }
    func loadBets(state: String, more: Bool = false) async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        do {
            let cursor = more ? nextCursor.map { "&cursor=\($0)" } ?? "" : ""
            let page: BetPage = try await request("/api/v1/bets?state=\(state)" + cursor)
            bets = more ? bets + page.items : page.items
            nextCursor = page.nextCursor
            if !more { BetNotifications.notifyNewBets(page.items) }
            error = nil
        } catch { self.error = error.localizedDescription }
    }
    func save(strategy: Strategy) async throws {
        let _: Strategy = try await request("/api/v1/strategy", method: "PUT", body: Wire.encoder.encode(strategy))
        await refresh()
    }
    func save(data: DataSettings) async throws {
        let _: DataSettings = try await request("/api/v1/data-settings", method: "PUT", body: Wire.encoder.encode(data))
        await refresh()
    }
    func toggleEngine() async {
        guard var strategy = dashboard?.engine.strategy, !offline else { return }
        busy = true
        defer { busy = false }
        strategy.enabled.toggle()
        do { try await save(strategy: strategy) } catch { self.error = error.localizedDescription }
    }
    func disconnect() {
        Vault.clear(); connection = nil; connected = false; dashboard = nil; bets = []; error = nil
        BetNotifications.reset()
        try? FileManager.default.removeItem(at: cacheURL)
    }
}
