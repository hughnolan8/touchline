import SwiftUI
import Charts

enum Theme {
    static let background = Color(red: 0.035, green: 0.045, blue: 0.065)
    static let card = Color(red: 0.075, green: 0.09, blue: 0.115)
    static let mint = Color(red: 0.47, green: 0.94, blue: 0.75)
    static let violet = Color(red: 0.66, green: 0.62, blue: 1)
}
struct Card<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View { content.padding(20).frame(maxWidth: .infinity, alignment: .leading).background(Theme.card, in: RoundedRectangle(cornerRadius: 22)) }
}
struct Caption: View {
    let text: String
    var body: some View { Text(text.uppercased()).font(.system(size: 11, weight: .semibold, design: .monospaced)).tracking(1.6).foregroundStyle(.secondary) }
}
struct StatusPill: View {
    let text: String
    var body: some View {
        HStack(spacing: 6) { Circle().fill(color).frame(width: 6, height: 6); Text(text.capitalized).font(.caption.weight(.semibold)) }
            .padding(.horizontal, 10).padding(.vertical, 6).background(color.opacity(0.1), in: Capsule()).foregroundStyle(color)
    }
    var color: Color { ["running", "won", "done"].contains(text) ? Theme.mint : ["lost", "failed", "overdue"].contains(text) ? .orange : Theme.violet }
}
struct Page<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View { ScrollView { VStack(alignment: .leading, spacing: 18) { content }.padding(20) }.background(Theme.background) }
}
struct RootView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.scenePhase) private var phase
    var body: some View {
        Group {
            if store.connected {
                TabView {
                    NavigationStack { OverviewView() }.tabItem { Label("Overview", systemImage: "square.grid.2x2.fill") }
                    NavigationStack { BetsView() }.tabItem { Label("Simulations", systemImage: "list.bullet.rectangle.portrait") }
                    NavigationStack { PerformanceView() }.tabItem { Label("Performance", systemImage: "chart.xyaxis.line") }
                    NavigationStack { EngineView() }.tabItem { Label("Engine", systemImage: "slider.horizontal.3") }
                }
                .toolbarBackground(Theme.background, for: .tabBar)
            } else { ConnectView() }
        }
        .task(id: phase) {
            guard phase == .active else { return }
            await store.refresh()
            while !Task.isCancelled {
                do { try await Task.sleep(for: .seconds(30)) } catch { return }
                await store.refresh()
            }
        }
    }
}
struct ConnectView: View {
    @EnvironmentObject private var store: AppStore
    @State private var url = "https://api-production-f10dd.up.railway.app"
    @State private var token = ""
    var body: some View {
        Page {
            HStack { Image(systemName: "waveform.path").font(.title).foregroundStyle(Theme.mint); Text("TOUCHLINE").font(.system(.headline, design: .monospaced)).tracking(4) }.padding(.top, 35)
            Spacer().frame(height: 30)
            Text("Your engine.\nAlways in play.").font(.system(size: 43, weight: .semibold)).tracking(-1.5)
            Text("An independent football simulation desk. Follow every decision, from the first price to the final whistle.").font(.body).foregroundStyle(.secondary).lineSpacing(5)
            HStack { Label("AUTOMATIC", systemImage: "bolt.fill"); Text("•"); Text("PAPER ONLY") }.font(.system(size: 10, weight: .semibold, design: .monospaced)).tracking(1).foregroundStyle(Theme.mint).padding(.vertical, 15)
            Card {
                VStack(alignment: .leading, spacing: 16) {
                    Text("Connect your engine").font(.title3.weight(.semibold))
                    Text("Use the separate mobile backend address and your private owner token.").font(.footnote).foregroundStyle(.secondary)
                    TextField("https://your-api.up.railway.app", text: $url).keyboardType(.URL).textContentType(.URL).autocorrectionDisabled().textInputAutocapitalization(.never).padding(14).background(Theme.background, in: RoundedRectangle(cornerRadius: 12)).accessibilityLabel("Backend URL")
                    SecureField("Owner token", text: $token).textInputAutocapitalization(.never).autocorrectionDisabled().padding(14).background(Theme.background, in: RoundedRectangle(cornerRadius: 12))
                    if let error = store.error { Text(error).font(.footnote).foregroundStyle(.orange) }
                    Button { Task { await store.connect(url: url, token: token) } } label: {
                        HStack { Text(store.busy ? "Connecting…" : "Connect securely"); Spacer(); Image(systemName: "arrow.right") }.font(.headline).padding(16).foregroundStyle(Theme.background).background(Theme.mint, in: RoundedRectangle(cornerRadius: 12))
                    }.disabled(store.busy || url.isEmpty || token.isEmpty)
                }
            }
            Label("Your token is stored in iPhone Keychain.", systemImage: "lock.shield").font(.footnote).foregroundStyle(.secondary)
        }
    }
}
struct SyncBanner: View {
    @EnvironmentObject private var store: AppStore
    var body: some View {
        if let error = store.error {
            VStack(alignment: .leading, spacing: 5) {
                Label(store.offline ? "Showing saved data" : "Connection notice", systemImage: "wifi.exclamationmark").font(.footnote.weight(.semibold))
                Text(error).font(.caption)
            }.foregroundStyle(.orange).padding(14).frame(maxWidth: .infinity, alignment: .leading).background(.orange.opacity(0.08), in: RoundedRectangle(cornerRadius: 14))
        }
    }
}
struct OverviewView: View {
    @EnvironmentObject private var store: AppStore
    var body: some View {
        Page {
            SyncBanner()
            if let d = store.dashboard {
                HStack { Caption(text: "Independent paper portfolio"); Spacer(); StatusPill(text: d.engine.status) }
                Card {
                    VStack(alignment: .leading, spacing: 14) {
                        Caption(text: "Virtual bankroll")
                        Text(d.account.balance.money).font(.system(size: 46, weight: .medium, design: .rounded)).minimumScaleFactor(0.6).lineLimit(1)
                        HStack { Text(d.account.profit.money).foregroundStyle(d.account.profit >= 0 ? Theme.mint : .orange); Text("all-time P&L").foregroundStyle(.secondary) }.font(.subheadline)
                        EquityChart(points: d.account.curve).frame(height: 100).padding(.top, 12)
                        Divider()
                        HStack { Metric(label: "Available", value: d.account.available.money); Spacer(); Metric(label: "Reserved", value: d.account.reserved.money) }
                    }
                }
                HStack(spacing: 14) {
                    Card { Metric(label: "Open simulations", value: "\(d.account.open)") }
                    Card { Metric(label: "Return on stake", value: d.account.roi?.percent ?? "—") }
                }
                Card {
                    HStack(alignment: .top, spacing: 14) {
                        Image(systemName: "bolt.horizontal.circle.fill").font(.title).foregroundStyle(Theme.mint)
                        VStack(alignment: .leading, spacing: 6) {
                            Text(d.engine.strategy.enabled ? "The engine takes it from here" : "New entries are paused").font(.headline)
                            Text(d.engine.configured ? "\(d.engine.trainedLeagues.count) of 5 leagues trained. Selection and settlement run on the server." : "The backend needs its Odds API key before it can collect current prices.").font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                }
                Caption(text: "Latest activity")
                if d.recent.isEmpty { EmptyState(title: "Waiting for the first simulation", message: "The engine needs trained models, fresh prices, and an eligible match. It never fills the ledger with invented bets.") }
                ForEach(d.recent) { bet in NavigationLink(value: bet) { BetRow(bet: bet) }.buttonStyle(.plain) }
                if let date = Wire.date(d.generatedAt) { Text("Updated \(date.formatted(date: .abbreviated, time: .shortened))").font(.caption).foregroundStyle(.secondary) }
            } else { ProgressView("Connecting to your engine…").frame(maxWidth: .infinity).padding(40) }
        }
        .navigationTitle("Touchline").navigationDestination(for: Simulation.self) { BetDetail(bet: $0) }
        .refreshable { await store.refresh() }
    }
}
struct Metric: View {
    let label, value: String
    var body: some View { VStack(alignment: .leading, spacing: 8) { Text(label).font(.caption).foregroundStyle(.secondary); Text(value).font(.title3.weight(.semibold)).monospacedDigit().minimumScaleFactor(0.6).lineLimit(1) } }
}
struct EquityChart: View {
    let points: [EquityPoint]
    var body: some View {
        Chart(Array(points.enumerated()), id: \.offset) { index, point in
            LineMark(x: .value("Simulation", index), y: .value("Bankroll", point.equity)).foregroundStyle(Theme.mint).interpolationMethod(.linear)
            if points.count == 1 { PointMark(x: .value("Simulation", index), y: .value("Bankroll", point.equity)).foregroundStyle(Theme.mint) }
        }.chartXAxis(.hidden).chartYAxis(.hidden).chartYScale(domain: domain)
            .accessibilityLabel("Virtual bankroll history, \(points.count) observations")
    }
    var domain: ClosedRange<Double> {
        let low = points.map(\.equity).min() ?? 1000, high = points.map(\.equity).max() ?? 1000
        let padding = max(10, (high - low) * 0.1); return (low-padding)...(high+padding)
    }
}
struct BetRow: View {
    let bet: Simulation
    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 12) {
                HStack { Caption(text: bet.competition); Spacer(); StatusPill(text: bet.status) }
                Text(bet.title).font(.headline)
                HStack { Text(bet.marketTitle).foregroundStyle(.secondary); Spacer(); Text(bet.odds.formatted(.number.precision(.fractionLength(2)))).foregroundStyle(Theme.mint).monospacedDigit() }.font(.subheadline)
                HStack { Text("\(bet.stake.money) virtual stake"); Spacer(); if let profit = bet.profit { Text(profit.money).foregroundStyle(profit >= 0 ? Theme.mint : .orange) } }.font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}
struct EmptyState: View {
    let title, message: String
    var body: some View { Card { VStack(alignment: .leading, spacing: 12) { Image(systemName: "circle.dotted").font(.title).foregroundStyle(Theme.violet); Text(title).font(.headline); Text(message).font(.subheadline).foregroundStyle(.secondary).lineSpacing(4) } } }
}
struct BetsView: View {
    @EnvironmentObject private var store: AppStore
    @State private var filter = "all"
    var body: some View {
        Page {
            Caption(text: "Every decision. Fully recorded.")
            Picker("Status", selection: $filter) { Text("All").tag("all"); Text("Open").tag("open"); Text("Settled").tag("settled") }.pickerStyle(.segmented)
            SyncBanner()
            if store.bets.isEmpty && !store.busy { EmptyState(title: "No simulations here yet", message: "Qualifying selections will appear automatically. Pull to refresh at any time.") }
            ForEach(store.bets) { bet in NavigationLink(value: bet) { BetRow(bet: bet) }.buttonStyle(.plain) }
            if store.nextCursor != nil { Button("Load more") { Task { await store.loadBets(state: filter, more: true) } }.disabled(store.busy).frame(maxWidth: .infinity) }
            if store.busy { ProgressView().frame(maxWidth: .infinity) }
        }.navigationTitle("Simulations").navigationDestination(for: Simulation.self) { BetDetail(bet: $0) }
            .task(id: filter) {
                await store.loadBets(state: filter)
                while !Task.isCancelled {
                    do { try await Task.sleep(for: .seconds(30)) } catch { return }
                    await store.loadBets(state: filter)
                }
            }
            .refreshable { await store.loadBets(state: filter) }
    }
}
struct BetDetail: View {
    let bet: Simulation
    var body: some View {
        Page {
            StatusPill(text: bet.status)
            Text(bet.title).font(.largeTitle.weight(.semibold))
            Text(bet.marketTitle).font(.title3).foregroundStyle(Theme.mint)
            Card {
                VStack(spacing: 16) {
                    detail("Recorded odds", bet.odds.formatted()); detail("Model probability", bet.probability.percent)
                    detail("Estimated edge", bet.edge.percent); detail("Virtual stake", bet.stake.money)
                    detail("Bookmaker observation", bet.bookmaker); detail("Profit / loss", bet.profit?.money ?? "Awaiting result")
                }
            }
            Card {
                VStack(alignment: .leading, spacing: 14) {
                    Caption(text: "Decision record")
                    detail("Sizing method", bet.stakeMode.capitalized); detail("Bankroll at entry", bet.bankrollAtEntry.money)
                    detail("Strategy version", "\(bet.strategyVersion)"); detail("Model version", "\(bet.modelId)")
                    detail("Recorded", timestamp(bet.createdAt)); detail("Price observed", timestamp(bet.quoteTime))
                    detail("Kickoff", timestamp(bet.kickoff))
                    if let settled = bet.settledAt { detail("Settled", timestamp(settled)) }
                    Text(bet.reason ?? "Awaiting verified full-time data. The virtual stake remains reserved.").font(.footnote).foregroundStyle(.secondary)
                }
            }
            Text("Paper simulation • No money was placed with a bookmaker.").font(.caption).foregroundStyle(.secondary)
        }.navigationTitle("Simulation #\(bet.id)").navigationBarTitleDisplayMode(.inline)
    }
    func detail(_ label: String, _ value: String) -> some View { HStack(alignment: .top) { Text(label).foregroundStyle(.secondary); Spacer(); Text(value).multilineTextAlignment(.trailing) }.font(.subheadline) }
    func timestamp(_ value: String?) -> String { Wire.date(value)?.formatted(date: .abbreviated, time: .shortened) ?? "Unavailable" }
}
struct PerformanceView: View {
    @EnvironmentObject private var store: AppStore
    var body: some View {
        Page {
            SyncBanner()
            if let a = store.dashboard?.account {
                Caption(text: "Forward simulation results")
                Card { VStack(alignment: .leading, spacing: 16) { Metric(label: "Net virtual profit", value: a.profit.money); EquityChart(points: a.curve).frame(height: 200); Text("Bankroll across settled simulations").font(.caption).foregroundStyle(.secondary) } }
                HStack { Card { Metric(label: "Return on stake", value: a.roi?.percent ?? "—") }; Card { Metric(label: "Win rate", value: a.winRate?.percent ?? "—") } }
                HStack { Card { Metric(label: "Settled", value: "\(a.settled)") }; Card { Metric(label: "Max drawdown", value: a.drawdown.percent) } }
                EmptyState(title: "Evidence grows over time", message: "These are forward paper results from recorded decisions. Small samples and estimated edges do not establish future profitability.")
            }
        }.navigationTitle("Performance").refreshable { await store.refresh() }
    }
}
struct EngineView: View {
    @EnvironmentObject private var store: AppStore
    @State private var strategySheet = false
    @State private var dataSheet = false
    @State private var disconnect = false
    var body: some View {
        Page {
            SyncBanner()
            if let e = store.dashboard?.engine {
                Card {
                    VStack(alignment: .leading, spacing: 18) {
                        HStack { Text("Automatic engine").font(.headline); Spacer(); StatusPill(text: e.status) }
                        Text("The server runs every five minutes. Your phone can be closed or offline.").font(.subheadline).foregroundStyle(.secondary)
                        Button { Task { await store.toggleEngine() } } label: { Label(e.strategy.enabled ? "Pause new entries" : "Resume automatic entries", systemImage: e.strategy.enabled ? "pause.fill" : "play.fill").frame(maxWidth: .infinity).padding(10) }.buttonStyle(.borderedProminent).foregroundStyle(Theme.background).disabled(store.busy || store.offline)
                        Text("Pausing entries keeps result collection and settlement running.").font(.caption).foregroundStyle(.secondary)
                    }
                }
                HStack { Card { Metric(label: "Credits today", value: "\(Int(e.dailyCredits)) / \(e.dataSettings.dailyCreditLimit)") }; Card { Metric(label: "Trained leagues", value: "\(e.trainedLeagues.count) / 5") } }
                Card {
                    VStack(spacing: 18) {
                        Button { strategySheet = true } label: { HStack { Label("Simulation rules", systemImage: "slider.horizontal.3"); Spacer(); Image(systemName: "chevron.right") } }
                        Divider()
                        Button { dataSheet = true } label: { HStack { Label("Data & credit budget", systemImage: "antenna.radiowaves.left.and.right"); Spacer(); Image(systemName: "chevron.right") } }
                    }.foregroundStyle(.primary).disabled(store.offline)
                }
                if !e.reasons.isEmpty {
                    Caption(text: "Why entries were skipped")
                    Card { VStack(alignment: .leading, spacing: 14) { ForEach(e.reasons) { r in HStack { Text(r.reason); Spacer(); Text("\(r.count)").foregroundStyle(Theme.violet) }.font(.footnote) } } }
                }
                Caption(text: "Recent engine jobs")
                ForEach(e.jobs.prefix(8)) { job in
                    Card { VStack(alignment: .leading, spacing: 10) { HStack { Text(job.kind.capitalized).font(.headline); Spacer(); StatusPill(text: job.status) }; Text(job.message ?? "Waiting for the next scheduled run").font(.footnote).foregroundStyle(.secondary) } }
                }
            }
            Button("Disconnect this phone", role: .destructive) { disconnect = true }.frame(maxWidth: .infinity).padding()
        }.navigationTitle("Engine").refreshable { await store.refresh() }
            .sheet(isPresented: $strategySheet) { if let strategy = store.dashboard?.engine.strategy { StrategyEditor(strategy: strategy) } }
            .sheet(isPresented: $dataSheet) { if let settings = store.dashboard?.engine.dataSettings { DataEditor(settings: settings) } }
            .confirmationDialog("Disconnect this phone? The server will continue running.", isPresented: $disconnect, titleVisibility: .visible) { Button("Disconnect", role: .destructive) { store.disconnect() } }
    }
}
struct StrategyEditor: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.dismiss) private var dismiss
    @State var strategy: Strategy
    @State private var saving = false
    @State private var error: String?
    var body: some View {
        NavigationStack {
            Form {
                Section("Automatic selection") {
                    Toggle("Enabled", isOn: $strategy.enabled)
                    number("Minimum edge (%)", value: $strategy.minEdge, scale: 100)
                    Stepper("Price age: \(strategy.maxQuoteAge) min", value: $strategy.maxQuoteAge, in: 1...15)
                    Stepper("Window opens: \(strategy.windowStart) min", value: $strategy.windowStart, in: 2...1440, step: 5)
                    Stepper("Window closes: \(strategy.windowEnd) min", value: $strategy.windowEnd, in: 1...1439, step: 5)
                }
                Section("Virtual stake sizing") {
                    Picker("Method", selection: $strategy.stakeMode) { Text("Fractional Kelly").tag("kelly"); Text("Fixed stake").tag("flat") }
                    if strategy.stakeMode == "kelly" { number("Kelly fraction (%)", value: $strategy.kellyFraction, scale: 100) }
                    number("Maximum bet (%)", value: $strategy.maxBetFraction, scale: 100)
                    number("Maximum exposure (%)", value: $strategy.maxExposure, scale: 100)
                    number("Minimum stake (£)", value: $strategy.minStake)
                    if strategy.stakeMode == "flat" { number("Fixed stake (£)", value: $strategy.stake) }
                }
                Section { Text("Changes apply to new simulated bets only. Recorded entries keep their original rules.").font(.footnote) }
                if let error { Section { Text(error).foregroundStyle(.orange) } }
            }.navigationTitle("Simulation rules").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }; ToolbarItem(placement: .confirmationAction) { Button(saving ? "Saving…" : "Save") { Task { saving = true; defer { saving = false }; do { try await store.save(strategy: strategy); dismiss() } catch { self.error = error.localizedDescription } } }.disabled(saving || store.offline) } }
        }.preferredColorScheme(.dark)
    }
    func number(_ label: String, value: Binding<Double>, scale: Double = 1) -> some View {
        HStack { Text(label); Spacer(); TextField(label, value: Binding(get: { value.wrappedValue * scale }, set: { value.wrappedValue = $0 / scale }), format: .number).keyboardType(.decimalPad).multilineTextAlignment(.trailing).frame(width: 80) }
    }
}
struct DataEditor: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.dismiss) private var dismiss
    @State var settings: DataSettings
    @State private var saving = false
    @State private var error: String?
    var body: some View {
        NavigationStack {
            Form {
                Section("Collection") {
                    Toggle("Automatic provider requests", isOn: $settings.autoRefresh)
                    Stepper("Odds interval: \(settings.intervalMinutes) min", value: $settings.intervalMinutes, in: 5...60, step: 5)
                    HStack { Text("Daily credit ceiling"); TextField("Credits", value: $settings.dailyCreditLimit, format: .number).keyboardType(.numberPad).multilineTextAlignment(.trailing) }
                    HStack { Text("Provider quota reserve"); TextField("Reserve", value: $settings.quotaReserve, format: .number).keyboardType(.numberPad).multilineTextAlignment(.trailing) }
                }
                Section { Text("Odds and results share the daily budget, which resets at midnight UTC. Results have priority. Provider keys are configured securely on the server.").font(.footnote) }
                if let error { Section { Text(error).foregroundStyle(.orange) } }
            }.navigationTitle("Data & budget").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }; ToolbarItem(placement: .confirmationAction) { Button(saving ? "Saving…" : "Save") { Task { saving = true; defer { saving = false }; do { try await store.save(data: settings); dismiss() } catch { self.error = error.localizedDescription } } }.disabled(saving || store.offline) } }
        }.preferredColorScheme(.dark)
    }
}
