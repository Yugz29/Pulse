import SwiftUI
import Combine

@MainActor
final class PulseViewModel: ObservableObject {
    @Published var isExpanded = false
    @Published var isStartupExpanded = false
    @Published var isStartupVisible = false
    @Published var isHovering = false
    @Published var isFullscreen = false
    @Published var isDaemonActive = false
    @Published var isLLMActive = false
    @Published var isOllamaOnline = false
    @Published var isModelSelected = false
    @Published var llmReadyState = false
    @Published var inputText = ""
    @Published var transientStatusText: String? = nil
    @Published var transientStatusAccent = Color(hex: "#5DCAA5")

    @Published var activeProject: String? = nil
    @Published var activeApp: String? = nil
    @Published var sessionDuration: Int = 0
    @Published var probableTask: String = "general"
    @Published var focusLevel: String = "normal"
    @Published var pendingCommand: CommandAnalysis? = nil
    @Published var pendingContextProbe: ContextProbeRequestPayload? = nil
    @Published var availableModels: [String] = []
    @Published var selectedModel: String = ""
    @Published var selectedCommandModel: String = ""
    @Published var selectedSummaryModel: String = ""
    @Published var isUpdatingModel = false
    @Published var isObservingEnabled = true
    @Published var panelMode: PanelMode = .dashboard

    @Published var chatMessages: [ChatMessage] = []
    @Published var isAsking: Bool = false
    @Published var activeRequestStatusText: String? = nil
    @Published var activeRequestSystemMessage: String? = nil

    @Published var recentEvents: [InsightEvent] = []
    @Published var recentProposals: [ProposalRecord] = []
    @Published var feedHistory: [FeedEvent] = []
    @Published var activeResumeCard: ResumeCard? = nil
    @Published var currentPresent: PresentData? = nil
    @Published var currentContext: SessionContextData? = nil
    @Published var currentSignals: SignalsData? = nil
    @Published var frictionScore: Double = 0.0
    @Published var activeFile: String? = nil
    @Published var recentApps: [String] = []

    let daemonController = DaemonController()
    var onObservationToggle: ((Bool) -> Void)?
    var onDaemonReconnected: (() -> Void)?
    var onToggleDashboard: (() -> Void)?

    let bridge: DaemonBridge
    var lastModelsRefreshAt: Date?
    var lastFeedTimestamp: String? = ISO8601DateFormatter().string(from: Date())
    var startupGracePeriodEnd: Date? = nil
    var pollTask: Task<Void, Never>?
    var askTask: Task<Void, Never>?
    var shouldShowCancellationFeedback = true

    init(bridge: DaemonBridge = DaemonBridge()) {
        self.bridge = bridge
    }

    var currentPanelHeight: CGFloat {
        if pendingCommand != nil { return NotchWindow.commandHeight }
        if pendingContextProbe != nil { return NotchWindow.contextProbeHeight }
        if panelMode == .resumeCard, let card = activeResumeCard {
            return card.displayHeight
        }
        switch panelMode {
        case .chat:
            return NotchWindow.chatHeight
        case .currentState:
            return NotchWindow.currentStateHeight
        case .insight:
            return NotchWindow.insightHeight
        case .feed:
            return NotchWindow.feedHeight
        case .settings:
            return NotchWindow.settingsHeight
        case .status:
            return NotchWindow.statusHeight
        case .resumeCard:
            return NotchWindow.resumeStandardHeight
        default:
            return NotchWindow.dashboardHeight
        }
    }

    var serviceStatus: PulseServiceStatus {
        if !isDaemonActive { return .daemonOffline }
        if daemonController.state == .paused { return .daemonPaused }
        if !isObservingEnabled { return .observationPaused }
        if !isLLMReady { return .llmUnavailable }
        return .healthy
    }

    var overallHealthColor: Color {
        serviceStatus.color
    }

    var isLLMReady: Bool {
        guard isDaemonActive else { return false }
        return llmReadyState
    }

    var llmStatusSubtitle: String {
        if !isDaemonActive { return "Daemon injoignable" }
        if !isOllamaOnline { return "Ollama introuvable" }
        if !selectedModel.isEmpty { return selectedModel }
        if !isModelSelected && !availableModels.isEmpty { return "Aucun modèle sélectionné" }
        return "Aucun modèle détecté"
    }

    func refreshPendingContextProbe() async {
        guard let payload = await bridge.getContextProbeRequests(status: "pending", includeTerminal: false) else {
            pendingContextProbe = nil
            return
        }
        pendingContextProbe = payload.requests.first
    }

    func approvePendingContextProbe() async {
        guard let request = pendingContextProbe else { return }
        guard await bridge.approveContextProbeRequest(request.requestId, reason: "Approved from Pulse Notch") != nil else { return }
        withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) {
            pendingContextProbe = nil
            isExpanded = false
        }
    }

    func refusePendingContextProbe() async {
        guard let request = pendingContextProbe else { return }
        guard await bridge.refuseContextProbeRequest(request.requestId, reason: "Refused from Pulse Notch") != nil else { return }
        withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) {
            pendingContextProbe = nil
            isExpanded = false
        }
    }
}
