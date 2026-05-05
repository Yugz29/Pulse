import Foundation

struct PingResponse: Codable {
    let status: String
    let version: String
    let paused: Bool?
}

struct StateResponse: Decodable {
    let activeApp: String?
    let activeFile: String?
    let activeProject: String?
    let sessionDurationMin: Int
    let lastEventType: String?
    let runtimePaused: Bool?
    let present: PresentData?
    let signals: SignalsData?
    let sessionFsm: SessionFSMData?
    let currentContext: SessionContextData?
    let recentSessions: [SessionContextData]?

    enum CodingKeys: String, CodingKey {
        case activeApp = "active_app"
        case activeFile = "active_file"
        case activeProject = "active_project"
        case sessionDurationMin = "session_duration_min"
        case lastEventType = "last_event_type"
        case runtimePaused = "runtime_paused"
        case present
        case signals
        case sessionFsm = "session_fsm"
        case currentContext = "current_context"
        case recentSessions = "recent_sessions"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        activeApp = try container.decodeIfPresent(String.self, forKey: .activeApp)
        activeFile = try container.decodeIfPresent(String.self, forKey: .activeFile)
        activeProject = try container.decodeIfPresent(String.self, forKey: .activeProject)
        sessionDurationMin = try container.decodeIfPresent(Int.self, forKey: .sessionDurationMin) ?? 0
        lastEventType = try container.decodeIfPresent(String.self, forKey: .lastEventType)
        runtimePaused = try container.decodeIfPresent(Bool.self, forKey: .runtimePaused)
        present = try container.decodeIfPresent(PresentData.self, forKey: .present)
        signals = try container.decodeIfPresent(SignalsData.self, forKey: .signals)
        sessionFsm = try container.decodeIfPresent(SessionFSMData.self, forKey: .sessionFsm)
        currentContext = try container.decodeIfPresent(SessionContextData.self, forKey: .currentContext)
        recentSessions = try container.decodeIfPresent([SessionContextData].self, forKey: .recentSessions)
    }
}

struct PresentData: Decodable {
    let sessionStatus: String
    let awake: Bool
    let locked: Bool
    let activeFile: String?
    let activeProject: String?
    let probableTask: String
    let activityLevel: String
    let focusLevel: String
    let frictionScore: Double
    let clipboardContext: String?
    let sessionDurationMin: Int
    let updatedAt: String?

    enum CodingKeys: String, CodingKey {
        case sessionStatus = "session_status"
        case awake
        case locked
        case activeFile = "active_file"
        case activeProject = "active_project"
        case probableTask = "probable_task"
        case activityLevel = "activity_level"
        case focusLevel = "focus_level"
        case frictionScore = "friction_score"
        case clipboardContext = "clipboard_context"
        case sessionDurationMin = "session_duration_min"
        case updatedAt = "updated_at"
    }

    var taskLabel: String {
        switch probableTask {
        case "coding": return "Développement"
        case "writing": return "Rédaction"
        case "debug": return "Débogage"
        case "exploration", "browsing": return "Exploration"
        case "general": return "Général"
        default: return probableTask
        }
    }

    var activityLabel: String {
        switch activityLevel {
        case "editing": return "Édition"
        case "reading": return "Lecture"
        case "executing": return "Exécution"
        case "navigating": return "Navigation"
        case "idle": return "Inactif"
        default: return activityLevel
        }
    }

    var taskAccentHex: String {
        switch probableTask {
        case "coding": return "#5DCAA5"
        case "writing": return "#5E9EFF"
        case "debug": return "#ff453a"
        case "exploration", "browsing": return "#EF9F27"
        default: return "#7c7c80"
        }
    }
}

struct SessionContextData: Decodable, Identifiable {
    private let rawId: String?
    let sessionId: String?
    let startedAt: String?
    let endedAt: String?
    let boundaryReason: String?
    let durationSec: Int?
    let activeProject: String?
    let activeFile: String?
    let probableTask: String?
    let activityLevel: String?
    let focusLevel: String?
    let taskConfidence: Double?
    let userPresenceState: String?
    let userIdleSeconds: Int?
    let terminalActionCategory: String?
    let terminalProject: String?
    let terminalCwd: String?
    let terminalCommand: String?
    let terminalSuccess: Bool?
    let terminalExitCode: Int?
    let terminalDurationMs: Int?
    let terminalSummary: String?
    let activeAppDurationSec: Int?
    let activeWindowTitleDurationSec: Int?
    let appSwitchCount10m: Int?
    let aiAppSwitchCount10m: Int?

    var id: String {
        if let rawId, !rawId.isEmpty { return rawId }
        if let sessionId, !sessionId.isEmpty { return sessionId }
        let fallback = [activeProject, activeFile, probableTask, activityLevel]
            .compactMap { $0 }
            .filter { !$0.isEmpty }
            .joined(separator: "|")
        return fallback.isEmpty ? "current-context" : fallback
    }

    enum CodingKeys: String, CodingKey {
        case rawId = "id"
        case sessionId = "session_id"
        case startedAt = "started_at"
        case endedAt = "ended_at"
        case boundaryReason = "boundary_reason"
        case durationSec = "duration_sec"
        case activeProject = "active_project"
        case activeFile = "active_file"
        case probableTask = "probable_task"
        case activityLevel = "activity_level"
        case focusLevel = "focus_level"
        case taskConfidence = "task_confidence"
        case userPresenceState = "user_presence_state"
        case userIdleSeconds = "user_idle_seconds"
        case terminalActionCategory = "terminal_action_category"
        case terminalProject = "terminal_project"
        case terminalCwd = "terminal_cwd"
        case terminalCommand = "terminal_command"
        case terminalSuccess = "terminal_success"
        case terminalExitCode = "terminal_exit_code"
        case terminalDurationMs = "terminal_duration_ms"
        case terminalSummary = "terminal_summary"
        case activeAppDurationSec = "active_app_duration_sec"
        case activeWindowTitleDurationSec = "active_window_title_duration_sec"
        case appSwitchCount10m = "app_switch_count_10m"
        case aiAppSwitchCount10m = "ai_app_switch_count_10m"
    }

