import Foundation
import Combine

extension Notification.Name {
    static let contextProbeResultSubmitted = Notification.Name("PulseContextProbeResultSubmitted")
}

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
    @Published var debugWorkEpisodes: DebugWorkEpisodesResponse?
    @Published var debugCommitEpisodeLinks: DebugCommitEpisodeLinksResponse?
    @Published var events: [InsightEvent] = []
    @Published var proposals: [ProposalRecord] = []
    @Published var contextProbeRequests: [ContextProbeRequestPayload] = []
    @Published var contextProbeDebug: [ContextProbeDebugPayload] = []
    @Published var contextProbeResults: [String: ContextProbeResultPayload] = [:]
    @Published var accessibilityProbeDiagnostic: AccessibilityTextProbeDiagnostic?
    @Published var workContextCard: WorkContextCardPayload?
    @Published var workIntentCandidates: [WorkIntentCandidatePayload] = []
    @Published var feedHistory: [FeedEvent] = []
    @Published var observation: ObservationData? = nil
    @Published var daydreams: [DaydreamEntry] = []
    @Published var daydreamStatus: DaydreamStatus?
    @Published var ping: PingResponse?
    @Published var llmModels: LLMModelsResponse?
    @Published var lightweightLLMStatus: LightweightLLMStatusResponse?
    @Published var appleFoundationLocalStatus: AppleFoundationLocalStatus?
    @Published var scoringStatus: ScoringStatusResponse?
    @Published var isLoading = false
    @Published var lastRefreshedAt: Date?

    private let bridge: DaemonBridge
    private let appleFoundationStatusProvider: (() async -> AppleFoundationLocalStatus?)?
    private var pollTask: Task<Void, Never>?
    private var cancellables = Set<AnyCancellable>()
    private let refreshInterval: TimeInterval = 10
    private let slowRefreshEveryTicks = 6
    private var slowRefreshTick = 0

    init(
        bridge: DaemonBridge = DaemonBridge(),
        appleFoundationStatusProvider: (() async -> AppleFoundationLocalStatus?)? = nil
    ) {
        self.bridge = bridge
        self.appleFoundationStatusProvider = appleFoundationStatusProvider
        NotificationCenter.default.publisher(for: .contextProbeResultSubmitted)
            .compactMap { $0.object as? String }
            .sink { [weak self] requestId in
                Task { @MainActor [weak self] in
                    await self?.refreshContextProbeAfterSubmittedResult(requestId: requestId)
                }
            }
            .store(in: &cancellables)
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
            let debugDate = dashboardDebugDateString()
            async let factsTask = bridge.getFacts(limit: 30)
            async let archivedFactsTask = bridge.getArchivedFacts(limit: 30)
            async let factsStatsTask = bridge.getFactsStats()
            async let factsProfileTask = bridge.getFactsProfile()
            async let memoryTask = bridge.getMemory()
            async let sessionJournalsTask = bridge.getSessionJournals()
            async let debugWorkEpisodesTask = bridge.getDebugWorkEpisodes(date: debugDate)
            async let debugCommitEpisodeLinksTask = bridge.getDebugCommitEpisodeLinks(date: debugDate)
            async let eventsTask = bridge.getInsights(limit: 100)
            async let proposalsTask = bridge.getRecentProposals(limit: 20)
            async let contextProbesTask = bridge.getContextProbeRequests(includeTerminal: true)
            async let workContextTask = bridge.getWorkContextCard()
            async let workIntentCandidatesTask = bridge.getWorkIntentCandidates()
            async let daydreamTask = bridge.getDaydreamData()
            async let llmTask: LLMModelsResponse? = try? await bridge.getLLMModels()
            async let lightweightTask: LightweightLLMStatusResponse? = try? await bridge.getLightweightLLMStatus()
            async let appleLocalTask = appleFoundationStatusProvider?()
            async let scoringTask = bridge.getScoringStatus()

            facts = await factsTask
            archivedFacts = await archivedFactsTask
            factsStats = await factsStatsTask
            factsProfile = await factsProfileTask
            memory = await memoryTask
            sessionJournals = await sessionJournalsTask
            debugWorkEpisodes = await debugWorkEpisodesTask
            debugCommitEpisodeLinks = await debugCommitEpisodeLinksTask
            events = await eventsTask
            proposals = await proposalsTask
            if let contextProbes = await contextProbesTask {
                contextProbeRequests = contextProbes.requests
                contextProbeDebug = contextProbes.debug
            }
            if let workContext = await workContextTask {
                workContextCard = workContext.card
            }
            if let workIntentCandidatesPayload = await workIntentCandidatesTask {
                workIntentCandidates = workIntentCandidatesPayload.candidates
            }
            let daydreamData = await daydreamTask
            daydreams = daydreamData.0
            daydreamStatus = daydreamData.1
            llmModels = await llmTask
            lightweightLLMStatus = await lightweightTask
            appleFoundationLocalStatus = await appleLocalTask
            scoringStatus = await scoringTask
        }

        lastRefreshedAt = Date()
        isLoading = false
    }

    func refreshContextProbeRequests(
        includeTerminal: Bool = true,
        refreshExecutedDetails: Bool = true
    ) async {
        guard let payload = await bridge.getContextProbeRequests(includeTerminal: includeTerminal) else { return }
        contextProbeRequests = payload.requests
        contextProbeDebug = payload.debug
        if refreshExecutedDetails {
            await refreshExecutedContextProbeResults(for: payload.requests)
        }
        lastRefreshedAt = Date()
    }

    func refreshWorkIntentCandidates() async {
        guard let payload = await bridge.getWorkIntentCandidates() else { return }
        workIntentCandidates = payload.candidates
        lastRefreshedAt = Date()
    }

    func acceptWorkIntentCandidate(_ candidate: WorkIntentCandidatePayload) async {
        guard candidate.canAcceptOrRefuse else { return }
        guard await bridge.acceptWorkIntentCandidate(candidate.candidateId) != nil else { return }
        await refreshWorkIntentCandidates()
        if let workContext = await bridge.getWorkContextCard() {
            workContextCard = workContext.card
        }
        state = try? await bridge.getState()
        lastRefreshedAt = Date()
    }

    func refuseWorkIntentCandidate(_ candidate: WorkIntentCandidatePayload) async {
        guard candidate.canAcceptOrRefuse else { return }
        guard await bridge.refuseWorkIntentCandidate(candidate.candidateId) != nil else { return }
        await refreshWorkIntentCandidates()
    }

    @discardableResult
    func refreshContextProbeDetail(requestId: String) async -> Bool {
        guard let detail = await bridge.getContextProbeRequestDetail(requestId) else { return false }
        upsertContextProbeRequest(detail.request)
        upsertContextProbeDebug(detail.debug)
        if let result = detail.result {
            contextProbeResults[requestId] = result
        } else {
            contextProbeResults.removeValue(forKey: requestId)
        }
        lastRefreshedAt = Date()
        return true
    }

    private func refreshExecutedContextProbeResults(for requests: [ContextProbeRequestPayload]) async {
        let executed = requests.filter { $0.status == "executed" }
        let visibleIds = Set(executed.map(\.requestId))
        contextProbeResults = contextProbeResults.filter { visibleIds.contains($0.key) }

        for request in executed {
            guard let detail = await bridge.getContextProbeRequestDetail(request.requestId) else { continue }
            if let result = detail.result {
                contextProbeResults[request.requestId] = result
            } else {
                contextProbeResults.removeValue(forKey: request.requestId)
            }
        }
    }

    private func refreshContextProbeAfterSubmittedResult(requestId: String) async {
        await refreshContextProbeRequests(includeTerminal: true, refreshExecutedDetails: false)
        _ = await refreshContextProbeDetail(requestId: requestId)
    }

    private func upsertContextProbeRequest(_ request: ContextProbeRequestPayload) {
        if let index = contextProbeRequests.firstIndex(where: { $0.requestId == request.requestId }) {
            contextProbeRequests[index] = request
        } else {
            contextProbeRequests.append(request)
        }
    }

    private func upsertContextProbeDebug(_ debug: ContextProbeDebugPayload) {
        if let index = contextProbeDebug.firstIndex(where: { $0.requestId == debug.requestId }) {
            contextProbeDebug[index] = debug
        } else {
            contextProbeDebug.append(debug)
        }
    }

    func createFocusedElementTextProbeRequest() async {
        guard await bridge.createFocusedElementTextProbeRequest() != nil else { return }
        await refreshContextProbeRequests()
    }

    func approveContextProbeRequest(_ request: ContextProbeRequestPayload) async {
        guard request.canApproveOrRefuse else { return }
        guard await bridge.approveContextProbeRequest(request.requestId, reason: "Approved from Pulse Dashboard") != nil else { return }
        await refreshContextProbeRequests()
    }

    func refuseContextProbeRequest(_ request: ContextProbeRequestPayload) async {
        guard request.canApproveOrRefuse else { return }
        guard await bridge.refuseContextProbeRequest(request.requestId, reason: "Refused from Pulse Dashboard") != nil else { return }
        await refreshContextProbeRequests()
    }

    func executeContextProbeRequest(_ request: ContextProbeRequestPayload) async {
        guard request.canExecute else { return }
        guard let response = await bridge.executeContextProbeRequest(request.requestId) else { return }
        contextProbeResults[request.requestId] = response.result
        await refreshContextProbeRequests()
    }

    func captureFocusedElementText(_ request: ContextProbeRequestPayload) async {
        guard request.canCaptureFromAccessibility else { return }
        let capture: AccessibilityTextProbeCapture
        do {
            capture = try AccessibilityContextProbeService().captureFocusedText()
        } catch {
            return
        }
        guard let response = await bridge.submitContextProbeResult(request.requestId, capture: capture) else { return }
        contextProbeResults[request.requestId] = response.result
        await refreshContextProbeRequests()
    }

    func diagnoseActiveAccessibilityElement() {
        do {
            setAccessibilityProbeDiagnostic(try AccessibilityContextProbeService().diagnoseFocusedElement())
        } catch {
            setAccessibilityProbeDiagnostic(AccessibilityTextProbeDiagnostic(
                appName: "unknown",
                bundleId: "unknown",
                pid: 0,
                axTrusted: false,
                focusedElementStatus: "error",
                focusedRole: nil,
                focusedSubrole: nil,
                focusedRoleDescription: nil,
                canReadSelectedText: false,
                selectedTextLength: nil,
                canReadValue: false,
                valueLength: nil,
                focusedWindowStatus: "error",
                focusedWindowRole: nil,
                focusedWindowTitleAvailable: false,
                rejectionReason: "diagnostic_failed:\(error)",
                isSecureField: false,
                isWebArea: false,
                treeSummary: nil
            ))
        }
    }

    func setAccessibilityProbeDiagnostic(_ diagnostic: AccessibilityTextProbeDiagnostic?) {
        accessibilityProbeDiagnostic = diagnostic
    }

    func debugForContextProbeRequest(_ request: ContextProbeRequestPayload) -> ContextProbeDebugPayload? {
        contextProbeDebug.first { $0.requestId == request.requestId }
    }

    func resultForContextProbeRequest(_ request: ContextProbeRequestPayload) -> ContextProbeResultPayload? {
        contextProbeResults[request.requestId]
    }

    private func dashboardDebugDateString() -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = .current
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: Date())
    }
}
