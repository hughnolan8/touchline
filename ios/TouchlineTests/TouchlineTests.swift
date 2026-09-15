import XCTest
import SwiftUI
@testable import Touchline

final class TouchlineTests: XCTestCase {
    @MainActor func testDarkScreenRendering() async throws {
        let store = AppStore()
        let host = UIHostingController(rootView: ConnectView().environmentObject(store)
            .preferredColorScheme(.dark).tint(Theme.mint))
        let window = UIWindow(frame: CGRect(x: 0, y: 0, width: 393, height: 852))
        window.rootViewController = host
        window.makeKeyAndVisible()
        defer { window.isHidden = true }
        host.view.frame = window.bounds
        host.view.setNeedsLayout()
        host.view.layoutIfNeeded()
        try await Task.sleep(for: .milliseconds(700))
        let image = UIGraphicsImageRenderer(bounds: host.view.bounds).image { _ in
            XCTAssertTrue(host.view.drawHierarchy(in: host.view.bounds, afterScreenUpdates: true))
        }
        let attachment = XCTAttachment(image: image)
        attachment.name = "Touchline-dark-connection"
        attachment.lifetime = .keepAlways
        add(attachment)
    }
    @MainActor func testInitialOverviewRendering() async throws {
        let store = AppStore()
        let strategy = Strategy(enabled: true, stakeMode: "kelly", kellyFraction: 0.25,
            maxBetFraction: 0.02, minStake: 1, stake: 10, minEdge: 0.05, maxExposure: 0.1,
            maxQuoteAge: 15, windowStart: 60, windowEnd: 15, version: 1)
        let engine = EngineStatus(status: "starting", lastSuccess: nil, lastAttempt: nil,
            configured: true, dailyCredits: 0, providerRemaining: nil, trainedLeagues: [],
            jobs: [], reasons: [], strategy: strategy,
            dataSettings: DataSettings(version: 1, autoRefresh: true, intervalMinutes: 15, dailyCreditLimit: 100, quotaReserve: 10))
        let account = Account(balance: 1000, available: 1000, reserved: 0, profit: 0,
            roi: nil, winRate: nil, settled: 0, open: 0, drawdown: 0,
            curve: [EquityPoint(date: "Start", equity: 1000)])
        store.dashboard = Dashboard(generatedAt: "2026-09-11T17:40:00Z", mode: "paper", account: account, engine: engine, recent: [])
        let host = UIHostingController(rootView: NavigationStack { OverviewView() }
            .environmentObject(store).preferredColorScheme(.dark).tint(Theme.mint))
        let window = UIWindow(frame: CGRect(x: 0, y: 0, width: 393, height: 852))
        window.rootViewController = host; window.makeKeyAndVisible()
        defer { window.isHidden = true }
        host.view.frame = window.bounds; host.view.setNeedsLayout(); host.view.layoutIfNeeded()
        try await Task.sleep(for: .milliseconds(700))
        let image = UIGraphicsImageRenderer(bounds: host.view.bounds).image { _ in
            XCTAssertTrue(host.view.drawHierarchy(in: host.view.bounds, afterScreenUpdates: true))
        }
        let attachment = XCTAttachment(image: image)
        attachment.name = "Touchline-dark-initial-overview"; attachment.lifetime = .keepAlways; add(attachment)
    }
    func testDatesAcceptBothServerFormats() {
        XCTAssertNotNil(Wire.date("2026-09-11T12:00:00.123456+00:00"))
        XCTAssertNotNil(Wire.date("2026-09-11T12:00:00+00:00"))
        XCTAssertNil(Wire.date("Start"))
    }
    @MainActor func testConnectionRejectsUnsafeOrAmbiguousOrigins() throws {
        XCTAssertThrowsError(try AppStore.validateURL("http://example.com"))
        XCTAssertThrowsError(try AppStore.validateURL("https://example.com/api"))
        XCTAssertThrowsError(try AppStore.validateURL("https://user:password@example.com"))
        XCTAssertNoThrow(try AppStore.validateURL("https://mobile.up.railway.app"))
    }
    func testVersionedSettingsWireRoundTrip() throws {
        let raw = Data(#"{"version":4,"auto_refresh":true,"interval_minutes":15,"daily_credit_limit":100,"quota_reserve":10}"#.utf8)
        let value = try Wire.decoder.decode(DataSettings.self, from: raw)
        XCTAssertEqual(value.version, 4)
        XCTAssertEqual(value.dailyCreditLimit, 100)
        let roundtrip = try JSONSerialization.jsonObject(with: Wire.encoder.encode(value)) as! [String: Any]
        XCTAssertEqual(roundtrip["quota_reserve"] as? Int, 10)
    }
    func testSimulationDecodesNullSettlementAndLockedDecision() throws {
        let raw = Data(#"{"id":1,"home":"Arsenal","away":"Chelsea","competition":"E0","kickoff":"2026-09-12T15:00:00Z","created_at":"2026-09-12T14:30:00Z","status":"open","stake":20,"profit":null,"settled_at":null,"reason":null,"market":"1x2","selection":"home","line":null,"bookmaker":"Bet365","odds":2,"probability":0.6,"edge":0.2,"quote_time":"2026-09-12T14:29:00Z","strategy_version":1,"stake_mode":"kelly","bankroll_at_entry":1000,"model_id":4}"#.utf8)
        let bet = try Wire.decoder.decode(Simulation.self, from: raw)
        XCTAssertTrue(bet.isOpen)
        XCTAssertEqual(bet.marketTitle, "Arsenal")
        XCTAssertEqual(bet.modelId, 4)
        XCTAssertNil(bet.profit)
    }
}