    var isActive: Bool {
        endedAt == nil
    }

    var boundaryLabel: String {
        switch boundaryReason {
        case "screen_lock": return "screen_lock"
        case "idle_timeout": return "idle_timeout · fin estimée"
        case "commit": return "Commit"
        case "session_end": return "Fin de session"
        case nil: return "En cours"
        default: return boundaryReason ?? "—"
        }
    }

    var boundaryColor: String {
        switch boundaryReason {
        case "screen_lock": return "#5E9EFF"
        case "idle_timeout": return "#EF9F27"
        case "commit": return "#5DCAA5"
        case "session_end": return "#7c7c80"
        case nil: return "#5DCAA5"
        default: return "#7c7c80"
        }
    }

    var taskLabel: String {
        switch probableTask {
        case "coding": return "Développement"
        case "writing": return "Rédaction"
        case "debug": return "Débogage"
        case "exploration", "browsing": return "Exploration"
        case "general": return "Général"
        case nil: return "—"
        default: return probableTask ?? "—"
        }
    }

    var activityLabel: String {
        switch activityLevel {
        case "editing": return "Édition"
        case "reading": return "Lecture"
        case "executing": return "Exécution"
        case "navigating": return "Navigation"
        case "idle": return "Inactif"
        case nil: return "—"
        default: return activityLevel ?? "—"
        }
    }

    var taskAccentHex: String {
        switch probableTask {
        case "coding": return "#5DCAA5"
        case "writing": return "#5E9EFF"
        case "debug": return "#ff453a"
        case "exploration", "browsing": return "#EF9F27"
        default: return "#7c7c80"
        }
    }
}

struct SignalsData: Codable {
    let activeProject: String?
    let activeFile: String?
    let probableTask: String?
    let activityLevel: String?
    let taskConfidence: Double?
    let focusLevel: String?
    let frictionScore: Double?
    let sessionDurationMin: Int?
    let recentApps: [String]?
    let clipboardContext: String?
    let editedFileCount10m: Int?
    let fileTypeMix10m: [String: Int]?
    let renameDeleteRatio10m: Double?
    let dominantFileMode: String?
    let workPatternCandidate: String?
    let lastSessionContext: String?

    enum CodingKeys: String, CodingKey {
        case activeProject = "active_project"
        case activeFile = "active_file"
        case probableTask = "probable_task"
        case activityLevel = "activity_level"
        case taskConfidence = "task_confidence"
        case focusLevel = "focus_level"
        case frictionScore = "friction_score"
        case sessionDurationMin = "session_duration_min"
        case recentApps = "recent_apps"
        case clipboardContext = "clipboard_context"
        case editedFileCount10m = "edited_file_count_10m"
        case fileTypeMix10m = "file_type_mix_10m"
        case renameDeleteRatio10m = "rename_delete_ratio_10m"
        case dominantFileMode = "dominant_file_mode"
        case workPatternCandidate = "work_pattern_candidate"
        case lastSessionContext = "last_session_context"
    }

    var taskLabel: String {
        switch probableTask {
        case "coding": return "Développement"
        case "writing": return "Rédaction"
        case "debug": return "Débogage"
        case "exploration", "browsing": return "Exploration"
        default: return "Général"
        }
    }

    var activityLabel: String {
        switch activityLevel {
        case "editing": return "Édition"
        case "reading": return "Lecture"
        case "executing": return "Exécution"
        case "navigating": return "Navigation"
        case "idle": return "Inactif"
        default: return "—"
        }
    }

    var taskAccentHex: String {
        switch probableTask {
        case "coding": return "#5DCAA5"
        case "writing": return "#5E9EFF"
        case "debug": return "#ff453a"
        case "exploration", "browsing": return "#EF9F27"
        default: return "#7c7c80"
        }
    }

    private var codeActivityCount: Int {
        (fileTypeMix10m?["source"] ?? 0) + (fileTypeMix10m?["test"] ?? 0)
    }

    private var configActivityCount: Int {
        fileTypeMix10m?["config"] ?? 0
    }

    private var docsActivityCount: Int {
        fileTypeMix10m?["docs"] ?? 0
    }

    var taskEvidenceLabel: String {
        if isFileDrivenTask {
            return "Ancré"
        }
        if probableTask == "general" || (taskConfidence ?? 0) < 0.45 {
            return "Faible"
        }
        return "Ambigu"
    }

    var taskEvidenceSummary: String {
        if isFileDrivenTask {
            var parts: [String] = []
            if let fileActivitySummary, !fileActivitySummary.isEmpty {
                parts.append(fileActivitySummary)
            }
            if let reading = sessionReadingSummary, !reading.isEmpty {
                parts.append(reading)
            }
            return parts.joined(separator: " ")
        }

        if let latestApp = recentApps?.last, !latestApp.isEmpty {
            return "Le libellé vient surtout de l’app récente (\(latestApp)) car l’activité fichiers reste faible."
        }
        return "Peu d’indices récents: Pulse garde une lecture prudente de la session."
    }

