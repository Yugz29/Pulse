import Foundation
import Combine

@MainActor
final class DashboardViewModel: ObservableObject {
    @Published var state: StateResponse?
    @Published var facts: FactsResponse?
    @Published var archivedFacts: FactsResponse?
    @Published var factsStats: FactsStatsResponse?
    @Published var factsProfile: FactsProfileResponse?
    @Published var memory: MemoryResponse?
    @Published var sessionJournals: SessionsResponse?
    @Published var todaySummary: TodaySummaryResponse?
    @Published var events: [InsightEvent] = []
    @Published var proposals: [ProposalRecord] = []
    @Published var feedHistory: [FeedEvent] = []
    @Published var observation: ObservationData? = nil
    @Published var daydreams: [DaydreamEntry] = []
    @Published var daydreamStatus: DaydreamStatus?
    @Published var ping: PingResponse?
    @Published var llmModels: LLMModelsResponse?
    @Published var scoringStatus: ScoringStatusResponse?
    @Published var isLoading = false
    @Published var lastRefreshedAt: Date?

    private let bridge: DaemonBridge
    private var pollTask: Task<Void, Never>?
    private let refreshInterval: TimeInterval = 10
    private let slowRefreshEveryTicks = 6
    private var slowRefreshTick = 0

    init(bridge: DaemonBridge = DaemonBridge()) {
        self.bridge = bridge
    }

    var daemonBaseURL: String {
        bridge.base
    }

    var daemonPort: Int? {
        URL(string: bridge.base)?.port
    }

    deinit {
        pollTask?.cancel()
    }

    func startPolling() {
        guard pollTask == nil else { return }
        pollTask = Task { [weak self] in
            guard let self else { return }
            await self.refresh()
            while !Task.isCancelled {
                do {
                    try await Task.sleep(for: .seconds(refreshInterval))
                } catch {
                    break
                }
                guard !Task.isCancelled else { break }
                await self.refresh(includeSlowData: false)
            }
        }
    }

    func stopPolling() {
        pollTask?.cancel()
        pollTask = nil
    }

    func refresh(includeSlowData: Bool = true) async {
        isLoading = true

        if !includeSlowData {
            slowRefreshTick += 1
        }
        let shouldRefreshSlowData = includeSlowData || slowRefreshTick >= slowRefreshEveryTicks
        if shouldRefreshSlowData {
            slowRefreshTick = 0
        }

        async let stateTask: StateResponse? = try? await bridge.getState()
        async let todaySummaryTask = bridge.getTodaySummary()
        async let feedTask = bridge.fetchFeed(since: nil)
        async let observationTask = bridge.getObservation()
        async let pingTask: PingResponse? = try? await bridge.pingStatus()

        state = await stateTask
        todaySummary = await todaySummaryTask
        feedHistory = await feedTask
        observation = await observationTask
        ping = await pingTask

        if shouldRefreshSlowData {
            async let factsTask = bridge.getFacts(limit: 30)
            async let archivedFactsTask = bridge.getArchivedFacts(limit: 30)
            async let factsStatsTask = bridge.getFactsStats()
            async let factsProfileTask = bridge.getFactsProfile()
            async let memoryTask = bridge.getMemory()
            async let sessionJournalsTask = bridge.getSessionJournals()
            async let eventsTask = bridge.getInsights(limit: 100)
            async let proposalsTask = bridge.getRecentProposals(limit: 20)
            async let daydreamTask = bridge.getDaydreamData()
            async let llmTask: LLMModelsResponse? = try? await bridge.getLLMModels()
            async let scoringTask = bridge.getScoringStatus()

            facts = await factsTask
            archivedFacts = await archivedFactsTask
            factsStats = await factsStatsTask
            factsProfile = await factsProfileTask
            memory = await memoryTask
            sessionJournals = await sessionJournalsTask
            events = await eventsTask
            proposals = await proposalsTask
            let daydreamData = await daydreamTask
            daydreams = daydreamData.0
            daydreamStatus = daydreamData.1
            llmModels = await llmTask
            scoringStatus = await scoringTask
        }

        lastRefreshedAt = Date()
        isLoading = false
    }
}
