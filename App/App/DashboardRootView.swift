import SwiftUI

private let gGreen = "#5DCAA5"
private let gRed = "#ff453a"
private let gOrange = "#EF9F27"
private let gBlue = "#5E9EFF"
private let gGray = "#7c7c80"
private let gPurple = "#8B5CF6"

enum DashboardSection: String, CaseIterable, Identifiable {
    case session = "Session"
    case observation = "Observation"
    case memory = "Mémoire"
    case daydream = "DayDream"
    case events = "Événements"
    case notifications = "Notifications"
    case contextProbes = "Context Probes"
    case mcp = "MCP"
    case system = "Système"

    var id: String { rawValue }

    var icon: String {
        switch self {
        case .session: return "waveform.path.ecg"
        case .observation: return "eye"
        case .memory: return "brain.head.profile"
        case .daydream: return "moon.stars"
        case .events: return "clock.arrow.trianglehead.counterclockwise.rotate.90"
        case .notifications: return "bell"
        case .contextProbes: return "shield.lefthalf.filled"
        case .mcp: return "terminal"
        case .system: return "gearshape.2"
        }
    }

    var accent: String {
        switch self {
        case .session: return gGreen
        case .observation: return gPurple
        case .memory: return gBlue
        case .daydream: return "#8B5CF6"
        case .events: return gPurple
        case .notifications: return gOrange
        case .contextProbes: return gBlue
        case .mcp: return gOrange
        case .system: return gGray
        }
    }
}

struct DashboardRootView: View {
    @ObservedObject var vm: DashboardViewModel
    @State private var selectedSection: DashboardSection = .session
    @State private var expandedJournal: String? = nil
    @State private var showArchivedFacts = false
    @State private var eventFilter = "all"