    var fileActivitySummary: String? {
        guard let editedFileCount10m, editedFileCount10m > 0 else { return nil }
        var parts = ["\(editedFileCount10m) fichier(s) touché(s) sur 10 min"]
        if editedFileCount10m < 2 {
            return parts.joined(separator: ", ")
        }
        let mixSummary = formattedFileMix
        if !mixSummary.isEmpty {
            parts.append("surtout \(mixSummary)")
        }
        return parts.joined(separator: ", ")
    }

    var sessionReadingSummary: String? {
        var parts: [String] = []
        if let mode = dominantFileModeLabel {
            parts.append(mode)
        }
        if let pattern = workPatternLabel {
            parts.append(pattern)
        }
        if let structural = structuralChangeLabel {
            parts.append(structural)
        }
        guard !parts.isEmpty else { return nil }
        return parts.joined(separator: ", ")
    }

    private var isFileDrivenTask: Bool {
        if codeActivityCount >= 2 { return true }
        if configActivityCount >= 2 { return true }
        if docsActivityCount >= 2 { return true }
        if let pattern = workPatternCandidate, !pattern.isEmpty { return true }
        return false
    }

    private var formattedFileMix: String {
        guard let fileTypeMix10m else { return "" }
        let labels: [String: String] = [
            "source": "code source",
            "test": "tests",
            "config": "configuration",
            "docs": "documentation",
            "assets": "assets",
        ]
        let preferredOrder = ["source", "test", "config", "docs", "assets"]
        let entries = preferredOrder.compactMap { key -> String? in
            guard let value = fileTypeMix10m[key], value > 0 else { return nil }
            return "\(labels[key] ?? key) (\(value))"
        }
        return entries.prefix(3).joined(separator: ", ")
    }

    private var dominantFileModeLabel: String? {
        switch dominantFileMode {
        case "single_file":
            return "travail concentré sur un seul fichier"
        case "few_files":
            return "petit lot cohérent de fichiers"
        case "multi_file":
            return "travail réparti sur plusieurs fichiers"
        default:
            return nil
        }
    }

    private var workPatternLabel: String? {
        switch workPatternCandidate {
        case "feature_candidate":
            return "ça ressemble à une évolution de fonctionnalité"
        case "refactor_candidate":
            return "ça ressemble à un refactor"
        case "debug_loop_candidate":
            return "ça ressemble à une boucle de débogage"
        case "setup_candidate":
            return "ça ressemble à une phase de configuration"
        default:
            return nil
        }
    }

    private var structuralChangeLabel: String? {
        guard let renameDeleteRatio10m, renameDeleteRatio10m >= 0.25 else { return nil }
        return "avec quelques changements de structure"
    }
}

struct SessionFSMData: Decodable {
    let state: String?
    let sessionStartedAt: String?
    let lastMeaningfulActivityAt: String?
    let lastScreenLockedAt: String?

    enum CodingKeys: String, CodingKey {
        case state
        case sessionStartedAt = "session_started_at"
        case lastMeaningfulActivityAt = "last_meaningful_activity_at"
        case lastScreenLockedAt = "last_screen_locked_at"
    }

    var stateLabel: String {
        switch state {
        case "active": return "Active"
        case "idle": return "Idle"
        case "locked": return "Verrouillée"
        default: return state ?? "—"
        }
    }

    var stateColor: String {
        switch state {
        case "active": return "#5DCAA5"
        case "idle": return "#EF9F27"
        case "locked": return "#7c7c80"
        default: return "#7c7c80"
        }
    }
}

struct FactsResponse: Decodable {
    let status: String
    let count: Int
    let facts: [FactRecord]
    let reason: String?
}

struct FactsProfileResponse: Decodable {
    let profile: String
}

struct FactRecord: Decodable, Identifiable {
    let id: String
    let key: String
    let value: String
    let confidence: Double
    let category: String?
    let createdAt: String?
    let updatedAt: String?

    enum CodingKeys: String, CodingKey {
        case id, key, value, description, confidence, category
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        key = try container.decode(String.self, forKey: .key)
        confidence = try container.decode(Double.self, forKey: .confidence)
        category = try container.decodeIfPresent(String.self, forKey: .category)
        createdAt = try container.decodeIfPresent(String.self, forKey: .createdAt)
        updatedAt = try container.decodeIfPresent(String.self, forKey: .updatedAt)

        if let value = try container.decodeIfPresent(String.self, forKey: .value) {
            self.value = value
        } else {
            self.value = try container.decode(String.self, forKey: .description)
        }
    }

    var confidenceLabel: String {
        switch confidence {
        case 0.8...: return "Fort"
        case 0.6...: return "Moyen"
        default: return "Faible"
        }
    }

    var confidenceColor: String {
        switch confidence {
        case 0.8...: return "#5DCAA5"
        case 0.6...: return "#EF9F27"
        default: return "#7c7c80"
        }
    }
}

struct MemoryResponse: Decodable {
    let entries: [MemoryEntry]
    let frozenAt: String?

    enum CodingKeys: String, CodingKey {
        case entries
        case frozenAt = "frozen_at"
    }
}

struct MemoryEntry: Decodable, Identifiable {
    let id: String
    let content: String
    let tier: String?
    let topic: String?
    let createdAt: String?

    enum CodingKeys: String, CodingKey {
        case id, content, tier, topic
        case createdAt = "created_at"
    }
}

struct SessionsResponse: Decodable {
    let sessions: [SessionJournal]
}

struct SessionJournal: Decodable, Identifiable {
    var id: String { date }
    let date: String
    let content: String
}

