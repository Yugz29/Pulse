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
    @Published var inputText = ""
    @Published var transientStatusText: String? = nil
    @Published var transientStatusAccent = Color(hex: "#5DCAA5")

    @Published var activeProject: String? = nil
    @Published var activeApp: String? = nil
    @Published var sessionDuration: Int = 0
    @Published var probableTask: String = "general"
    @Published var focusLevel: String = "normal"
    @Published var pendingCommand: CommandAnalysis? = nil
    @Published var availableModels: [String] = []
    @Published var selectedCommandModel: String = ""
    @Published var selectedSummaryModel: String = ""
    @Published var isUpdatingModel = false
    @Published var isObservingEnabled = true
    @Published var panelMode: PanelMode = .dashboard

    @Published var askResponse: String? = nil
    @Published var isAsking: Bool = false

    @Published var recentEvents: [InsightEvent] = []
    @Published var frictionScore: Double = 0.0
    @Published var activeFile: String? = nil
    @Published var recentApps: [String] = []

    let daemonController = DaemonController()
    var onObservationToggle: ((Bool) -> Void)?

    let bridge = DaemonBridge()
    var lastModelsRefreshAt: Date?
    var pollTask: Task<Void, Never>?
    var askTask: Task<Void, Never>?

    var currentPanelHeight: CGFloat {
        if pendingCommand != nil { return NotchWindow.commandHeight }
        switch panelMode {
        case .chat:
            return NotchWindow.chatHeight
        case .insight:
            return NotchWindow.insightHeight
        case .settings:
            return NotchWindow.settingsHeight
        case .status:
            return NotchWindow.statusHeight
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
        guard isDaemonActive, isOllamaOnline else { return false }
        if isLLMActive { return true }
        return !selectedCommandModel.isEmpty
            || !selectedSummaryModel.isEmpty
            || !availableModels.isEmpty
    }

    var llmStatusSubtitle: String {
        if !isDaemonActive { return "Daemon injoignable" }
        if !isOllamaOnline { return "Ollama introuvable" }
        if !selectedCommandModel.isEmpty { return selectedCommandModel }
        if !selectedSummaryModel.isEmpty { return selectedSummaryModel }
        if !availableModels.isEmpty { return "Modèle disponible" }
        return "Aucun modèle détecté"
    }
}