    var body: some View {
        NavigationSplitView {
            sidebar
                .navigationSplitViewColumnWidth(200)
        } detail: {
            detailView
                .background(.ultraThinMaterial)
        }
        .onAppear {
            if vm.lastRefreshedAt == nil {
                Task { await vm.refresh() }
            }
        }
    }

    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Circle()
                        .fill(Color(hex: daemonStatusColor))
                        .frame(width: 8, height: 8)
                    Text("Pulse")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(.primary)
                }
                Text(vm.ping != nil ? "Daemon actif" : "Daemon injoignable")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 16)
            .padding(.top, 20)
            .padding(.bottom, 16)

            Divider().padding(.horizontal, 8)

            ScrollView {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(DashboardSection.allCases) { section in
                        sidebarItem(section)
                    }
                }
                .padding(.horizontal, 8)
                .padding(.top, 8)
            }

            Spacer()

            Divider().padding(.horizontal, 8)
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(lastRefreshLabel)
                        .font(.system(size: 10))
                        .foregroundStyle(.tertiary)
                }
                Spacer()
                Button {
                    Task { await vm.refresh() }
                } label: {
                    if vm.isLoading {
                        ProgressView().controlSize(.mini)
                    } else {
                        Image(systemName: "arrow.clockwise")
                            .font(.system(size: 11))
                    }
                }
                .buttonStyle(.plain)
                .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
        }
        .background(.regularMaterial)
    }

    private func sidebarItem(_ section: DashboardSection) -> some View {
        Button {
            withAnimation(.easeInOut(duration: 0.15)) {
                selectedSection = section
            }
        } label: {
            HStack(spacing: 10) {
                Image(systemName: section.icon)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(
                        selectedSection == section
                            ? Color(hex: section.accent)
                            : Color.secondary
                    )
                    .frame(width: 18)

                Text(section.rawValue)
                    .font(.system(size: 13, weight: selectedSection == section ? .semibold : .regular))
                    .foregroundStyle(selectedSection == section ? .primary : .secondary)

                Spacer()
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(selectedSection == section
                        ? Color(hex: section.accent).opacity(0.12)
                        : Color.clear)
            )
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private var detailView: some View {
        switch selectedSection {
        case .session:
            sessionView
        case .observation:
            observationView
        case .memory:
            memoryView
        case .daydream:
            daydreamView
        case .events:
            eventsView
        case .notifications:
            notificationsView
        case .contextProbes:
            contextProbesView
        case .mcp:
            mcpView
        case .system:
            systemView
        }
    }

    private var sessionView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                sessionHero

                HStack(alignment: .top, spacing: 16) {
                    todayOverviewCard
                    todayProjectsCard
                }

                HStack(alignment: .top, spacing: 16) {
                    currentContextCard
                    recentSessionsCard
                }

                HStack(alignment: .top, spacing: 16) {
                    taskCard
                    signalsCard
                }

                contextCard
                appsCard
                fileMixCard
            }
            .padding(24)
        }
    }

    private var todayOverviewCard: some View {
        let summary = vm.todaySummary
        let totals = summary?.totals
        let currentWindow = summary?.currentWindow
        let currentBlock = summary?.workBlocks.last

        return GlassCard(accent: gGreen) {
            VStack(alignment: .leading, spacing: 12) {
                cardTitle("Aujourd’hui", icon: "calendar")

                HStack(spacing: 18) {
                    statBadge("Travail", dashboardMinutes(totals?.workedMin), gGreen)
                    statBadge("Commits", dashboardCount(totals?.commitCount), gOrange)
                    statBadge("Blocs", dashboardCount(totals?.windowCount), gGray)
                    statBadge("Projets", dashboardCount(totals?.projectCount), gBlue)
                }

                Divider()

                VStack(alignment: .leading, spacing: 6) {
                    signalRow("Première activité", dashboardAbsoluteTimestamp(summary?.timeline.firstActivityAt))
                    signalRow("Dernière activité", dashboardRelativeTimestamp(summary?.timeline.lastActivityAt))
                    signalRow("Mis à jour", dashboardRelativeTimestamp(summary?.generatedAt))
                }

                if currentBlock != nil || currentWindow != nil {
                    Divider()
                    VStack(alignment: .leading, spacing: 6) {
                        HStack(spacing: 6) {
                            Image(systemName: "waveform.path.ecg")
                                .font(.system(size: 10))
                                .foregroundStyle(.secondary)
                            Text("Bloc de travail courant")
                                .font(.system(size: 10, weight: .semibold))
                                .foregroundStyle(.secondary)
                        }
                        TimelineView(.periodic(from: .now, by: 1)) { _ in
                            Text(sessionDurationLabel(from: currentBlock?.startedAt ?? currentWindow?.startedAt))
                                .font(.system(size: 22, weight: .bold, design: .rounded))
                                .foregroundStyle(.primary)
                        }
                        signalRow("Projet", currentBlock?.project ?? currentWindow?.project ?? "—")
                        signalRow("Tâche", currentBlock?.taskLabel ?? currentWindow?.taskLabel ?? "—")
                        signalRow("Activité", currentWindow?.activityLabel ?? "—")
                        signalRow("Commits", "\(currentWindow?.commitCount ?? totals?.commitCount ?? 0)")
                    }
                }
            }
        }
        .frame(maxWidth: .infinity)
    }

    private var todayProjectsCard: some View {
        let projects = vm.todaySummary?.projects ?? []

        return GlassCard(accent: gBlue) {
            VStack(alignment: .leading, spacing: 12) {
                cardTitle("Projets du jour", icon: "square.grid.2x2")

                if projects.isEmpty {
                    emptyState("Aucune fenêtre de travail persistée aujourd’hui")
                } else {
                    VStack(spacing: 0) {
                        ForEach(projects.prefix(5)) { project in
                            HStack(alignment: .top, spacing: 10) {
                                Circle()
                                    .fill(Color(hex: gBlue).opacity(0.65))
                                    .frame(width: 8, height: 8)
                                    .padding(.top, 5)

                                VStack(alignment: .leading, spacing: 4) {
                                    HStack {
                                        Text(project.name)
                                            .font(.system(size: 12, weight: .medium))
                                            .foregroundStyle(.primary)
                                        Spacer()
                                        Text(dashboardMinutes(project.workedMin))
                                            .font(.system(size: 11, weight: .semibold))
                                            .foregroundStyle(.secondary)
                                    }
                                    Text("\(dashboardMinutes(project.workedMin)) travaillées · \(project.commitCount) commit(s)")
                                        .font(.system(size: 10))
                                        .foregroundStyle(.secondary)
                                    if !project.topTasks.isEmpty {
                                        Text(project.topTasks.map(todayTaskLabel).joined(separator: " · "))
                                            .font(.system(size: 10))
                                            .foregroundStyle(.tertiary)
                                    }
                                }
                            }
                            .padding(.vertical, 8)

                            if project.id != projects.prefix(5).last?.id {
                                Divider().padding(.leading, 18)
                            }
                        }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity)
    }

    private var sessionHero: some View {
        let fsm = vm.state?.sessionFsm
        let present = vm.state?.present
        let stateColor = Color(hex: fsm?.stateColor ?? gGray)

        return GlassCard(accent: fsm?.stateColor ?? gGray) {
            HStack(alignment: .top, spacing: 24) {
                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 8) {
                        Circle().fill(stateColor).frame(width: 10, height: 10)
                        Text("Maintenant")
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(.primary)
                    }
                    Text(liveTaskTitle(present))
                        .font(.system(size: 24, weight: .bold, design: .rounded))
                        .foregroundStyle(Color(hex: present?.taskAccentHex ?? gGray))
                    Text("\(present?.activeProject ?? "Projet non identifié") · \(present?.activityLabel ?? "—")")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }

                Spacer()

                VStack(alignment: .trailing, spacing: 4) {
                    metaLabel("État live")
                    Text(fsm?.stateLabel ?? "—")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(.primary)
                    metaLabel("Dernier signal").padding(.top, 8)
                    Text(dashboardRelativeTimestamp(fsm?.lastMeaningfulActivityAt))
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(.secondary)
                    if let locked = fsm?.lastScreenLockedAt {
                        metaLabel("Dernier verrou").padding(.top, 8)
                        Text(dashboardRelativeTimestamp(locked))
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private var currentContextCard: some View {
        let context = vm.state?.currentContext
        let present = vm.state?.present
        let liveSignals = vm.state?.signals
        let weakContext = isWeakProductTask(context, present)
        let accent = context?.taskAccentHex ?? present?.taskAccentHex ?? gGray

        return GlassCard(accent: context?.boundaryColor ?? gBlue) {
            VStack(alignment: .leading, spacing: 12) {
                cardTitle("Contexte actuel", icon: "timeline.selection")

                if let context {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(productTaskTitle(context, present))
                            .font(.system(size: weakContext ? 18 : 22, weight: weakContext ? .semibold : .bold, design: .rounded))
                            .foregroundStyle(weakContext ? .secondary : Color(hex: accent))
                        HStack(spacing: 8) {
                            evidenceBadge(liveSignals?.taskEvidenceLabel ?? "Faible", weak: weakContext)
                            Text(dashboardRelativeTimestamp(present?.updatedAt))
                                .font(.system(size: 11, weight: .medium))
                                .foregroundStyle(.secondary)
                        }
                    }

                    Divider()

                    VStack(alignment: .leading, spacing: 6) {
                        HStack(spacing: 6) {
                            Image(systemName: "shippingbox")
                                .font(.system(size: 10))
                                .foregroundStyle(.secondary)
                            Text("Interprétation")
                                .font(.system(size: 10, weight: .semibold))
                                .foregroundStyle(.secondary)
                        }

                        signalRow("Projet", context.activeProject ?? present?.activeProject ?? "—")
                        signalRow("Tâche", context.taskLabel)
                        signalRow("Activité", context.activityLabel)
                        signalRow("Focus", focusLabel(present?.focusLevel))
                        signalRow("Confiance", dashboardPercent(context.taskConfidence))
                        if context.boundaryReason == "idle_timeout" {
                            signalRow("Fin", "Estimée par inactivité")
                        }
                    }

                    if let liveSignals {
                        Divider()
                        Text(liveSignals.taskEvidenceSummary)
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                } else {
                    emptyState("Aucun contexte actif")
                }
            }
        }
        .frame(maxWidth: .infinity)
    }

    private var recentSessionsCard: some View {
        let history = (vm.state?.recentSessions ?? []).filter { !$0.isActive }

        return GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                cardTitle("Sessions récentes", icon: "clock")

                if history.isEmpty {
                    emptyState("Aucune session close")
                } else {
                    VStack(spacing: 0) {
                        ForEach(history.prefix(5)) { session in
                            HStack(alignment: .top, spacing: 10) {
                                Circle()
                                    .fill(Color(hex: session.boundaryColor))
                                    .frame(width: 8, height: 8)
                                    .padding(.top, 5)

                                VStack(alignment: .leading, spacing: 3) {
                                    HStack {
                                        Text(session.boundaryLabel)
                                            .font(.system(size: 12, weight: .medium))
                                            .foregroundStyle(.primary)
                                        Spacer()
                                        Text(sessionDurationCompact(session))
                                            .font(.system(size: 11, weight: .semibold))
                                            .foregroundStyle(.secondary)
                                    }
                                    Text("\(dashboardAbsoluteTimestamp(session.startedAt)) → \(dashboardAbsoluteTimestamp(session.endedAt))")
                                        .font(.system(size: 10))
                                        .foregroundStyle(.tertiary)
                                    Text("\(session.taskLabel) · \(session.activityLabel) · \(dashboardPercent(session.taskConfidence))")
                                        .font(.system(size: 10))
                                        .foregroundStyle(Color(hex: session.taskAccentHex))
                                }
                            }
                            .padding(.vertical, 8)

                            if session.id != history.prefix(5).last?.id {
                                Divider().padding(.leading, 18)
                            }
                        }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity)
    }

    private var taskCard: some View {
        let context = vm.state?.currentContext
        let present = vm.state?.present
        let signals = vm.state?.signals
        let confidence = context?.taskConfidence ?? signals?.taskConfidence ?? 0
        let weakTask = isWeakProductTask(context, present)
        let accent = context?.taskAccentHex ?? present?.taskAccentHex ?? gGray

        return GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                cardTitle("Bloc de travail", icon: "target")

                Text(productTaskTitle(context, present))
                    .font(.system(size: weakTask ? 18 : 22, weight: weakTask ? .semibold : .bold, design: .rounded))
                    .foregroundStyle(weakTask ? .secondary : Color(hex: accent))

                if let signals {
                    VStack(alignment: .leading, spacing: 6) {
                        evidenceBadge(signals.taskEvidenceLabel, weak: weakTask)
                        Text(signals.taskEvidenceSummary)
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }

                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        metaLabel("Confiance")
                        Spacer()
                        Text(dashboardPercent(context?.taskConfidence ?? signals?.taskConfidence))
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(.secondary)
                    }
                    ProgressView(value: confidence)
                        .tint(Color(hex: accent))
                }

                HStack(spacing: 6) {
                    Image(systemName: "bolt.fill")
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                    Text((present?.activityLabel ?? context?.activityLabel) ?? "—")
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                }
            }
        }
        .frame(maxWidth: .infinity)
    }

    private var signalsCard: some View {
        let signals = vm.state?.signals
        let friction = signals?.frictionScore ?? 0

        return GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                cardTitle("Signaux support", icon: "waveform")

                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        metaLabel("Friction")
                        Spacer()
                        Text(dashboardScore(signals?.frictionScore))
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(frictionColor(friction))
                    }
                    ProgressView(value: friction)
                        .tint(frictionColor(friction))
                }

                Divider()

                VStack(spacing: 6) {
                    signalRow("Focus", focusLabel(signals?.focusLevel))
                    signalRow("Mode", fileModeLabel(signals?.dominantFileMode))
                    signalRow("Pattern", patternLabel(signals?.workPatternCandidate))
                    signalRow("Clipboard", clipboardLabel(signals?.clipboardContext))
                    if let ratio = signals?.renameDeleteRatio10m, ratio > 0 {
                        signalRow("Ratio Δ", String(format: "%.0f%%", ratio * 100))
                    }
                }
            }
        }
        .frame(maxWidth: .infinity)
    }

    private var contextCard: some View {
        let state = vm.state
        return GlassCard {
            VStack(alignment: .leading, spacing: 10) {
                cardTitle("Contexte actif", icon: "scope")
                HStack(spacing: 16) {
                    contextItem("App", state?.activeApp ?? "—")
                    contextItem(
                        "Projet",
                        state?.currentContext?.activeProject
                            ?? state?.present?.activeProject
                            ?? state?.activeProject
                            ?? "—"
                    )
                    contextItem(
                        "Fichier",
                        (state?.present?.activeFile ?? state?.activeFile).map { URL(fileURLWithPath: $0).lastPathComponent } ?? "—",
                        monospace: true
                    )
                }
                if let lastSession = state?.signals?.lastSessionContext, !lastSession.isEmpty {
                    Divider()
                    HStack(alignment: .top, spacing: 6) {
                        Image(systemName: "arrow.triangle.2.circlepath")
                            .font(.system(size: 10))
                            .foregroundStyle(.secondary)
                            .padding(.top, 2)
                        Text(lastSession)
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                }
            }
        }
    }

    private var appsCard: some View {
        let apps = vm.state?.signals?.recentApps ?? []
        return GlassCard {
            VStack(alignment: .leading, spacing: 10) {
                cardTitle("Apps récentes", icon: "square.stack.3d.up")
                if apps.isEmpty {
                    emptyState("Aucune app récente")
                } else {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(Array(apps.enumerated()), id: \.offset) { i, app in
                                Text(app)
                                    .font(.system(size: 12, weight: .medium))
                                    .foregroundStyle(i == apps.count - 1 ? Color(hex: gGreen) : .primary)
                                    .padding(.horizontal, 12)
                                    .padding(.vertical, 7)
                                    .background(.ultraThinMaterial)
                                    .clipShape(Capsule())
                                    .overlay(
                                        Capsule().stroke(
                                            i == apps.count - 1
                                                ? Color(hex: gGreen).opacity(0.4)
                                                : Color.white.opacity(0.08),
                                            lineWidth: 1
                                        )
                                    )
                            }
                        }
                    }
                }
            }
        }
    }

    private var fileMixCard: some View {
        let mix = vm.state?.signals?.fileTypeMix10m ?? [:]
        let total = mix.values.reduce(0, +)
        let types: [(String, String, String)] = [
            ("source", "Code source", gGreen),
            ("test", "Tests", gBlue),
            ("config", "Config", gOrange),
            ("docs", "Docs", gPurple),
        ]
        return GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    cardTitle("File type mix (10m)", icon: "doc.on.doc")
                    Spacer()
                    if total > 0 {
                        Text("\(total) fichier\(total > 1 ? "s" : "")")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                    }
                }
                if total == 0 {
                    emptyState("Aucune activité fichier récente")
                } else {
                    HStack(spacing: 12) {
                        ForEach(types, id: \.0) { key, label, color in
                            if let count = mix[key], count > 0 {
                                VStack(spacing: 4) {
                                    Text("\(count)")
                                        .font(.system(size: 20, weight: .bold, design: .rounded))
                                        .foregroundStyle(Color(hex: color))
                                    Text(label)
                                        .font(.system(size: 10))
                                        .foregroundStyle(.secondary)
                                }
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 10)
                                .background(Color(hex: color).opacity(0.08))
                                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                            }
                        }
                    }
                }
            }
        }
    }

    private var observationView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                // Titres de fenêtres
                GlassCard(accent: gPurple) {
                    VStack(alignment: .leading, spacing: 12) {
                        cardTitle("Titres de fenêtres capturs", icon: "eye")
                        let titles = vm.observation?.windowTitles ?? []
                        if titles.isEmpty {
                            emptyState("Aucun titre capté — navigation en cours ?")
                        } else {
                            VStack(spacing: 0) {
                                ForEach(titles.prefix(30)) { item in
                                    HStack(alignment: .top, spacing: 12) {
                                        VStack(alignment: .leading, spacing: 3) {
                                            Text(item.title)
                                                .font(.system(size: 12, weight: .medium))
                                                .foregroundStyle(.primary)
                                                .lineLimit(2)
                                            Text(item.app)
                                                .font(.system(size: 10))
                                                .foregroundStyle(.secondary)
                                        }
                                        Spacer()
                                        Text(dashboardAbsoluteTimestamp(item.timestamp))
                                            .font(.system(size: 10))
                                            .foregroundStyle(.tertiary)
                                    }
                                    .padding(.vertical, 8)
                                    if item.id != titles.prefix(30).last?.id {
                                        Divider()
                                    }
                                }
                            }
                        }
                    }
                }

                // Commandes terminal
                GlassCard {
                    VStack(alignment: .leading, spacing: 12) {
                        cardTitle("Commandes terminal récentes", icon: "terminal")
                        let commands = vm.observation?.terminalCommands ?? []
                        if commands.isEmpty {
                            emptyState("Aucune commande récente")
                        } else {
                            VStack(spacing: 0) {
                                ForEach(commands) { cmd in
                                    HStack(alignment: .top, spacing: 10) {
                                        Circle()
                                            .fill(cmd.success == true ? Color(hex: gGreen) : cmd.success == false ? Color(hex: gRed) : Color(hex: gGray))
                                            .frame(width: 7, height: 7)
                                            .padding(.top, 5)
                                        VStack(alignment: .leading, spacing: 3) {
                                            Text(cmd.command)
                                                .font(.system(size: 11, design: .monospaced))
                                                .foregroundStyle(.primary)
                                                .lineLimit(1)
                                                .truncationMode(.middle)
                                            if !cmd.summary.isEmpty {
                                                Text(cmd.summary)
                                                    .font(.system(size: 10))
                                                    .foregroundStyle(.secondary)
                                            }
                                        }
                                        Spacer()
                                        Text(dashboardAbsoluteTimestamp(cmd.timestamp))
                                            .font(.system(size: 10))
                                            .foregroundStyle(.tertiary)
                                    }
                                    .padding(.vertical, 8)
                                    if cmd.id != commands.last?.id {
                                        Divider().padding(.leading, 17)
                                    }
                                }
                            }
                        }
                    }
                }
            }
            .padding(24)
        }
    }

    private var daydreamView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if let status = vm.daydreamStatus {
                    GlassCard(accent: "#8B5CF6") {
                        VStack(alignment: .leading, spacing: 8) {
                            HStack {
                                Label(daydreamStatusTitle(status), systemImage: "moon.stars")
                                    .font(.system(size: 13, weight: .semibold))
                                    .foregroundStyle(Color(hex: "#8B5CF6"))
                                Spacer()
                                if let targetDate = status.targetDate, !targetDate.isEmpty {
                                    Text(targetDate)
                                        .font(.system(size: 11, weight: .medium))
                                        .foregroundStyle(.secondary)
                                }
                            }
                            if let detail = daydreamStatusDetail(status) {
                                Text(detail)
                                    .font(.system(size: 11))
                                    .foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                            if let error = status.lastError, !error.isEmpty {
                                Text(error)
                                    .font(.system(size: 10))
                                    .foregroundStyle(.red.opacity(0.8))
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                }
                if vm.daydreams.isEmpty {
                    VStack(spacing: 12) {
                        Image(systemName: "moon.stars")
                            .font(.system(size: 32, weight: .light))
                            .foregroundStyle(.tertiary)
                        Text("Aucun DayDream généré")
                            .font(.system(size: 14, weight: .medium))
                            .foregroundStyle(.secondary)
                        Text("DayDream se déclenche automatiquement au premier verrouillage après 23h59.")
                            .font(.system(size: 11))
                            .foregroundStyle(.tertiary)
                            .multilineTextAlignment(.center)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.top, 80)
                } else {
                    ForEach(vm.daydreams) { dream in
                        GlassCard(accent: "#8B5CF6") {
                            VStack(alignment: .leading, spacing: 10) {
                                HStack {
                                    Label(journalDateLabel(dream.date), systemImage: "moon.stars")
                                        .font(.system(size: 13, weight: .semibold))
                                        .foregroundStyle(Color(hex: "#8B5CF6"))
                                    Spacer()
                                }
                                Divider()
                                Text(dream.content)
                                    .font(.system(size: 11))
                                    .foregroundStyle(.primary)
                                    .textSelection(.enabled)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                }
            }
            .padding(24)
        }
    }

    private func daydreamStatusTitle(_ status: DaydreamStatus) -> String {
        switch status.status {
        case "pending": return "DayDream en attente"
        case "running": return "DayDream en cours"
        case "generated": return "DayDream généré"
        case "skipped": return "DayDream ignoré"
        case "failed": return "DayDream en échec"
        default: return "DayDream inactif"
        }
    }

    private func daydreamStatusDetail(_ status: DaydreamStatus) -> String? {
        switch status.lastReason {
        case "awaiting_screen_lock":
            return "Le résumé nocturne attend le prochain verrouillage d’écran après 23h59."
        case "running":
            return "Le résumé de la journée est en cours de génération."
        case "generated":
            return "Le résumé a été généré avec succès."
        case "already_exists":
            return "Le fichier DayDream existait déjà; aucune régénération n’a été faite."
        case "already_completed_for_date":
            return "Cette journée a déjà été consolidée."
        case "no_journal_entries":
            return "Aucune entrée de journal exploitable n’a été trouvée pour cette date."
        case "unexpected_error":
            return "La génération a échoué. Voir l’erreur ci-dessous."
        default:
            return nil
        }
    }

    private var memoryView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                GlassCard(accent: gBlue) {
                    VStack(alignment: .leading, spacing: 10) {
                        cardTitle("Profil injecté au LLM", icon: "brain.head.profile")
                        if let profile = vm.factsProfile?.profile, !profile.isEmpty {
                            Text(profile)
                                .font(.system(size: 12))
                                .foregroundStyle(.primary)
                                .textSelection(.enabled)
                                .fixedSize(horizontal: false, vertical: true)
                        } else {
                            emptyState("Aucun profil consolidé")
                        }
                    }
                }

                GlassCard {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            cardTitle("Faits consolidés", icon: "checkmark.seal")
                            Spacer()
                            Toggle("Archivés (\(vm.factsStats?.archived ?? 0))",
                                   isOn: $showArchivedFacts)
                                .toggleStyle(.switch)
                                .font(.system(size: 11))
                        }

                        HStack(spacing: 16) {
                            statBadge("Actifs", "\(vm.factsStats?.active ?? 0)", gGreen)
                            statBadge("Archivés", "\(vm.factsStats?.archived ?? 0)", gOrange)
                        }

                        Divider()

                        let factsToShow = showArchivedFacts
                            ? (vm.archivedFacts?.facts ?? [])
                            : (vm.facts?.facts ?? [])
                        if factsToShow.isEmpty {
                            emptyState(showArchivedFacts ? "Aucun fait archivé" : "Aucun fait actif")
                        } else {
                            VStack(spacing: 0) {
                                ForEach(factsToShow) { fact in
                                    factRow(fact)
                                    if fact.id != factsToShow.last?.id {
                                        Divider().padding(.leading, 18)
                                    }
                                }
                            }
                        }
                    }
                }

                GlassCard {
                    VStack(alignment: .leading, spacing: 10) {
                        cardTitle("Mémoire figée", icon: "memorychip")
                        HStack(spacing: 6) {
                            Image(systemName: "clock")
                                .font(.system(size: 11))
                                .foregroundStyle(.secondary)
                            Text("Gelée à \(dashboardAbsoluteTimestamp(vm.memory?.frozenAt))")
                                .font(.system(size: 12))
                                .foregroundStyle(.secondary)
                        }
                        Text("Consolidée depuis les faits et journaux de session, injectée dans chaque échange LLM.")
                            .font(.system(size: 11))
                            .foregroundStyle(.tertiary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }

                GlassCard {
                    VStack(alignment: .leading, spacing: 12) {
                        cardTitle("Journaux de session", icon: "doc.text")
                        let journals = vm.sessionJournals?.sessions ?? []
                        if journals.isEmpty {
                            emptyState("Aucun journal disponible")
                        } else {
                            VStack(spacing: 6) {
                                ForEach(journals) { journal in
                                    journalAccordion(journal)
                                }
                            }
                        }
                    }
                }
            }
            .padding(24)
        }
    }

    private var notificationsView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                if vm.feedHistory.isEmpty {
                    VStack(spacing: 12) {
                        Image(systemName: "bell.slash")
                            .font(.system(size: 28, weight: .light))
                            .foregroundStyle(.tertiary)
                        Text("Aucune notification")
                            .font(.system(size: 13))
                            .foregroundStyle(.secondary)
                        Text("Les résultats de commandes terminal et les commits capturés apparaitront ici.")
                            .font(.system(size: 11))
                            .foregroundStyle(.tertiary)
                            .multilineTextAlignment(.center)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.top, 60)
                } else {
                    GlassCard {
                        VStack(spacing: 0) {
                            ForEach(vm.feedHistory) { event in
                                HStack(spacing: 14) {
                                    ZStack {
                                        Circle()
                                            .fill(Color(hex: event.accentHex).opacity(0.15))
                                            .frame(width: 30, height: 30)
                                        Image(systemName: event.icon)
                                            .font(.system(size: 12, weight: .medium))
                                            .foregroundStyle(Color(hex: event.accentHex))
                                    }

                                    VStack(alignment: .leading, spacing: 3) {
                                        Text(event.label)
                                            .font(.system(size: 13, weight: .medium))
                                            .foregroundStyle(.primary)
                                            .lineLimit(1)
                                        if let cmd = event.command, !cmd.isEmpty {
                                            Text(cmd)
                                                .font(.system(size: 10, design: .monospaced))
                                                .foregroundStyle(.tertiary)
                                                .lineLimit(1)
                                                .truncationMode(.middle)
                                        }
                                    }

                                    Spacer()

                                    Text(dashboardAbsoluteTimestamp(event.timestamp))
                                        .font(.system(size: 11))
                                        .foregroundStyle(.tertiary)
                                }
                                .padding(.vertical, 10)

                                if event.id != vm.feedHistory.last?.id {
                                    Divider().padding(.leading, 44)
                                }
                            }
                        }
                    }
                }
            }
            .padding(24)
        }
    }

    private var eventsView: some View {
        VStack(spacing: 0) {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    filterChip("Tous", tag: "all")
                    ForEach(Array(Set(vm.events.map(\.type))).sorted(), id: \.self) { type in
                        filterChip(
                            InsightEvent(type: type, timestamp: "", keyValue: nil).label,
                            tag: type
                        )
                    }
                }
                .padding(.horizontal, 24)
                .padding(.vertical, 12)
            }
            .background(.ultraThinMaterial)

            Divider()

            ScrollView {
                LazyVStack(spacing: 0) {
                    ForEach(filteredEvents) { event in
                        eventRow(event)
                        Divider().padding(.leading, 54)
                    }
                }
                .padding(.vertical, 8)
            }
        }
    }

    private var contextProbesView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                GlassCard(accent: gBlue) {
                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            cardTitle("Context Probes", icon: "shield.lefthalf.filled")
                            Spacer()
                            statBadge("Demandes", "\(vm.contextProbeRequests.count)", gBlue)
                        }
                        Text("Demandes de contexte contrôlées par validation humaine. Les metadata brutes et les valeurs capturées ne sont pas affichées ici.")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }

                if vm.contextProbeRequests.isEmpty {
                    GlassCard {
                        VStack(spacing: 12) {
                            Image(systemName: "shield.slash")
                                .font(.system(size: 28, weight: .light))
                                .foregroundStyle(.tertiary)
                            Text("Aucune demande de contexte")
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(.secondary)
                            Text("Pulse n'a rien demandé à lire pour l'instant.")
                                .font(.system(size: 11))
                                .foregroundStyle(.tertiary)
                                .multilineTextAlignment(.center)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 36)
                    }
                } else {
                    ForEach(sortedContextProbeRequests) { request in
                        GlassCard(accent: request.statusAccentHex) {
                            contextProbeRequestCard(request)
                        }
                    }
                }
            }
            .padding(24)
        }
    }

    private var sortedContextProbeRequests: [ContextProbeRequestPayload] {
        vm.contextProbeRequests.sorted { left, right in
            if left.status == "pending" && right.status != "pending" { return true }
            if left.status != "pending" && right.status == "pending" { return false }
            if left.status == "approved" && right.status != "approved" { return true }
            if left.status != "approved" && right.status == "approved" { return false }
            return left.createdAt > right.createdAt
        }
    }

    private func contextProbeRequestCard(_ request: ContextProbeRequestPayload) -> some View {
        let debug = vm.debugForContextProbeRequest(request)
        let risk = debug?.labels.risk ?? "Unknown"
        let riskColor = Color(hex: debug?.labels.riskAccentHex ?? gGray)
        let statusColor = Color(hex: request.statusAccentHex)

        return VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 8) {
                        Text(request.kindLabel)
                            .font(.system(size: 14, weight: .semibold))
                            .foregroundStyle(.primary)
                        Text(request.statusLabel)
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(statusColor)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 4)
                            .background(statusColor.opacity(0.12))
                            .clipShape(Capsule())
                    }
                    Text(request.reason)
                        .font(.system(size: 12))
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer()

                Text(risk)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(riskColor)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(riskColor.opacity(0.12))
                    .clipShape(Capsule())
            }

            HStack(spacing: 8) {
                contextProbeMetaPill("Consentement", request.policy.consentLabel)
                contextProbeMetaPill("Privacy", request.policy.privacyLabel)
                contextProbeMetaPill("Rétention", request.policy.retentionLabel)
            }

            if !request.metadataKeys.isEmpty {
                Divider()
                HStack(alignment: .top, spacing: 8) {
                    Image(systemName: "key.horizontal")
                        .font(.system(size: 10, weight: .medium))
                        .foregroundStyle(.tertiary)
                        .padding(.top, 2)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Metadata keys")
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundStyle(.tertiary)
                        Text(request.metadataKeys.joined(separator: " · "))
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                }
            }

            if let result = vm.resultForContextProbeRequest(request) {
                Divider()
                contextProbeResultBlock(result)
            }

            HStack(spacing: 8) {
                if request.canApproveOrRefuse {
                    Button {
                        Task { await vm.approveContextProbeRequest(request) }
                    } label: {
                        Label("Approuver", systemImage: "checkmark")
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(Color(hex: gGreen))

                    Button(role: .destructive) {
                        Task { await vm.refuseContextProbeRequest(request) }
                    } label: {
                        Label("Refuser", systemImage: "xmark")
                    }
                    .buttonStyle(.bordered)
                }

                if request.canExecute {
                    Button {
                        Task { await vm.executeContextProbeRequest(request) }
                    } label: {
                        Label("Exécuter", systemImage: "play.fill")
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(Color(hex: gBlue))
                }

                Spacer()

                if let decision = request.decisionReason, !decision.isEmpty {
                    Text(decision)
                        .font(.system(size: 10))
                        .foregroundStyle(.tertiary)
                        .lineLimit(1)
                }
            }
        }
    }

    private func contextProbeResultBlock(_ result: ContextProbeResultPayload) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Image(systemName: result.captured ? "checkmark.shield" : "xmark.shield")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(result.captured ? Color(hex: gGreen) : Color(hex: gOrange))
                Text(result.captured ? "Résultat exécuté" : "Probe bloqué")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(.secondary)
                Spacer()
                Text(result.kind)
                    .font(.system(size: 9, design: .monospaced))
                    .foregroundStyle(.tertiary)
            }

            if result.kind == "window_title" {
                contextProbeWindowTitleResult(result)
            } else {
                contextProbeGenericResult(result)
            }
        }
        .padding(10)
        .background(Color.white.opacity(0.035))
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }

    private func contextProbeWindowTitleResult(_ result: ContextProbeResultPayload) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            if let value = result.data["redacted_value"]?.displayValue, !value.isEmpty {
                Text(value)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(.primary)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }

            HStack(spacing: 6) {
                if let flags = result.data["redaction_flags"]?.stringArrayValue, !flags.isEmpty {
                    ForEach(flags, id: \.self) { flag in
                        Text(flag)
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundStyle(Color(hex: gOrange))
                            .padding(.horizontal, 7)
                            .padding(.vertical, 3)
                            .background(Color(hex: gOrange).opacity(0.12))
                            .clipShape(Capsule())
                    }
                } else {
                    Text("no redaction flag")
                        .font(.system(size: 9))
                        .foregroundStyle(.tertiary)
                }
                Spacer()
            }

            HStack(spacing: 12) {
                Text("Original: \(result.data["original_length"]?.displayValue ?? "—")")
                Text("Redacted: \(result.data["redacted_length"]?.displayValue ?? "—")")
                Text("Was redacted: \(result.data["was_redacted"]?.displayValue ?? "—")")
            }
            .font(.system(size: 9, design: .monospaced))
            .foregroundStyle(.tertiary)
        }
    }

    private func contextProbeGenericResult(_ result: ContextProbeResultPayload) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            ForEach(result.data.keys.sorted(), id: \.self) { key in
                HStack(alignment: .top, spacing: 8) {
                    Text(key)
                        .font(.system(size: 9, weight: .semibold, design: .monospaced))
                        .foregroundStyle(.tertiary)
                        .frame(width: 110, alignment: .leading)
                    Text(result.data[key]?.displayValue ?? "—")
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                    Spacer()
                }
            }
        }
    }

    private func contextProbeMetaPill(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label)
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(.tertiary)
            Text(value)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(.primary)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(Color.white.opacity(0.035))
        .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
    }

    private var mcpView: some View {
        ScrollView {
            VStack(spacing: 12) {
                if vm.proposals.isEmpty {
                    emptyState("Aucune proposition récente")
                        .padding(24)
                } else {
                    ForEach(vm.proposals) { proposal in
                        GlassCard(accent: proposal.statusAccentHex) {
                            mcpProposalCard(proposal)
                        }
                    }
                }
            }
            .padding(24)
        }
    }

    private var systemView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                HStack(alignment: .top, spacing: 16) {
                    GlassCard(accent: daemonStatusColor) {
                        VStack(alignment: .leading, spacing: 10) {
                            cardTitle("Daemon", icon: "server.rack")
                            statBadge("État", daemonStatusLabel, daemonStatusColor)
                            signalRow("Port", vm.daemonPort.map(String.init) ?? "—")
                            signalRow("Version", vm.ping?.version ?? "—")
                            signalRow("Endpoint", vm.daemonBaseURL)
                        }
                    }
                    .frame(maxWidth: .infinity)

                    GlassCard(accent: vm.llmModels?.llmReady == true ? gGreen : gOrange) {
                        VStack(alignment: .leading, spacing: 10) {
                            cardTitle("LLM", icon: "cpu")
                            statBadge("Provider", vm.llmModels?.provider ?? "—", gBlue)
                            signalRow("Modèle", vm.llmModels?.selectedModel ?? "—")
                            signalRow("Ollama", dashboardBoolLabel(vm.llmModels?.ollamaOnline))
                            signalRow("Prêt", dashboardBoolLabel(vm.llmModels?.llmReady))
                        }
                    }
                    .frame(maxWidth: .infinity)
                }

                GlassCard {
                    VStack(alignment: .leading, spacing: 10) {
                        cardTitle("Cortex Scoring", icon: "chart.bar.doc.horizontal")
                        HStack(spacing: 16) {
                            statBadge(
                                "Tree-sitter",
                                dashboardBoolLabel(vm.scoringStatus?.treesitterCore),
                                vm.scoringStatus?.treesitterCore == true ? gGreen : gGray
                            )
                            statBadge(
                                "Python AST",
                                dashboardBoolLabel(vm.scoringStatus?.pythonAst),
                                vm.scoringStatus?.pythonAst == true ? gGreen : gGray
                            )
                        }
                        let languages = (vm.scoringStatus?.languages ?? [:]).keys.sorted()
                        if !languages.isEmpty {
                            Divider()
                            LazyVGrid(
                                columns: Array(repeating: GridItem(.flexible()), count: 3),
                                spacing: 8
                            ) {
                                ForEach(languages, id: \.self) { lang in
                                    let avail = vm.scoringStatus?.languages?[lang]?.available ?? false
                                    HStack(spacing: 4) {
                                        Circle()
                                            .fill(avail ? Color(hex: gGreen) : Color(hex: gGray))
                                            .frame(width: 6, height: 6)
                                        Text(lang)
                                            .font(.system(size: 11, design: .monospaced))
                                            .foregroundStyle(.primary)
                                    }
                                }
                            }
                        }
                    }
                }
            }
            .padding(24)
        }
    }

    private func cardTitle(_ title: String, icon: String) -> some View {
        Label(title, systemImage: icon)
            .font(.system(size: 11, weight: .semibold))
            .foregroundStyle(.secondary)
            .textCase(.uppercase)
            .tracking(0.4)
    }

    private func metaLabel(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 10, weight: .semibold))
            .foregroundStyle(.tertiary)
            .tracking(0.3)
    }

    private func statBadge(_ label: String, _ value: String, _ colorHex: String = gGray) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label)
                .font(.system(size: 10))
                .foregroundStyle(.tertiary)
            Text(value)
                .font(.system(size: 14, weight: .semibold, design: .rounded))
                .foregroundStyle(Color(hex: colorHex))
        }
    }

    private func signalRow(_ label: String, _ value: String) -> some View {
        HStack {
            Text(label)
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
            Spacer()
            Text(value)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(.primary)
                .lineLimit(1)
                .truncationMode(.middle)
        }
    }

    private func contextItem(_ label: String, _ value: String, monospace: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label)
                .font(.system(size: 10))
                .foregroundStyle(.tertiary)
            Text(value)
                .font(.system(size: 12, weight: .medium, design: monospace ? .monospaced : .default))
                .foregroundStyle(.primary)
                .lineLimit(1)
                .truncationMode(.middle)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func emptyState(_ text: String) -> some View {
        HStack {
            Spacer()
            Text(text)
                .font(.system(size: 12))
                .foregroundStyle(.tertiary)
            Spacer()
        }
        .padding(.vertical, 12)
    }

    private func evidenceBadge(_ label: String, weak: Bool) -> some View {
        Text(label)
            .font(.system(size: 10, weight: .semibold))
            .foregroundStyle(weak ? .secondary : Color(hex: gBlue))
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(
                Capsule()
                    .fill(weak ? Color.white.opacity(0.06) : Color(hex: gBlue).opacity(0.12))
            )
    }

    private func productTaskTitle(_ context: SessionContextData?, _ present: PresentData?) -> String {
        if let context, context.taskLabel != "Général", context.taskLabel != "—" {
            return context.taskLabel
        }
        return liveTaskTitle(present)
    }

    private func liveTaskTitle(_ present: PresentData?) -> String {
        guard let present else { return "Contexte faible" }
        return present.taskLabel == "Général" ? "Contexte faible" : present.taskLabel
    }

    private func isWeakProductTask(_ context: SessionContextData?, _ present: PresentData?) -> Bool {
        if let context {
            if context.taskLabel == "Général" || context.taskLabel == "—" { return true }
            return (context.taskConfidence ?? 0) < 0.45
        }
        guard let present else { return true }
        if present.taskLabel == "Général" { return true }
        return false
    }

    private func isWeakLiveTask(_ signals: SignalsData?) -> Bool {
        guard let signals else { return true }
        if signals.taskLabel == "Général" { return true }
        return (signals.taskConfidence ?? 0) < 0.45
    }

    private func filterChip(_ label: String, tag: String) -> some View {
        Button { eventFilter = tag } label: {
            Text(label)
                .font(.system(size: 11, weight: eventFilter == tag ? .semibold : .regular))
                .foregroundStyle(eventFilter == tag ? .primary : .secondary)
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                .background(
                    eventFilter == tag
                        ? AnyShapeStyle(.ultraThinMaterial)
                        : AnyShapeStyle(Color.clear)
                )
                .clipShape(Capsule())
                .overlay(
                    Capsule().stroke(
                        eventFilter == tag
                            ? Color.white.opacity(0.15)
                            : Color.clear,
                        lineWidth: 1
                    )
                )
        }
        .buttonStyle(.plain)
    }

    private func factRow(_ fact: FactRecord) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Circle()
                .fill(Color(hex: fact.confidenceColor))
                .frame(width: 8, height: 8)
                .padding(.top, 5)

            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline) {
                    Text(fact.value)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(.primary)
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer()
                    Text(fact.confidenceLabel)
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundStyle(Color(hex: fact.confidenceColor))
                        .padding(.horizontal, 6)
                        .padding(.vertical, 3)
                        .background(Color(hex: fact.confidenceColor).opacity(0.12))
                        .clipShape(Capsule())
                }
                HStack(spacing: 6) {
                    Text(fact.key)
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(.tertiary)
                    if let cat = fact.category {
                        Text("·").foregroundStyle(.tertiary)
                        Text(cat).font(.system(size: 10)).foregroundStyle(.tertiary)
                    }
                    Text("·").foregroundStyle(.tertiary)
                    Text(dashboardRelativeTimestamp(fact.updatedAt))
                        .font(.system(size: 10)).foregroundStyle(.tertiary)
                }
            }
        }
        .padding(.vertical, 8)
    }

    private func journalAccordion(_ journal: SessionJournal) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Button {
                withAnimation(.easeInOut(duration: 0.2)) {
                    expandedJournal = expandedJournal == journal.date ? nil : journal.date
                }
            } label: {
                HStack {
                    Image(systemName: "doc.text")
                        .font(.system(size: 11))
                        .foregroundStyle(Color(hex: gBlue))
                    Text(journalDateLabel(journal.date))
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(.primary)
                    Spacer()
                    Image(systemName: expandedJournal == journal.date ? "chevron.up" : "chevron.down")
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 10)
                .background(.ultraThinMaterial)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            .buttonStyle(.plain)

            if expandedJournal == journal.date {
                ScrollView(.vertical, showsIndicators: true) {
                    Text(journal.content)
                        .font(.system(size: 11))
                        .foregroundStyle(.primary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .textSelection(.enabled)
                        .padding(12)
                }
                .frame(maxHeight: 280)
                .background(Color.white.opacity(0.03))
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
    }

    private func eventRow(_ event: InsightEvent) -> some View {
        HStack(alignment: .top, spacing: 14) {
            ZStack {
                Circle().fill(Color(hex: event.accentHex).opacity(0.15)).frame(width: 30, height: 30)
                Image(systemName: event.iconName)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Color(hex: event.accentHex))
            }
            VStack(alignment: .leading, spacing: 3) {
                HStack {
                    Text(event.primaryText)
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(.primary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                    Spacer()
                    Text(event.timeLabel)
                        .font(.system(size: 11))
                        .foregroundStyle(.tertiary)
                }
                Text(event.secondaryText)
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 10)
    }

    private func mcpProposalCard(_ proposal: ProposalRecord) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(proposal.displayTitle)
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(.primary)
                    Text("\(proposal.typeLabel) · \(proposal.relativeTimeLabel)")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Text(proposal.statusLabel)
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(Color(hex: proposal.statusAccentHex))
                    .padding(.horizontal, 10)
                    .padding(.vertical, 5)
                    .background(Color(hex: proposal.statusAccentHex).opacity(0.12))
                    .clipShape(Capsule())
            }

            if let command = proposal.command, !command.isEmpty {
                Text(command)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(.primary)
                    .textSelection(.enabled)
                    .padding(8)
                    .background(Color.black.opacity(0.2))
                    .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
            }

            if let evidence = proposal.evidence, !evidence.isEmpty,
               proposal.type == "context_injection" {
                Divider()
                LazyVGrid(
                    columns: Array(repeating: GridItem(.flexible(), spacing: 12), count: 3),
                    alignment: .leading,
                    spacing: 8
                ) {
                    ForEach(evidence, id: \.self) { item in
                        if let label = item["label"], let value = item["value"] {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(label)
                                    .font(.system(size: 9, weight: .semibold))
                                    .foregroundStyle(.tertiary)
                                    .tracking(0.3)
                                Text(value)
                                    .font(.system(size: 11))
                                    .foregroundStyle(.primary)
                                    .lineLimit(2)
                            }
                        }
                    }
                }
            }
        }
    }

    private var filteredEvents: [InsightEvent] {
        let ordered = vm.events.reversed()
        guard eventFilter != "all" else { return Array(ordered) }
        return ordered.filter { $0.type == eventFilter }
    }

    private var daemonStatusLabel: String {
        guard let ping = vm.ping else { return "Injoignable" }
        return ping.paused == true ? "En pause" : "Ok"
    }

    private var daemonStatusColor: String {
        guard let ping = vm.ping else { return gRed }
        return ping.paused == true ? gOrange : gGreen
    }

    private var lastRefreshLabel: String {
        guard let t = vm.lastRefreshedAt else { return "Jamais rafraîchi" }
        let d = max(Int(Date().timeIntervalSince(t)), 0)
        return "Il y a \(d) sec"
    }

    private func frictionColor(_ value: Double) -> Color {
        if value > 0.6 { return Color(hex: gRed) }
        if value > 0.3 { return Color(hex: gOrange) }
        return Color(hex: gGreen)
    }

    private func focusLabel(_ raw: String?) -> String {
        switch raw {
        case "deep": return "Profond"
        case "normal": return "Normal"
        case "scattered": return "Fragmenté"
        case "idle": return "Inactif"
        default: return raw ?? "—"
        }
    }

    private func todayTaskLabel(_ raw: String) -> String {
        switch raw {
        case "coding": return "Développement"
        case "writing": return "Rédaction"
        case "debug": return "Débogage"
        case "exploration", "browsing": return "Exploration"
        case "general": return "Général"
        default: return raw
        }
    }

    private func fileModeLabel(_ raw: String?) -> String {
        switch raw {
        case "single_file": return "Fichier unique"
        case "few_files": return "Quelques fichiers"
        case "multi_file": return "Multi-fichiers"
        default: return "—"
        }
    }

    private func patternLabel(_ raw: String?) -> String {
        switch raw {
        case "feature_candidate": return "Nouvelle feature"
        case "refactor_candidate": return "Refactoring"
        case "debug_loop_candidate": return "Boucle de debug"
        case "setup_candidate": return "Configuration"
        default: return raw ?? "—"
        }
    }

    private func clipboardLabel(_ raw: String?) -> String {
        switch raw {
        case "stacktrace": return "Stacktrace"
        case "code": return "Code"
        case "error_message": return "Erreur"
        case "url": return "URL"
        case "text": return "Texte"
        default: return "—"
        }
    }

    private func sessionDurationCompact(_ session: SessionContextData) -> String {
        guard let duration = session.durationSec else { return "—" }
        let hours = duration / 3600
        let minutes = (duration % 3600) / 60
        let seconds = duration % 60
        if hours > 0 {
            return String(format: "%02dh %02dm", hours, minutes)
        }
        if minutes > 0 {
            return String(format: "%02dm %02ds", minutes, seconds)
        }
        return "\(seconds) s"
    }
}