struct TodaySummaryResponse: Decodable {
    let date: String
    let generatedAt: String
    let totals: TodayTotals
    let projects: [TodayProject]
    let workBlocks: [TodayWorkBlock]
    let timeline: TodayTimeline
    let currentWindow: TodayCurrentWindow?

    enum CodingKeys: String, CodingKey {
        case date
        case generatedAt = "generated_at"
        case totals
        case projects
        case workBlocks = "work_blocks"
        case timeline
        case currentWindow = "current_window"
    }
}

struct TodayTotals: Decodable {
    let workedMin: Int
    let activeMin: Int
    let commitCount: Int
    let windowCount: Int
    let projectCount: Int

    enum CodingKeys: String, CodingKey {
        case workedMin = "worked_min"
        case activeMin = "active_min"
        case commitCount = "commit_count"
        case windowCount = "window_count"
        case projectCount = "project_count"
    }
}

struct TodayProject: Decodable, Identifiable {
    var id: String { name }
    let name: String
    let workedMin: Int
    let activeMin: Int
    let commitCount: Int
    let topTasks: [String]

    enum CodingKeys: String, CodingKey {
        case name
        case workedMin = "worked_min"
        case activeMin = "active_min"
        case commitCount = "commit_count"
        case topTasks = "top_tasks"
    }
}

struct TodayTimeline: Decodable {
    let firstActivityAt: String?
    let lastActivityAt: String?

    enum CodingKeys: String, CodingKey {
        case firstActivityAt = "first_activity_at"
        case lastActivityAt = "last_activity_at"
    }
}

struct TodayWorkBlock: Decodable, Identifiable {
    let id: String
    let startedAt: String
    let endedAt: String
    let durationMin: Int
    let eventCount: Int
    let project: String?
    let probableTask: String?

    enum CodingKeys: String, CodingKey {
        case id
        case startedAt = "started_at"
        case endedAt = "ended_at"
        case durationMin = "duration_min"
        case eventCount = "event_count"
        case project
        case probableTask = "probable_task"
    }

    var taskLabel: String {
        switch probableTask {
        case "coding": return "Développement"
        case "writing": return "Rédaction"
        case "debug": return "Débogage"
        case "exploration", "browsing": return "Exploration"
        case "general": return "Général"
        default: return probableTask ?? "—"
        }
    }
}

struct TodayCurrentWindow: Decodable {
    let id: String
    let startedAt: String
    let updatedAt: String
    let project: String?
    let probableTask: String?
    let activityLevel: String?
    let commitCount: Int

    enum CodingKeys: String, CodingKey {
        case id
        case startedAt = "started_at"
        case updatedAt = "updated_at"
        case project
        case probableTask = "probable_task"
        case activityLevel = "activity_level"
        case commitCount = "commit_count"
    }

    var taskLabel: String {
        switch probableTask {
        case "coding": return "Développement"
        case "writing": return "Rédaction"
        case "debug": return "Débogage"
        case "exploration", "browsing": return "Exploration"
        case "general": return "Général"
        default: return probableTask ?? "—"
        }
    }

    var activityLabel: String {
        switch activityLevel {
        case "editing": return "Édition"
        case "reading": return "Lecture"
        case "executing": return "Exécution"
        case "navigating": return "Navigation"
        case "idle": return "Inactif"
        default: return activityLevel ?? "—"
        }
    }
}

struct FactsStatsResponse: Decodable {
    let total: Int?
    let active: Int?
    let archived: Int?
    let byCategory: [String: Int]?

    enum CodingKeys: String, CodingKey {
        case total
        case active
        case activeFacts = "active_facts"
        case archived
        case archivedFacts = "archived_facts"
        case byCategory = "by_category"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        total = try container.decodeIfPresent(Int.self, forKey: .total)
        active =
            try container.decodeIfPresent(Int.self, forKey: .active)
            ?? container.decodeIfPresent(Int.self, forKey: .activeFacts)
        archived =
            try container.decodeIfPresent(Int.self, forKey: .archived)
            ?? container.decodeIfPresent(Int.self, forKey: .archivedFacts)
        byCategory = try container.decodeIfPresent([String: Int].self, forKey: .byCategory)
    }
}

struct ScoringStatusResponse: Decodable {
    let treesitterCore: Bool?
    let pythonAst: Bool?
    let languages: [String: ScoringLanguageStatus]?

    enum CodingKeys: String, CodingKey {
        case treesitterCore = "treesitter_core"
        case pythonAst = "python_ast"
        case languages
    }
}

struct ScoringLanguageStatus: Decodable {
    let available: Bool?
    let parser: String?
}

struct AskResponse: Codable {
    let ok: Bool
    let response: String?
    let error: String?
}

struct CommandAnalysis: Codable {
    let toolUseId: String
    let command: String
    let translated: String
    let riskLevel: String
    let riskScore: Int
    let isReadOnly: Bool
    let affects: [String]?
    let warning: String?
    let needsLlm: Bool

    enum CodingKeys: String, CodingKey {
        case toolUseId = "tool_use_id"
        case command
        case translated
        case riskLevel = "risk_level"
        case riskScore = "risk_score"
        case isReadOnly = "is_read_only"
        case affects
        case warning
        case needsLlm = "needs_llm"
    }
}

struct ContextResponse: Codable {
    let context: String
}

struct LLMModelsResponse: Codable {
    let provider: String
    let availableModels: [String]
    let selectedModel: String?
    let selectedCommandModel: String
    let selectedSummaryModel: String
    let modelSelected: Bool?
    let llmReady: Bool?
    let ollamaOnline: Bool?
    let llmActive: Bool?

