import SwiftUI
import Combine
import AppKit

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
    @Published var contextInputMode: ContextInputMode = .choosing
    @Published var contextManualNoteText: String = ""
    @Published var contextInputStatusText: String? = nil
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
    private let oneShotClipboardService = OneShotClipboardContextService()
    private var oneShotClipboardTimer: Timer?
    private var activeContextResultRequestId: String?

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

    var currentPanelWidth: CGFloat {
        if panelMode == .resumeCard, activeResumeCard?.displaySize == "expanded" {
            return NotchWindow.resumeExpandedWidth
        }
        return NotchWindow.panelWidth
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
        if activeContextResultRequestId != nil {
            return
        }
        guard let payload = await bridge.getContextProbeRequests(status: "pending", includeTerminal: false) else {
            pendingContextProbe = nil
            resetContextInputState()
            return
        }
        let next = payload.requests.first
        if next?.requestId != pendingContextProbe?.requestId {
            resetContextInputState()
        }
        pendingContextProbe = next
    }

    func approvePendingContextProbe() async {
        guard let request = pendingContextProbe else { return }
        guard await bridge.approveContextProbeRequest(request.requestId, reason: "Approved from Pulse Notch") != nil else { return }
        withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) {
            pendingContextProbe = nil
            isExpanded = false
            resetContextInputState()
        }
    }

    func refusePendingContextProbe() async {
        guard let request = pendingContextProbe else { return }
        guard await bridge.refuseContextProbeRequest(request.requestId, reason: "Refused from Pulse Notch") != nil else { return }
        withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) {
            pendingContextProbe = nil
            isExpanded = false
            resetContextInputState()
        }
    }

    func chooseNextClipboardContext() async {
        guard let request = await prepareContentProbeRequest(
            kind: "clipboard_sample",
            reason: "Use the next copied text as explicit context",
            sourceMetadata: "notch_next_clipboard"
        ) else { return }
        activeContextResultRequestId = request.requestId
        contextInputMode = .clipboardArmed
        contextInputStatusText = "En attente du prochain texte copié..."
        oneShotClipboardService.arm(baselineChangeCount: NSPasteboard.general.changeCount)
        startOneShotClipboardPolling()
    }

    func showManualContextNoteInput() {
        contextInputMode = .manualNote
        contextInputStatusText = nil
    }

    func submitManualContextNote() async {
        let note = contextManualNoteText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !note.isEmpty else {
            contextInputStatusText = "Note vide."
            return
        }
        guard let request = await prepareContentProbeRequest(
            kind: "manual_context_note",
            reason: "Use a quick manual note as explicit context",
            sourceMetadata: "notch_manual_note"
        ) else { return }
        let capture = ContextTextProbeCapture.manualContextNote(note)
        await submitContextTextProbeResult(requestId: request.requestId, capture: capture)
    }

    func ignorePendingContextInput() async {
        if activeContextResultRequestId != nil || contextInputMode == .clipboardArmed {
            if let requestId = activeContextResultRequestId {
                _ = await bridge.abortContextProbeRequest(
                    requestId,
                    reason: "Cancelled from Pulse Notch"
                )
            }
            withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) {
                pendingContextProbe = nil
                isExpanded = false
                resetContextInputState()
            }
            return
        }
        await refusePendingContextProbe()
    }

    private func prepareContentProbeRequest(
        kind: String,
        reason: String,
        sourceMetadata: String
    ) async -> ContextProbeRequestPayload? {
        guard let visibleRequest = pendingContextProbe else { return nil }
        if visibleRequest.kind == kind {
            guard let approved = await bridge.approveContextProbeRequest(
                visibleRequest.requestId,
                reason: "Approved from Pulse Notch"
            ) else {
                contextInputMode = .failed("Impossible d'approuver la demande.")
                return nil
            }
            return approved.request
        }

        var metadata = ["source": sourceMetadata]
        if let project = activeProject?.trimmingCharacters(in: .whitespacesAndNewlines),
           !project.isEmpty {
            metadata["project"] = project
        }

        guard let created = await bridge.createContextProbeRequest(
            kind: kind,
            reason: reason,
            ttlSec: kind == "clipboard_sample" ? 3_600 : 60,
            metadata: metadata
        ) else {
            contextInputMode = .failed("Impossible de créer la demande.")
            return nil
        }
        guard let approved = await bridge.approveContextProbeRequest(
            created.request.requestId,
            reason: "Approved from Pulse Notch"
        ) else {
            contextInputMode = .failed("Impossible d'approuver la demande.")
            return nil
        }
        _ = await bridge.refuseContextProbeRequest(
            visibleRequest.requestId,
            reason: "Replaced by explicit \(kind) source from Pulse Notch"
        )
        pendingContextProbe = approved.request
        return approved.request
    }

    private func startOneShotClipboardPolling() {
        oneShotClipboardTimer?.invalidate()
        let timer = Timer(timeInterval: 0.5, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.pollOneShotClipboard()
            }
        }
        oneShotClipboardTimer = timer
        RunLoop.main.add(timer, forMode: .common)
    }

    private func pollOneShotClipboard() {
        guard let requestId = activeContextResultRequestId else { return }
        let pasteboard = NSPasteboard.general
        guard let oneShot = oneShotClipboardService.captureIfChanged(
            changeCount: pasteboard.changeCount,
            text: pasteboard.string(forType: .string)
        ) else {
            if !oneShotClipboardService.isArmed {
                stopOneShotClipboardPolling()
                withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) {
                    pendingContextProbe = nil
                    isExpanded = false
                    resetContextInputState()
                }
            }
            return
        }
        stopOneShotClipboardPolling()
        contextInputStatusText = "Texte copié reçu (\(oneShot.capture.charCount) caractères)."
        Task { @MainActor in
            await submitContextTextProbeResult(requestId: requestId, capture: oneShot.capture)
        }
    }

    func submitContextTextProbeResult(
        requestId: String,
        capture: ContextTextProbeCapture
    ) async {
        guard await bridge.submitContextProbeResult(requestId, capture: capture) != nil else {
            contextInputMode = .failed("Envoi impossible.")
            return
        }
        NotificationCenter.default.post(name: .contextProbeResultSubmitted, object: requestId)
        contextInputMode = .submitted
        contextInputStatusText = capture.truncated
            ? "Contexte envoyé avec troncature locale."
            : "Contexte envoyé."
        contextManualNoteText = ""
        activeContextResultRequestId = nil
        pendingContextProbe = nil
        oneShotClipboardService.disarm()
        stopOneShotClipboardPolling()
        withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) {
            isExpanded = false
        }
    }

    private func stopOneShotClipboardPolling() {
        oneShotClipboardTimer?.invalidate()
        oneShotClipboardTimer = nil
    }

    private func resetContextInputState() {
        contextInputMode = .choosing
        contextManualNoteText = ""
        contextInputStatusText = nil
        activeContextResultRequestId = nil
        oneShotClipboardService.disarm()
        stopOneShotClipboardPolling()
    }
}
