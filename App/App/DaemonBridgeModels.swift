import Foundation

struct PingResponse: Codable {
    let status: String
    let version: String
    let paused: Bool?
}

struct StateResponse: Codable {
    let activeApp: String?
    let activeFile: String?
    let activeProject: String?
    let sessionDurationMin: Int
    let lastEventType: String?
    let runtimePaused: Bool?
    let signals: SignalsData?

    enum CodingKeys: String, CodingKey {
        case activeApp = "active_app"
        case activeFile = "active_file"
        case activeProject = "active_project"
        case sessionDurationMin = "session_duration_min"
        case lastEventType = "last_event_type"
        case runtimePaused = "runtime_paused"
        case signals
    }
}

struct SignalsData: Codable {
    let probableTask: String?
    let focusLevel: String?
    let frictionScore: Double?
    let recentApps: [String]?

    enum CodingKeys: String, CodingKey {
        case probableTask = "probable_task"
        case focusLevel = "focus_level"
        case frictionScore = "friction_score"
        case recentApps = "recent_apps"
    }
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
    let createdAt: String
    let updatedAt: String
    let decidedAt: String?

    enum CodingKeys: String, CodingKey {
        case id
        case type
        case title
        case summary
        case rationale
        case status
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case decidedAt = "decided_at"
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
        case "file_modified": return "Modifié"
        case "file_created": return "Créé"
        case "file_deleted": return "Supprimé"
        case "file_renamed": return "Renommé"
        case "clipboard_updated": return "Clipboard"
        case "screen_locked": return "Verrouillé"
        case "screen_unlocked": return "Déverrouillé"
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