    enum CodingKeys: String, CodingKey {
        case provider
        case availableModels = "available_models"
        case selectedModel = "selected_model"
        case selectedCommandModel = "selected_command_model"
        case selectedSummaryModel = "selected_summary_model"
        case modelSelected = "model_selected"
        case llmReady = "llm_ready"
        case ollamaOnline = "ollama_online"
        case llmActive = "llm_active"
    }
}

struct SetLLMModelResponse: Codable {
    let ok: Bool
    let kind: String?
    let selectedModel: String?
    let selectedCommandModel: String?
    let selectedSummaryModel: String?

    enum CodingKeys: String, CodingKey {
        case ok
        case kind
        case selectedModel = "selected_model"
        case selectedCommandModel = "selected_command_model"
        case selectedSummaryModel = "selected_summary_model"
    }
}

struct ProposalHistoryResponse: Codable {
    let items: [ProposalRecord]
}

struct ProposalRecord: Identifiable, Codable {
    let id: String
    let type: String
    let title: String
    let summary: String
    let rationale: String
    let status: String
    let command: String?
    let translated: String?
    let riskLevel: String?
    let riskScore: Int?
    let createdAt: String
    let updatedAt: String
    let decidedAt: String?
    let evidence: [[String: String]]?

    enum CodingKeys: String, CodingKey {
        case id
        case type
        case title
        case summary
        case rationale
        case status
        case command
        case translated
        case riskLevel = "risk_level"
        case riskScore = "risk_score"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case decidedAt = "decided_at"
        case evidence
    }

    private static let internetISO8601Formatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    private static let internetISO8601WithoutFractionalFormatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    private static func localTimestampFormatter(_ format: String) -> DateFormatter {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = .current
        formatter.dateFormat = format
        return formatter
    }

    private static let localFractionalTimestampFormatter =
        localTimestampFormatter("yyyy-MM-dd'T'HH:mm:ss.SSSSSS")

    private static let localTimestampWithoutFractionalFormatter =
        localTimestampFormatter("yyyy-MM-dd'T'HH:mm:ss")

    private static let clockFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "fr_FR")
        formatter.dateFormat = "HH:mm"
        return formatter
    }()

    private var effectiveTimestamp: String {
        decidedAt ?? updatedAt
    }

    private var parsedDate: Date? {
        Self.internetISO8601Formatter.date(from: effectiveTimestamp)
            ?? Self.internetISO8601WithoutFractionalFormatter.date(from: effectiveTimestamp)
            ?? Self.localFractionalTimestampFormatter.date(from: effectiveTimestamp)
            ?? Self.localTimestampWithoutFractionalFormatter.date(from: effectiveTimestamp)
    }

    var displayTitle: String {
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty { return trimmed }
        let fallback = summary.trimmingCharacters(in: .whitespacesAndNewlines)
        return fallback.isEmpty ? typeLabel : fallback
    }

    var typeLabel: String {
        switch type {
        case "risky_command": return "Commande risquée"
        case "context_injection": return "Contexte assistant"
        default: return type.replacingOccurrences(of: "_", with: " ")
        }
    }

    var flowLabel: String {
        switch type {
        case "risky_command":
            return status == "pending" ? "validation requise" : "validation utilisateur"
        case "context_injection":
            return "application automatique"
        default:
            return status == "pending" ? "en attente" : "traitement interne"
        }
    }

    var statusLabel: String {
        switch status {
        case "pending": return "À valider"
        case "accepted": return "Autorisée"
        case "refused": return "Refusée"
        case "expired": return "Expirée"
        case "executed": return "Appliquée"
        default: return status
        }
    }

    var statusAccentHex: String {
        switch status {
        case "accepted": return "#5DCAA5"
        case "refused": return "#ff453a"
        case "expired": return "#7c7c80"
        case "executed": return "#5E9EFF"
        default: return "#EF9F27"
        }
    }

    var timeLabel: String {
        guard let date = parsedDate else { return "" }
        return Self.clockFormatter.string(from: date)
    }

    var relativeTimeLabel: String {
        guard let date = parsedDate else { return "" }
        let diff = Date().timeIntervalSince(date)
        if diff < 10 { return "à l'instant" }
        if diff < 60 { return "il y a \(Int(diff)) s" }
        if diff < 3600 { return "il y a \(Int(diff / 60)) min" }
        if diff < 86_400 { return "il y a \(Int(diff / 3600)) h" }
        return "il y a \(Int(diff / 86_400)) j"
    }

    var statusSummary: String {
        switch (type, status) {
        case ("risky_command", "pending"):
            return "Pulse a détecté une commande sensible et attend votre choix."
        case ("risky_command", "accepted"):
            return "La commande sensible a été autorisée."
        case ("risky_command", "refused"):
            return "La commande sensible a été refusée."
        case ("risky_command", "expired"):
            return "La commande sensible a expiré sans validation."
        case ("context_injection", "executed"):
            return "Pulse a injecté le contexte existant automatiquement."
        case ("context_injection", "pending"):
            return "Pulse prépare une injection de contexte."
        default:
            return "Pulse a enregistré cette proposition."
        }
    }

    var detailText: String? {
        let normalizedTitle = displayTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedSummary = summary.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedRationale = rationale.trimmingCharacters(in: .whitespacesAndNewlines)

        var parts: [String] = [statusSummary]
        if !normalizedSummary.isEmpty && normalizedSummary != normalizedTitle && normalizedSummary != statusSummary {
            parts.append(normalizedSummary)
        }
        if !normalizedRationale.isEmpty && normalizedRationale != normalizedSummary && normalizedRationale != statusSummary {
            parts.append("Pourquoi : \(normalizedRationale)")
        }
        return parts.isEmpty ? nil : parts.joined(separator: " ")
    }
}

