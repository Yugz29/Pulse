import Foundation

struct ResumeThreadPanelSnapshot: Equatable {
    struct Source {
        var activeProject: String?
        var activeApp: String?
        var activeFile: String?
        var taskLabel: String
        var sessionDuration: Int
        var focusLabel: String
        var feedEvent: FeedEvent?
        var insightEvent: InsightEvent?
        var whyLine: String?
        var resumeNextAction: String?
        var workIntentSummary: String?
        var lastSessionContext: String?
    }

    let title: String
    let contextLine: String
    let fileLine: String
    let taskLine: String
    let sessionLine: String
    let focusLine: String
    let lastSignalTitle: String
    let lastSignalDetail: String
    let whyLine: String
    let nextActionLine: String

    @MainActor
    init(vm: PulseViewModel) {
        self.init(source: Source(
            activeProject: vm.activeProject,
            activeApp: vm.activeApp,
            activeFile: vm.activeFile,
            taskLabel: Self.taskLabel(
                context: vm.currentContext,
                present: vm.currentPresent,
                fallback: vm.probableTask
            ),
            sessionDuration: vm.sessionDuration,
            focusLabel: Self.focusLabel(vm.focusLevel),
            feedEvent: vm.feedHistory.first,
            insightEvent: vm.recentEvents.first,
            whyLine: vm.currentSignals?.taskEvidenceSummary
                ?? vm.currentSignals?.fileActivitySummary,
            resumeNextAction: vm.activeResumeCard?.nextAction,
            workIntentSummary: vm.currentContext?.workIntent?.summary,
            lastSessionContext: vm.currentSignals?.lastSessionContext
        ))
    }

    init(source: Source) {
        title = "Reprise du fil"
        contextLine = Self.firstNonEmpty(source.activeProject, source.activeApp) ?? "Contexte local"
        fileLine = Self.fileLine(source.activeFile)
        taskLine = source.taskLabel
        sessionLine = source.sessionDuration > 0
            ? "\(source.sessionDuration) min observees"
            : "Duree non etablie"
        focusLine = source.focusLabel

        let signal = Self.lastSignal(feedEvent: source.feedEvent, insightEvent: source.insightEvent)
        lastSignalTitle = signal.title
        lastSignalDetail = signal.detail

        whyLine = Self.nonEmpty(source.whyLine) ?? "Pulse garde une lecture prudente du contexte local."
        nextActionLine = Self.firstNonEmpty(
            source.resumeNextAction,
            source.workIntentSummary,
            source.lastSessionContext
        ) ?? "Revenir au contexte actif observé."
    }

    nonisolated private static func firstNonEmpty(_ values: String?...) -> String? {
        values.lazy.compactMap(nonEmpty).first
    }

    nonisolated private static func nonEmpty(_ value: String?) -> String? {
        let trimmed = value?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return trimmed.isEmpty ? nil : trimmed
    }

    nonisolated private static func fileLine(_ path: String?) -> String {
        guard let path = nonEmpty(path) else { return "Aucun fichier actif" }
        return URL(fileURLWithPath: path).lastPathComponent
    }

    private static func lastSignal(feedEvent: FeedEvent?, insightEvent: InsightEvent?) -> (title: String, detail: String) {
        if let event = feedEvent {
            return (
                event.label,
                nonEmpty(event.command) ?? event.timestamp
            )
        }
        if let event = insightEvent {
            return (
                event.primaryText,
                "\(event.secondaryText) · \(event.relativeTimeLabel)"
            )
        }
        return ("Aucun signal notable", "Pulse n'a pas encore observe d'evenement recent important.")
    }

    private static func taskLabel(
        context: SessionContextData?,
        present: PresentData?,
        fallback: String
    ) -> String {
        if let context, context.taskLabel != "—" {
            return context.taskLabel
        }
        if let present {
            return present.taskLabel == "Général" ? "Contexte léger" : present.taskLabel
        }
        switch fallback {
        case "coding": return "Développement"
        case "writing": return "Rédaction"
        case "debug": return "Débogage"
        case "exploration", "browsing": return "Exploration"
        default: return "Contexte léger"
        }
    }

    nonisolated private static func focusLabel(_ focus: String) -> String {
        switch focus {
        case "deep": return "Focus profond"
        case "scattered": return "Focus fragmente"
        case "idle": return "Attention faible"
        default: return "Focus normal"
        }
    }
}