private struct GlassCard<Content: View>: View {
    var accent: String? = nil
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            content
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(
                    accent.map { Color(hex: $0).opacity(0.25) } ?? Color.white.opacity(0.08),
                    lineWidth: 1
                )
        )
    }
}

private func dashboardPercent(_ value: Double?) -> String {
    guard let value else { return "—" }
    return "\(Int((value * 100).rounded())) %"
}

private func dashboardScore(_ value: Double?) -> String {
    guard let value else { return "—" }
    return String(format: "%.2f", value)
}

private func dashboardCount(_ value: Int?) -> String {
    guard let value else { return "—" }
    return "\(value)"
}

private func dashboardMinutes(_ value: Int?) -> String {
    guard let value else { return "—" }
    let hours = value / 60
    let minutes = value % 60
    if hours > 0 {
        return String(format: "%02dh %02dm", hours, minutes)
    }
    return "\(minutes) min"
}

private func dashboardBoolLabel(_ value: Bool?) -> String {
    guard let value else { return "—" }
    return value ? "Oui" : "Non"
}

private func dashboardAbsoluteTimestamp(_ raw: String?) -> String {
    guard let date = dashboardDate(from: raw) else { return "—" }
    return DashboardDateFormatting.absolute.string(from: date)
}

private func dashboardRelativeTimestamp(_ raw: String?) -> String {
    guard let date = dashboardDate(from: raw) else { return "—" }
    let diff = Date().timeIntervalSince(date)
    if diff < 10 { return "à l'instant" }
    if diff < 60 { return "il y a \(Int(diff)) s" }
    if diff < 3600 { return "il y a \(Int(diff / 60)) min" }
    if diff < 86_400 { return "il y a \(Int(diff / 3600)) h" }
    return "il y a \(Int(diff / 86_400)) j"
}