struct ContextProbeListResponse: Decodable {
    let requests: [ContextProbeRequestPayload]
    let debug: [ContextProbeDebugPayload]
    let count: Int
}

struct ContextProbeActionResponse: Decodable {
    let request: ContextProbeRequestPayload
    let debug: ContextProbeDebugPayload
}

struct ContextProbeExecuteResponse: Decodable {
    let result: ContextProbeResultPayload
    let request: ContextProbeRequestPayload
    let debug: ContextProbeDebugPayload
}

struct ContextProbeRequestPayload: Decodable, Identifiable {
    let requestId: String
    let kind: String
    let reason: String
    let policy: ContextProbePolicyPayload
    let status: String
    let createdAt: String
    let expiresAt: String?
    let decidedAt: String?
    let executedAt: String?
    let decisionReason: String?
    let metadataKeys: [String]
    let isTerminal: Bool

    enum CodingKeys: String, CodingKey {
        case requestId = "request_id"
        case kind
        case reason
        case policy
        case status
        case createdAt = "created_at"
        case expiresAt = "expires_at"
        case decidedAt = "decided_at"
        case executedAt = "executed_at"
        case decisionReason = "decision_reason"
        case metadataKeys = "metadata_keys"
        case isTerminal = "is_terminal"
    }

    var id: String { requestId }

    var kindLabel: String {
        switch kind {
        case "app_context": return "Contexte app"
        case "window_title": return "Titre fenêtre"
        case "selected_text": return "Texte sélectionné"
        case "clipboard_sample": return "Extrait clipboard"
        case "screen_snapshot": return "Capture écran"
        case "unknown": return "Probe inconnu"
        default: return kind.replacingOccurrences(of: "_", with: " ")
        }
    }

    var statusLabel: String {
        switch status {
        case "pending": return "À valider"
        case "approved": return "Approuvée"
        case "refused": return "Refusée"
        case "expired": return "Expirée"
        case "executed": return "Exécutée"
        case "cancelled": return "Annulée"
        default: return status
        }
    }

    var statusAccentHex: String {
        switch status {
        case "approved": return "#5DCAA5"
        case "executed": return "#5E9EFF"
        case "refused": return "#ff453a"
        case "expired", "cancelled": return "#7c7c80"
        default: return "#EF9F27"
        }
    }

    var canApproveOrRefuse: Bool {
        status == "pending"
    }

    var canExecute: Bool {
        status == "approved" && kind == "app_context"
    }
}

struct ContextProbeDebugPayload: Decodable, Identifiable {
    let requestId: String
    let kind: String
    let status: String
    let reason: String
    let createdAt: String
    let expiresAt: String?
    let decidedAt: String?
    let executedAt: String?
    let decisionReason: String?
    let isTerminal: Bool
    let isExpired: Bool
    let policy: ContextProbePolicyPayload
    let labels: ContextProbeLabelsPayload
    let metadataKeys: [String]

    enum CodingKeys: String, CodingKey {
        case requestId = "request_id"
        case kind
        case status
        case reason
        case createdAt = "created_at"
        case expiresAt = "expires_at"
        case decidedAt = "decided_at"
        case executedAt = "executed_at"
        case decisionReason = "decision_reason"
        case isTerminal = "is_terminal"
        case isExpired = "is_expired"
        case policy
        case labels
        case metadataKeys = "metadata_keys"
    }

    var id: String { requestId }
}

struct ContextProbePolicyPayload: Decodable {
    let kind: String
    let consent: String
    let privacy: String
    let retention: String
    let allowRawValue: Bool
    let allowPersistentStorage: Bool
    let requiresUserVisibleReason: Bool
    let maxChars: Int?

    enum CodingKeys: String, CodingKey {
        case kind
        case consent
        case privacy
        case retention
        case allowRawValue = "allow_raw_value"
        case allowPersistentStorage = "allow_persistent_storage"
        case requiresUserVisibleReason = "requires_user_visible_reason"
        case maxChars = "max_chars"
    }

    var consentLabel: String {
        switch consent {
        case "none": return "Aucun"
        case "implicit_session": return "Session"
        case "explicit_each_time": return "À chaque fois"
        case "blocked": return "Bloqué"
        default: return consent
        }
    }

    var privacyLabel: String {
        switch privacy {
        case "public": return "Public"
        case "path_sensitive": return "Chemin sensible"
        case "content_sensitive": return "Contenu sensible"
        case "secret_sensitive": return "Secret potentiel"
        case "unknown": return "Inconnu"
        default: return privacy
        }
    }

    var retentionLabel: String {
        switch retention {
        case "ephemeral": return "Éphémère"
        case "session": return "Session"
        case "persistent": return "Persistant"
        case "debug_only": return "Debug only"
        default: return retention
        }
    }
}

struct ContextProbeLabelsPayload: Decodable {
    let kind: String
    let consent: String
    let privacy: String
    let retention: String
    let risk: String

    var riskAccentHex: String {
        switch risk {
        case "Low": return "#5DCAA5"
        case "Moderate": return "#EF9F27"
        case "Sensitive": return "#ff453a"
        case "Blocked": return "#7c7c80"
        default: return "#7c7c80"
        }
    }
}

