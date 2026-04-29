import SwiftUI

struct CurrentStateView: View {
    @ObservedObject var vm: PulseViewModel
    private let proposalLimit = 4
    private var currentPresent: PresentData? { vm.currentPresent }
    private var currentContext: SessionContextData? { vm.currentContext }
    private var currentSignals: SignalsData? { vm.currentSignals }

    private var visibleProposals: [ProposalRecord] {
        Array(vm.recentProposals.prefix(proposalLimit))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if currentPresent == nil && currentContext == nil && visibleProposals.isEmpty {
                HStack {
                    Spacer()
                    Text("Aucune lecture courante ni proposition récente")
                        .font(.system(size: 11))
                        .foregroundColor(.white.opacity(0.22))
                    Spacer()
                }
                .padding(.top, 16)
            } else {
                ScrollView(.vertical, showsIndicators: false) {
                    VStack(alignment: .leading, spacing: 0) {
                        sectionHeader("Contexte actuel")
                            .padding(.horizontal, 18)
                            .padding(.top, 10)

                        currentContextRow
                            .padding(.horizontal, 18)

                        if currentContext != nil || currentPresent != nil {
                            Divider().background(Color.white.opacity(0.05))

                            sectionHeader("Bloc courant")
                                .padding(.horizontal, 18)
                                .padding(.top, 8)

                            currentInterpretationRow(
                                context: currentContext,
                                present: currentPresent,
                                signals: currentSignals
                            )
                                .padding(.horizontal, 18)
                        }

                        if !visibleProposals.isEmpty {
                            Divider().background(Color.white.opacity(0.05))

                            sectionHeaderRow("Propositions récentes", count: visibleProposals.count)
                                .padding(.horizontal, 18)
                                .padding(.top, 8)

                            VStack(spacing: 0) {
                                ForEach(visibleProposals) { proposal in
                                    proposalRow(proposal)
                                    if proposal.id != visibleProposals.last?.id {
                                        Divider().background(Color.white.opacity(0.05))
                                    }
                                }
                            }
                            .padding(.horizontal, 18)
                        }
                    }
                }
            }
        }
        .frame(height: NotchWindow.currentStateHeight - .panelContentGap, alignment: .top)
        .onAppear { vm.refreshInsights() }
    }

    private func sectionHeaderRow(_ title: String, count: Int) -> some View {
        HStack {
            sectionHeader(title)
            Spacer()
            Text("\(count) visible\(count > 1 ? "s" : "")")
                .font(.system(size: 9, weight: .semibold))
                .foregroundColor(.white.opacity(0.30))
        }
    }

    private func sectionHeader(_ title: String) -> some View {
        Text(title)
            .font(.system(size: 10, weight: .semibold))
            .foregroundColor(.white.opacity(0.34))
            .tracking(0.4)
    }

    private var currentContextRow: some View {
        HStack(alignment: .top, spacing: 10) {
            ZStack {
                Circle()
                    .fill(Color.white.opacity(0.08))
                    .frame(width: 24, height: 24)
                Image(systemName: "scope")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundColor(.white.opacity(0.68))
            }

            VStack(alignment: .leading, spacing: 4) {
                Text(currentContextSummary)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundColor(.white.opacity(0.78))
                    .lineLimit(2)

                Text(currentContextDetail)
                    .font(.system(size: 10))
                    .foregroundColor(.white.opacity(0.36))
                    .lineLimit(2)

                if let continuity = continuityLine {
                    Text(continuity)
                        .font(.system(size: 10))
                        .foregroundColor(.white.opacity(0.28))
                        .lineLimit(1)
                }
            }
        }
        .padding(.vertical, 8)
    }

    private var currentContextSummary: String {
        if let project = vm.activeProject, !project.isEmpty,
           let file = vm.activeFile, !file.isEmpty {
            let fileName = URL(fileURLWithPath: file).lastPathComponent
            return "\(project) · \(fileName)"
        }
        if let project = vm.activeProject, !project.isEmpty {
            return project
        }
        if let file = vm.activeFile, !file.isEmpty {
            return URL(fileURLWithPath: file).lastPathComponent
        }
        if let app = vm.activeApp, !app.isEmpty {
            return app
        }
        return vm.isDaemonActive ? "Contexte courant léger" : "Pulse inactif"
    }

    private var currentContextDetail: String {
        var parts: [String] = []
        if let app = vm.activeApp, !app.isEmpty {
            parts.append("App : \(app)")
        }
        if vm.sessionDuration > 0 {
            let durationLabel = vm.probableTask == "general" ? "Présence" : "Session"
            parts.append("\(durationLabel) : \(vm.sessionDuration) min")
        }
        if let signals = currentSignals,
           let fileActivity = signals.fileActivitySummary {
            parts.append(fileActivity)
        }
        return parts.isEmpty ? "Pas encore assez de contexte local." : parts.joined(separator: " · ")
    }

    private var continuityLine: String? {
        guard vm.probableTask != "general" else { return nil }
        return currentSignals?.lastSessionContext
    }

    private func proposalRow(_ proposal: ProposalRecord) -> some View {
        HStack(alignment: .top, spacing: 10) {
            ZStack {
                Circle()
                    .fill(Color(hex: proposal.statusAccentHex).opacity(0.18))
                    .frame(width: 24, height: 24)
                Circle()
                    .fill(Color(hex: proposal.statusAccentHex))
                    .frame(width: 8, height: 8)
            }

            VStack(alignment: .leading, spacing: 3) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(proposal.displayTitle)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundColor(.white.opacity(0.78))
                        .lineLimit(1)
                        .truncationMode(.tail)

                    Spacer(minLength: 8)

                    Text(proposal.statusLabel)
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundColor(Color(hex: proposal.statusAccentHex))
                        .padding(.horizontal, 6)
                        .padding(.vertical, 3)
                        .background(Color(hex: proposal.statusAccentHex).opacity(0.10))
                        .clipShape(Capsule())
                }

                Text("\(proposal.typeLabel) · \(proposal.flowLabel) · \(proposal.relativeTimeLabel)")
                    .font(.system(size: 10))
                    .foregroundColor(.white.opacity(0.36))
                    .lineLimit(1)

                if let detail = proposal.detailText {
                    Text(detail)
                        .font(.system(size: 10))
                        .foregroundColor(.white.opacity(0.52))
                        .lineLimit(2)
                }
            }
        }
        .padding(.vertical, 8)
    }

    private func currentInterpretationRow(
        context: SessionContextData?,
        present: PresentData?,
        signals: SignalsData?
    ) -> some View {
        let accent = context?.taskAccentHex ?? present?.taskAccentHex ?? "#7c7c80"
        let taskTitle = currentTaskTitle(context: context, present: present)

        return HStack(alignment: .top, spacing: 10) {
            ZStack {
                Circle()
                    .fill(Color(hex: accent).opacity(0.18))
                    .frame(width: 24, height: 24)
                Image(systemName: "waveform.path.ecg")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundColor(Color(hex: accent))
            }

            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(taskTitle)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundColor(.white.opacity(0.78))
                        .lineLimit(1)

                    Spacer(minLength: 8)

                    Text(context != nil ? "Contexte" : "Live")
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundColor(Color(hex: accent))
                        .padding(.horizontal, 6)
                        .padding(.vertical, 3)
                        .background(Color(hex: accent).opacity(0.10))
                        .clipShape(Capsule())
                }

                Text(currentTaskSummary(context: context, present: present))
                    .font(.system(size: 10))
                    .foregroundColor(.white.opacity(0.52))
                    .lineLimit(3)

                if let signals {
                    Text(signals.taskEvidenceSummary)
                        .font(.system(size: 10))
                        .foregroundColor(.white.opacity(0.36))
                        .lineLimit(3)
                }

                if let fileActivity = signals?.fileActivitySummary {
                    Text("Activité fichiers : \(fileActivity)")
                        .font(.system(size: 10))
                        .foregroundColor(.white.opacity(0.36))
                        .lineLimit(2)
                }
            }
        }
        .padding(.vertical, 8)
    }

    private func currentTaskTitle(context: SessionContextData?, present: PresentData?) -> String {
        if let context, context.taskLabel != "—" {
            return context.taskLabel
        }
        if let present {
            return present.taskLabel == "Général" ? "Contexte faible" : present.taskLabel
        }
        return "Contexte faible"
    }

    private func currentTaskSummary(context: SessionContextData?, present: PresentData?) -> String {
        let project = context?.activeProject ?? present?.activeProject ?? "—"
        let activity = present?.activityLabel ?? context?.activityLabel ?? "—"
        if let context {
            return "Bloc courant sur \(project) · \(context.taskLabel) · \(activity)"
        }
        if let present {
            return "Lecture live sur \(project) · \(present.taskLabel) · \(activity)"
        }
        return "Pas encore assez de contexte local."
    }
}
