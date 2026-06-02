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
        var terminalSummary: String? = nil
        var terminalSuccess: Bool? = nil
        var terminalActionCategory: String? = nil
        var recentApps: [String] = []

        var hasCurrentContext: Bool {
            ResumeThreadPanelSnapshot.firstNonEmpty(activeProject, activeApp, activeFile) != nil
        }

        var hasRecentSignal: Bool {
            feedEvent != nil || insightEvent != nil || ResumeThreadPanelSnapshot.nonEmpty(terminalSummary) != nil
        }
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
            lastSessionContext: vm.currentSignals?.lastSessionContext,
            terminalSummary: vm.currentContext?.terminalSummary,
            terminalSuccess: vm.currentContext?.terminalSuccess,
            terminalActionCategory: vm.currentContext?.terminalActionCategory,
            recentApps: vm.recentApps
        ))
    }

    init(source: Source) {
        title = "Reprise du fil"
        contextLine = Self.firstNonEmpty(source.activeProject, source.activeApp) ?? "Contexte local"
        fileLine = Self.fileLine(source.activeFile)
        taskLine = source.taskLabel
        sessionLine = source.sessionDuration > 0
            ? "\(Self.formatDuration(source.sessionDuration)) observées"
            : "Duree non etablie"
        focusLine = source.focusLabel

        let signal = Self.lastSignal(
            feedEvent: source.feedEvent,
            insightEvent: source.insightEvent,
            terminalSummary: source.terminalSummary
        )
        lastSignalTitle = signal.title
        lastSignalDetail = signal.detail

        whyLine = Self.whyLine(source)
        nextActionLine = Self.nextActionLine(source)
    }

    private static func nextActionLine(_ source: Source) -> String {
        if let action = firstNonEmpty(
            source.resumeNextAction,
            source.workIntentSummary
        ) {
            return action
        }

        if let fileName = fileName(source.activeFile) {
            return "Revenir à \(fileName)."
        }

        if nonEmpty(source.terminalSummary) != nil {
            return "Reprendre depuis la dernière commande observée."
        }

        if source.hasRecentSignal {
            return "Reprendre depuis le dernier signal observé."
        }

        return "Revenir au contexte actif observé."
    }

    private static func whyLine(_ source: Source) -> String {
        if nonEmpty(source.terminalSummary) != nil {
            return "Une commande récente a été détectée."
        }

        if nonEmpty(source.activeFile) != nil, hasRecentApps(source.recentApps) {
            return "Le contexte vient du fichier actif et des apps récentes."
        }

        if nonEmpty(source.activeFile) != nil {
            return "Le contexte vient du fichier actif observé."
        }

        if nonEmpty(source.activeApp) != nil, hasRecentApps(source.recentApps) {
            return "Le contexte vient de l’app active et des apps récentes."
        }

        if hasRecentApps(source.recentApps) {
            return "Le contexte vient de l’app active et des apps récentes."
        }

        if source.feedEvent != nil || source.insightEvent != nil {
            return "Le contexte vient surtout des signaux récents du poste."
        }

        if nonEmpty(source.activeProject) != nil || nonEmpty(source.activeApp) != nil {
            return "Le contexte vient de l’app active et des signaux récents."
        }

        if nonEmpty(source.whyLine) != nil {
            return "Le contexte vient surtout des signaux récents du poste."
        }

        return "Le contexte local reste limité aux signaux observés."
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

    nonisolated private static func fileName(_ path: String?) -> String? {
        guard let path = nonEmpty(path) else { return nil }
        let name = URL(fileURLWithPath: path).lastPathComponent
        return nonEmpty(name)
    }

    nonisolated private static func hasRecentApps(_ apps: [String]) -> Bool {
        apps.contains { nonEmpty($0) != nil }
    }

    nonisolated private static func formatDuration(_ minutes: Int) -> String {
        if minutes < 60 {
            return "\(minutes) min"
        }

        let hours = minutes / 60
        let remainingMinutes = minutes % 60
        if remainingMinutes == 0 {
            return "\(hours) h"
        }
        return "\(hours) h \(remainingMinutes)"
    }

    nonisolated private static func sanitizedLastSessionContext(_ value: String?) -> String? {
        guard var line = nonEmpty(value) else { return nil }
        line = replaceMinuteDurations(in: line)
        if let sentenceEnd = line.firstIndex(where: { ".!?".contains($0) }) {
            line = String(line[...sentenceEnd])
        }
        if line.count > 120 {
            line = String(line.prefix(117)).trimmingCharacters(in: .whitespacesAndNewlines) + "..."
        }
        return nonEmpty(line)
    }

    nonisolated private static func replaceMinuteDurations(in line: String) -> String {
        let pattern = #"\b(\d+)\s*min\b"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return line }
        let nsRange = NSRange(line.startIndex..<line.endIndex, in: line)
        let matches = regex.matches(in: line, range: nsRange).reversed()
        var result = line

        for match in matches {
            guard
                match.numberOfRanges > 1,
                let fullRange = Range(match.range(at: 0), in: result),
                let valueRange = Range(match.range(at: 1), in: result),
                let minutes = Int(result[valueRange])
            else { continue }
            result.replaceSubrange(fullRange, with: formatDuration(minutes))
        }

        return result
    }

    private static func lastSignal(
        feedEvent: FeedEvent?,
        insightEvent: InsightEvent?,
        terminalSummary: String?
    ) -> (title: String, detail: String) {
        if let event = feedEvent {
            return (
                event.label,
                nonEmpty(terminalSummary)
                    ?? safeCommandDetail(event.command)
                    ?? event.timestamp
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

    nonisolated private static func safeCommandDetail(_ command: String?) -> String? {
        guard let command = nonEmpty(command), command.count <= 80 else { return nil }
        let lowered = command.lowercased()
        let sensitiveMarkers = ["token", "secret", "password", "api_key", "private_key"]
        if sensitiveMarkers.contains(where: { lowered.contains($0) }) {
            return nil
        }
        return command
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