struct ContextProbeResultPayload: Decodable {
    let requestId: String
    let kind: String
    let captured: Bool
    let data: [String: ContextProbeResultValue]
    let privacy: String
    let retention: String
    let capturedAt: String
    let blockedReason: String?

    enum CodingKeys: String, CodingKey {
        case requestId = "request_id"
        case kind
        case captured
        case data
        case privacy
        case retention
        case capturedAt = "captured_at"
        case blockedReason = "blocked_reason"
    }
}


enum ContextProbeResultValue: Decodable {
    case string(String)
    case int(Int)
    case double(Double)
    case bool(Bool)
    case stringArray([String])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode(Int.self) {
            self = .int(value)
        } else if let value = try? container.decode(Double.self) {
            self = .double(value)
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode([String].self) {
            self = .stringArray(value)
        } else {
            self = .null
        }
    }

    var displayValue: String {
        switch self {
        case .string(let value): return value
        case .int(let value): return "\(value)"
        case .double(let value): return String(format: "%.2f", value)
        case .bool(let value): return value ? "true" : "false"
        case .stringArray(let value): return value.joined(separator: " · ")
        case .null: return "—"
        }
    }

    var stringArrayValue: [String]? {
        if case .stringArray(let value) = self { return value }
        return nil
    }
}

struct WorkContextCardResponse: Decodable {
    let card: WorkContextCardPayload
}

struct WorkContextCardPayload: Decodable {
    let project: String?
    let projectHint: String?
    let projectHintConfidence: Double
    let projectHintSource: String?
    let activityLevel: String
    let probableTask: String
    let confidence: Double
    let evidence: [String]
    let missingContext: [String]
    let safeNextProbes: [String]

    enum CodingKeys: String, CodingKey {
        case project
        case projectHint = "project_hint"
        case projectHintConfidence = "project_hint_confidence"
        case projectHintSource = "project_hint_source"
        case activityLevel = "activity_level"
        case probableTask = "probable_task"
        case confidence
        case evidence
        case missingContext = "missing_context"
        case safeNextProbes = "safe_next_probes"
    }

    var projectLabel: String {
        project?.isEmpty == false ? project! : "Projet inconnu"
    }

    var projectHintLabel: String? {
        guard let projectHint, !projectHint.isEmpty else { return nil }
        let confidence = Int((projectHintConfidence * 100).rounded())
        if let projectHintSource, !projectHintSource.isEmpty {
            return "Indice faible : \(projectHint) · \(projectHintSource) · \(confidence) %"
        }
        return "Indice faible : \(projectHint) · \(confidence) %"
    }

    var activityLabel: String {
        switch activityLevel {
        case "editing": return "Édition"
        case "reading": return "Lecture"
        case "executing": return "Exécution"
        case "navigating": return "Navigation"
        case "idle": return "Inactif"
        case "unknown": return "Inconnu"
        default: return activityLevel
        }
    }

    var taskLabel: String {
        switch probableTask {
        case "coding": return "Développement"
        case "writing": return "Rédaction"
        case "debug": return "Débogage"
        case "review": return "Revue"
        case "test": return "Tests"
        case "exploration", "browsing": return "Exploration"
        case "general": return "Général"
        default: return probableTask
        }
    }

    var confidencePercentLabel: String {
        "\(Int((confidence * 100).rounded())) %"
    }

    var confidenceAccentHex: String {
        switch confidence {
        case 0.75...: return "#5DCAA5"
        case 0.45..<0.75: return "#EF9F27"
        default: return "#7c7c80"
        }
    }
}

struct InsightEvent: Identifiable {
    let id = UUID()
    let type: String
    let timestamp: String
    let keyValue: String?

    private static let internetISO8601Formatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    private static let internetISO8601WithoutFractionalFormatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    private static func localTimestampFormatter(_ format: String) -> DateFormatter {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = .current
        formatter.dateFormat = format
        return formatter
    }

    private static let localFractionalTimestampFormatter =
        localTimestampFormatter("yyyy-MM-dd'T'HH:mm:ss.SSSSSS")

    private static let localTimestampWithoutFractionalFormatter =
        localTimestampFormatter("yyyy-MM-dd'T'HH:mm:ss")