private func sessionDurationLabel(from raw: String?) -> String {
    guard let date = dashboardDate(from: raw) else { return "—" }
    let delta = max(Int(Date().timeIntervalSince(date)), 0)
    let h = delta / 3600
    let m = (delta % 3600) / 60
    let s = delta % 60
    if h > 0 { return String(format: "%02dh %02dm", h, m) }
    return String(format: "%02dm %02ds", m, s)
}

private func journalDateLabel(_ raw: String) -> String {
    let f = DateFormatter()
    f.dateFormat = "yyyy-MM-dd"
    f.locale = Locale(identifier: "fr_FR")
    guard let date = f.date(from: raw) else { return raw }
    let d = DateFormatter()
    d.dateStyle = .full
    d.locale = Locale(identifier: "fr_FR")
    return d.string(from: date)
}

private func dashboardDate(from raw: String?) -> Date? {
    guard let raw, !raw.isEmpty else { return nil }
    return DashboardDateFormatting.internetFractional.date(from: raw)
        ?? DashboardDateFormatting.internet.date(from: raw)
        ?? DashboardDateFormatting.localFractional.date(from: raw)
        ?? DashboardDateFormatting.local.date(from: raw)
}

private enum DashboardDateFormatting {
    static let internetFractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    static let internet: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    static let localFractional: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSSSSS"
        return f
    }()

    static let local: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f
    }()

    static let absolute: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "fr_FR")
        f.dateStyle = .medium
        f.timeStyle = .short
        return f
    }()
}
