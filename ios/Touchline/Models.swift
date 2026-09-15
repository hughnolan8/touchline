import Foundation

struct Simulation: Codable, Identifiable, Hashable {
    let id: Int
    let home, away, competition, kickoff, createdAt, status: String
    let stake: Double
    let profit: Double?
    let settledAt, reason: String?
    let market, selection: String
    let line: Double?
    let bookmaker: String
    let odds, probability, edge: Double
    let quoteTime: String?
    let strategyVersion: Int
    let stakeMode: String
    let bankrollAtEntry: Double
    let modelId: Int
    var title: String { "\(home) vs \(away)" }
    var marketTitle: String {
        if market == "1x2" { return selection == "home" ? home : selection == "away" ? away : "Draw" }
        return "\(selection.capitalized) \(line.map { $0.formatted() } ?? "") goals"
    }
    var isOpen: Bool { status == "open" || status == "review" }
}
struct BetPage: Codable { let items: [Simulation]; let nextCursor: Int? }
struct EquityPoint: Codable, Identifiable { let date: String; let equity: Double; var id: String { date } }
struct Account: Codable {
    let balance, available, reserved, profit: Double
    let roi, winRate: Double?
    let settled, open: Int
    let drawdown: Double
    let curve: [EquityPoint]
}
struct EngineJob: Codable, Identifiable { let id, kind, status: String; let attempts: Int; let message: String? }
struct SkipReason: Codable, Identifiable { let reason: String; let count: Int; var id: String { reason } }
struct Strategy: Codable {
    var enabled: Bool
    var stakeMode: String
    var kellyFraction, maxBetFraction, minStake, stake, minEdge, maxExposure: Double
    var maxQuoteAge, windowStart, windowEnd, version: Int
}
struct DataSettings: Codable {
    var version: Int
    var autoRefresh: Bool
    var intervalMinutes, dailyCreditLimit, quotaReserve: Int
}
struct EngineStatus: Codable {
    let status: String
    let lastSuccess, lastAttempt: String?
    let configured: Bool
    let dailyCredits: Double
    let providerRemaining: Double?
    let trainedLeagues: [String]
    let jobs: [EngineJob]
    let reasons: [SkipReason]
    var strategy: Strategy
    var dataSettings: DataSettings
}
struct Dashboard: Codable {
    let generatedAt, mode: String
    let account: Account
    var engine: EngineStatus
    let recent: [Simulation]
}

enum Wire {
    static var decoder: JSONDecoder { let d = JSONDecoder(); d.keyDecodingStrategy = .convertFromSnakeCase; return d }
    static var encoder: JSONEncoder { let e = JSONEncoder(); e.keyEncodingStrategy = .convertToSnakeCase; return e }
    static func date(_ text: String?) -> Date? {
        guard let text else { return nil }
        let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let value = f.date(from: text) { return value }
        f.formatOptions = [.withInternetDateTime]; return f.date(from: text)
    }
}
extension Double {
    var money: String { formatted(.currency(code: "GBP")) }
    var percent: String { formatted(.percent.precision(.fractionLength(1))) }
}