    private static let clockFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "fr_FR")
        formatter.dateFormat = "HH:mm"
        return formatter
    }()

    private var parsedDate: Date? {
        Self.internetISO8601Formatter.date(from: timestamp)
            ?? Self.internetISO8601WithoutFractionalFormatter.date(from: timestamp)
            ?? Self.localFractionalTimestampFormatter.date(from: timestamp)
            ?? Self.localTimestampWithoutFractionalFormatter.date(from: timestamp)
    }

    var label: String {
        switch type {
        case "app_activated", "app_switch": return "App"
        case "local_exploration": return "Exploration locale"
        case "file_modified": return "Modifié"
        case "file_created": return "Créé"
        case "file_deleted": return "Supprimé"
        case "file_renamed": return "Renommé"
        case "clipboard_updated": return "Clipboard"
        case "screen_locked": return "screen_locked"
        case "screen_unlocked": return "screen_unlocked"
        case "mcp_command_received": return "MCP"
        default: return type
        }
    }

    var timeLabel: String {
        guard let date = parsedDate else { return "" }
        return Self.clockFormatter.string(from: date)
    }

    var relativeTimeLabel: String {
        guard let date = parsedDate else { return "" }
        let diff = Date().timeIntervalSince(date)
        if diff < 10 { return "à l'instant" }
        if diff < 60 { return "il y a \(Int(diff)) s" }
        if diff < 3600 { return "il y a \(Int(diff / 60)) min" }
        if diff < 86_400 { return "il y a \(Int(diff / 3600)) h" }
        return "il y a \(Int(diff / 86_400)) j"
    }

    var iconName: String {
        switch type {
        case "app_activated", "app_switch": return "app.badge"
        case "local_exploration": return "folder"
        case "file_modified": return "pencil.line"
        case "file_created": return "plus.square"
        case "file_deleted": return "trash"
        case "file_renamed": return "character.cursor.ibeam"
        case "clipboard_updated": return "doc.on.clipboard"
        case "screen_locked": return "lock.fill"
        case "screen_unlocked": return "lock.open.fill"
        case "mcp_command_received": return "terminal"
        default: return "circle.fill"
        }
    }

    var accentHex: String {
        switch type {
        case "app_activated", "app_switch": return "#5E9EFF"
        case "local_exploration": return "#8B5CF6"
        case "file_modified": return "#5DCAA5"
        case "file_created": return "#7DD3FC"
        case "file_deleted": return "#ff453a"
        case "file_renamed": return "#EF9F27"
        case "clipboard_updated": return "#C084FC"
        case "screen_locked", "screen_unlocked": return "#7c7c80"
        case "mcp_command_received": return "#F59E0B"
        default: return "#7c7c80"
        }
    }

    var primaryText: String {
        if let keyValue, !keyValue.isEmpty {
            return keyValue
        }
        return label
    }

    var secondaryText: String {
        switch type {
        case "app_activated", "app_switch": return "application active"
        case "local_exploration": return "exploration locale"
        case "file_modified": return "fichier modifié"
        case "file_created": return "fichier créé"
        case "file_deleted": return "fichier supprimé"
        case "file_renamed": return "fichier renommé"
        case "clipboard_updated": return "presse-papiers mis à jour"
        case "screen_locked": return "session verrouillée"
        case "screen_unlocked": return "session déverrouillée"
        case "mcp_command_received": return "commande reçue"
        default: return label.lowercased()
        }
    }
}

struct FeedEvent: Identifiable {
    let id = UUID()
    let kind: String
    let label: String
    let success: Bool?
    let command: String?
    let timestamp: String
    let resumeCard: ResumeCard?

    var accentHex: String {
        switch kind {
        case "terminal":
            return (success == true) ? "#5DCAA5" : "#ff453a"
        case "commit":
            return "#5DCAA5"
        case "resume_card":
            return "#5E9EFF"
        default:
            return "#7c7c80"
        }
    }

    var icon: String {
        switch kind {
        case "terminal":
            return (success == true) ? "checkmark.circle.fill" : "xmark.circle.fill"
        case "commit":
            return "arrow.up.circle.fill"
        case "resume_card":
            return "arrow.clockwise.circle.fill"
        default:
            return "circle.fill"
        }
    }
}

struct ResumeCard: Identifiable, Equatable {
    let id: String
    let project: String?
    let title: String
    let summary: String
    let lastObjective: String
    let nextAction: String
    let confidence: Double
    let sourceRefs: [String]
    let generatedBy: String
    let displaySize: String
    let createdAt: String?

    var displayHeight: CGFloat {
        switch displaySize {
        case "compact":
            return NotchWindow.resumeCompactHeight
        case "expanded":
            return expandedDisplayHeight
        default:
            return NotchWindow.resumeStandardHeight
        }
    }

    private var expandedDisplayHeight: CGFloat {
        let totalLength = summary.count + lastObjective.count + nextAction.count
        switch totalLength {
        case 0..<260:
            return 220
        case 260..<380:
            return 250
        default:
            return NotchWindow.resumeExpandedHeight
        }
    }
}

struct ObservationWindowTitle: Identifiable {
    let id = UUID()
    let title: String
    let app: String
    let timestamp: String
    let elapsedSec: Int
}

struct ObservationTerminalCommand: Identifiable {
    let id = UUID()
    let command: String
    let summary: String
    let success: Bool?
    let durationMs: Int?
    let project: String
    let timestamp: String
}

struct ObservationData {
    let windowTitles: [ObservationWindowTitle]
    let terminalCommands: [ObservationTerminalCommand]
}

struct DaydreamEntry: Identifiable {
    let id: String
    let date: String
    let content: String
}

struct DaydreamStatus {
    let status: String
    let pending: Bool
    let targetDate: String?
    let doneForDate: String?
    let lastReason: String?
    let lastError: String?
    let lastAttemptAt: String?
    let lastCompletedAt: String?
    let lastOutputPath: String?
}

enum DaemonError: Error {
    case invalidURL
    case badStatus(Int)
    case badResponse
    case decoding
    case unreachable
    case llm(String)

    static func from(_ error: Error) -> DaemonError {
        if let daemonError = error as? DaemonError {
            return daemonError
        }
        if error is DecodingError {
            return .decoding
        }
        if let urlError = error as? URLError {
            switch urlError.code {
            case .cannotConnectToHost,
                 .cannotFindHost,
                 .networkConnectionLost,
                 .notConnectedToInternet,
                 .timedOut:
                return .unreachable
            default:
                return .badResponse
            }
        }
        return .badResponse
    }

    var userMessage: String {
        switch self {
        case .invalidURL, .badResponse, .decoding:
            return "Réponse du daemon invalide."
        case .badStatus(let statusCode):
            if statusCode >= 500 {
                return "Le daemon a rencontré une erreur."
            }
            return "Requête refusée par le daemon."
        case .unreachable:
            return "Daemon injoignable."
        case .llm(let message):
            return message
        }
    }
}
