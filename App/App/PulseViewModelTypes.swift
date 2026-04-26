import SwiftUI

struct ChatMessage: Identifiable {
    let id      = UUID()
    let role:   String   // "user" | "assistant"
    var content: String
    var isStreaming: Bool = false
}

enum PanelMode {
    case dashboard
    case chat
    case currentState
    case insight
    case settings
    case status
    case feed
}

enum PulseServiceStatus {
    case daemonOffline
    case daemonPaused
    case observationPaused
    case llmUnavailable
    case healthy

    var iconName: String {
        switch self {
        case .daemonOffline:
            return "xmark.circle.fill"
        case .daemonPaused:
            return "pause.circle.fill"
        case .observationPaused:
            return "pause.circle.fill"
        case .llmUnavailable:
            return "exclamationmark.circle.fill"
        case .healthy:
            return "checkmark.circle.fill"
        }
    }

    var color: Color {
        switch self {
        case .daemonOffline:
            return Color(hex: "#ff453a")
        case .daemonPaused, .observationPaused, .llmUnavailable:
            return Color(hex: "#EF9F27")
        case .healthy:
            return Color(hex: "#5DCAA5")
        }
    }
}
