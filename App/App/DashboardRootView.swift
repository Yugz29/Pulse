import SwiftUI

private let gGreen = "#5DCAA5"
private let gRed = "#ff453a"
private let gOrange = "#EF9F27"
private let gBlue = "#5E9EFF"
private let gGray = "#7c7c80"
private let gPurple = "#8B5CF6"

private let dashboardBackground = Color(red: 0.035, green: 0.038, blue: 0.044)
private let dashboardSidebarBackground = Color(red: 0.025, green: 0.027, blue: 0.032)
private let dashboardPanelBackground = Color.white.opacity(0.045)
private let dashboardPanelSelectedBackground = Color.white.opacity(0.075)
private let dashboardStroke = Color.white.opacity(0.075)
private let dashboardSubtleStroke = Color.white.opacity(0.045)
private let dashboardDivider = Color.white.opacity(0.06)

enum DashboardSection: String, CaseIterable, Identifiable {
    case session = "Aujourd’hui"
    case episodes = "Séquences debug"
    case observation = "Observation"
    case memory = "Mémoire (Lab)"
    case daydream = "DayDream (Lab)"
    case events = "Événements"
    case notifications = "Notifications"
    case contextProbes = "Contexte (Lab)"
    case mcp = "MCP"
    case system = "Système"

    var id: String { rawValue }

    var icon: String {
        switch self {
        case .session: return "waveform.path.ecg"
        case .episodes: return "rectangle.stack.badge.play"
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
        case .episodes: return gOrange
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

enum DashboardSurface: String, CaseIterable, Identifiable {
    case product = "Produit"
    case debugLab = "Debug / Lab"

    var id: String { rawValue }

    var defaultSection: DashboardSection {
        switch self {
        case .product:
            return .session
        case .debugLab:
            return .episodes
        }
    }

    var sections: [DashboardSection] {
        switch self {
        case .product:
            return [
                .session,
                .notifications,
            ]
        case .debugLab:
            return [
                .episodes,
                .observation,
                .events,
                .mcp,
                .system,
                .memory,
                .daydream,
                .contextProbes,
            ]
        }
    }

    func contains(_ section: DashboardSection) -> Bool {
        sections.contains(section)
    }
}

struct DashboardRootView: View {
    @ObservedObject var vm: DashboardViewModel
    @State private var selectedSurface: DashboardSurface = .product
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
                .background(dashboardBackground)
        }
        .background(dashboardBackground)
        .preferredColorScheme(.dark)
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
                        .frame(width: 7, height: 7)
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

            Divider()
                .background(dashboardDivider)
                .padding(.horizontal, 10)

            surfaceSelector
                .padding(.horizontal, 12)
                .padding(.vertical, 10)

            ScrollView {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(selectedSurface.sections) { section in
                        sidebarItem(section)
                    }
                }
                .padding(.horizontal, 8)
            }

            Spacer()

            Divider()
                .background(dashboardDivider)
                .padding(.horizontal, 10)
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
        .background(dashboardSidebarBackground)
    }

    private var surfaceSelector: some View {
        HStack(spacing: 4) {
            ForEach(DashboardSurface.allCases) { surface in
                Button {
                    selectSurface(surface)
                } label: {
                    Text(surface.rawValue)
                        .font(.system(size: 11, weight: selectedSurface == surface ? .semibold : .medium))
                        .foregroundStyle(selectedSurface == surface ? .primary : .secondary)
                        .lineLimit(1)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 6)
                        .background(
                            RoundedRectangle(cornerRadius: 7, style: .continuous)
                                .fill(selectedSurface == surface ? dashboardPanelSelectedBackground : Color.clear)
                        )
                }
                .buttonStyle(.plain)
            }
        }
        .padding(3)
        .background(dashboardPanelBackground)
        .overlay(
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .stroke(dashboardSubtleStroke, lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
    }

    private func selectSurface(_ surface: DashboardSurface) {
        withAnimation(.easeInOut(duration: 0.15)) {
            selectedSurface = surface
            if !surface.contains(selectedSection) {
                selectedSection = surface.defaultSection
            }
        }
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
            .padding(.vertical, 6)
            .background(
                RoundedRectangle(cornerRadius: 7, style: .continuous)
                    .fill(selectedSection == section
                        ? Color(hex: section.accent).opacity(0.10)
                        : Color.clear)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 7, style: .continuous)
                    .stroke(
                        selectedSection == section
                            ? Color(hex: section.accent).opacity(0.20)
                            : Color.clear,
                        lineWidth: 1
                    )
            )
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private var detailView: some View {
        switch selectedSection {
        case .session:
            sessionView
        case .episodes:
            episodesView
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
            VStack(alignment: .leading, spacing: 16) {
                productTodayHero

                HStack(alignment: .top, spacing: 16) {
                    productRecentBlocksCard
                        .frame(maxWidth: .infinity)

                    VStack(alignment: .leading, spacing: 16) {
                        productNowCompactCard
                        productProjectsCompactCard
                    }
                    .frame(width: 320)
                }

                if !activeWorkIntentCandidates.isEmpty {
                    GlassCard(accent: gPurple) {
                        workIntentCandidatesSection
                    }
                }
            }
            .padding(24)
        }
    }

    private var productTodayHero: some View {
        let summary = vm.todaySummary
        let totals = summary?.totals
        let currentWindow = summary?.currentWindow
        let currentBlock = summary?.workBlocks.last
        let present = vm.state?.present
        let context = vm.state?.currentContext
        let fsm = vm.state?.sessionFsm
        let accent = context?.taskAccentHex ?? present?.taskAccentHex ?? fsm?.stateColor ?? gGreen
        let project = currentBlock?.project ?? currentWindow?.project ?? context?.activeProject ?? present?.activeProject ?? "Projet non identifié"
        let task = currentBlock?.taskLabel ?? currentWindow?.taskLabel ?? productTaskTitle(context, present)
        let activity = currentWindow?.activityLabel ?? present?.activityLabel ?? context?.activityLabel ?? "—"

        return GlassCard(accent: accent) {
            VStack(alignment: .leading, spacing: 18) {
                HStack(alignment: .top, spacing: 20) {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack(spacing: 8) {
                            Circle()
                                .fill(Color(hex: accent))
                                .frame(width: 7, height: 7)
                            Text("Aujourd’hui")
                                .font(.system(size: 11, weight: .semibold))
                                .foregroundStyle(.secondary)
                                .textCase(.uppercase)
                                .tracking(0.5)
                        }

                        Text(task)
                            .font(.system(size: 30, weight: .bold, design: .rounded))
                            .foregroundStyle(Color(hex: accent))
                            .lineLimit(1)
                            .minimumScaleFactor(0.75)

                        HStack(spacing: 8) {
                            Label(project, systemImage: "shippingbox")
                            Text("·")
                            Text(activity)
                            if let stateLabel = fsm?.stateLabel, !stateLabel.isEmpty {
                                Text("·")
                                Text(stateLabel)
                            }
                        }
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                    }

                    Spacer(minLength: 16)

                    VStack(alignment: .trailing, spacing: 5) {
                        metaLabel("Bloc en cours")
                        if currentBlock != nil || currentWindow != nil {
                            TimelineView(.periodic(from: .now, by: 1)) { _ in
                                Text(sessionDurationLabel(from: currentBlock?.startedAt ?? currentWindow?.startedAt))
                                    .font(.system(size: 24, weight: .bold, design: .rounded))
                                    .foregroundStyle(.primary)
                                    .monospacedDigit()
                            }
                            Text("Mis à jour \(dashboardRelativeTimestamp(summary?.generatedAt))")
                                .font(.system(size: 11))
                                .foregroundStyle(.tertiary)
                        } else {
                            Text("—")
                                .font(.system(size: 24, weight: .bold, design: .rounded))
                                .foregroundStyle(.secondary)
                        }
                    }
                }

                HStack(spacing: 10) {
                    productHeroMetric("Travail", dashboardMinutes(totals?.workedMin), gGreen)
                    productHeroMetric("Commits", dashboardCount(totals?.commitCount), gOrange)
                    productHeroMetric("Blocs", dashboardCount(totals?.windowCount), gBlue)
                    productHeroMetric("Projets", dashboardCount(totals?.projectCount), gGray)
                }
            }
        }
    }

    private func productHeroMetric(_ label: String, _ value: String, _ colorHex: String) -> some View {
        HStack(spacing: 8) {
            Circle()
                .fill(Color(hex: colorHex).opacity(0.85))
                .frame(width: 6, height: 6)
            VStack(alignment: .leading, spacing: 2) {
                Text(label)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(.tertiary)
                Text(value)
                    .font(.system(size: 15, weight: .semibold, design: .rounded))
                    .foregroundStyle(.primary)
                    .monospacedDigit()
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 11)
        .padding(.vertical, 9)
        .background(Color.white.opacity(0.035))
        .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
    }

    private var productRecentBlocksCard: some View {
        let allBlocks = vm.todaySummary?.workBlocks ?? []
        let blocks = Array(allBlocks.suffix(3).reversed())
        let dayBlocks = Array(allBlocks.suffix(8).reversed())
        let currentWindowId = vm.todaySummary?.currentWindow?.id

        return GlassCard(accent: gGreen) {
            VStack(alignment: .leading, spacing: 14) {
                VStack(alignment: .leading, spacing: 6) {
                    HStack(alignment: .firstTextBaseline) {
                        cardTitle("Travail récent", icon: "list.bullet.rectangle")
                        Spacer()
                        Text(dashboardRelativeTimestamp(vm.todaySummary?.timeline.lastActivityAt))
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(.tertiary)
                    }

                    Text("Résumé local construit depuis les signaux observés. Les commandes récentes sont dans Notifications.")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                if blocks.isEmpty {
                    emptyState("Aucun bloc de travail persistant aujourd’hui")
                } else {
                    VStack(spacing: 0) {
                        ForEach(Array(blocks.enumerated()), id: \.element.id) { index, block in
                            productBlockRow(
                                block,
                                isPrimary: index == 0,
                                currentWindowId: currentWindowId
                            )
                            if block.id != blocks.last?.id {
                                Divider()
                                    .background(dashboardDivider)
                                    .padding(.leading, 88)
                            }
                        }
                    }

                    Divider()
                        .background(dashboardDivider)

                    VStack(alignment: .leading, spacing: 8) {
                        HStack(alignment: .firstTextBaseline) {
                            cardTitle("Journée complète", icon: "calendar")
                            Spacer()
                            if allBlocks.count > dayBlocks.count {
                                Text("\(dayBlocks.count) / \(allBlocks.count) blocs")
                                    .font(.system(size: 11, weight: .medium))
                                    .foregroundStyle(.tertiary)
                            }
                        }

                        Text("Vue compacte des blocs observés aujourd’hui.")
                            .font(.system(size: 11))
                            .foregroundStyle(.tertiary)

                        VStack(spacing: 0) {
                            ForEach(dayBlocks) { block in
                                productDayBlockRow(block)
                                if block.id != dayBlocks.last?.id {
                                    Divider()
                                        .background(dashboardDivider)
                                        .padding(.leading, 56)
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    private func productBlockRow(
        _ block: TodayWorkBlock,
        isPrimary: Bool = false,
        currentWindowId: String? = nil
    ) -> some View {
        let visibleFiles = Array((block.topFiles ?? []).prefix(3))
        let hiddenFileCount = max((block.topFiles ?? []).count - visibleFiles.count, 0)
        let primaryLabel = currentWindowId == block.id ? "Maintenant" : "Dernier signal"
        let titleWeight: Font.Weight = isPrimary ? .semibold : .medium
        let rowOpacity = isPrimary ? 1.0 : 0.68

        return HStack(alignment: .top, spacing: 14) {
            VStack(alignment: .leading, spacing: 3) {
                Text(dashboardShortTime(block.startedAt))
                    .font(.system(size: 13, weight: titleWeight, design: .rounded))
                    .foregroundStyle(.primary)
                Text(dashboardMinutes(block.durationMin))
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(.tertiary)
            }
            .frame(width: 74, alignment: .leading)

            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 6) {
                    Text(block.taskLabel)
                        .font(.system(size: 13, weight: titleWeight))
                        .foregroundStyle(.primary)
                    if let project = block.project, !project.isEmpty {
                        Text("·")
                            .foregroundStyle(.tertiary)
                        Text(project)
                            .foregroundStyle(.secondary)
                    }
                    if isPrimary {
                        Text(primaryLabel)
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(Color(hex: currentWindowId == block.id ? gGreen : gGray))
                            .padding(.horizontal, 7)
                            .padding(.vertical, 3)
                            .background(Color(hex: currentWindowId == block.id ? gGreen : gGray).opacity(0.12))
                            .clipShape(Capsule())
                    }
                }
                .lineLimit(1)

                if !visibleFiles.isEmpty {
                    HStack(spacing: 5) {
                        Image(systemName: "doc.text")
                            .font(.system(size: 10, weight: .medium))
                            .foregroundStyle(.tertiary)
                        Text(visibleFiles.joined(separator: " · "))
                        if hiddenFileCount > 0 {
                            Text("· +\(hiddenFileCount)")
                        }
                    }
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                } else {
                    Text("Signal récent : \(block.activityLabel)")
                        .font(.system(size: 11))
                        .foregroundStyle(.tertiary)
                        .lineLimit(1)
                }
            }

            Spacer(minLength: 0)
        }
        .opacity(rowOpacity)
        .padding(.vertical, 10)
    }

    private func productDayBlockRow(_ block: TodayWorkBlock) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(dashboardShortTime(block.startedAt))
                .font(.system(size: 11, weight: .semibold, design: .rounded))
                .foregroundStyle(.secondary)
                .frame(width: 46, alignment: .leading)

            Text(block.taskLabel)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(.primary)
                .lineLimit(1)

            if let project = block.project, !project.isEmpty {
                Text("·")
                    .foregroundStyle(.tertiary)
                Text(project)
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            if let file = block.topFiles?.first, !file.isEmpty {
                Text("·")
                    .foregroundStyle(.tertiary)
                Text(file)
                    .font(.system(size: 11))
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }

            Spacer(minLength: 8)

            Text(dashboardMinutes(block.durationMin))
                .font(.system(size: 11, weight: .semibold, design: .rounded))
                .foregroundStyle(.tertiary)
                .monospacedDigit()
        }
        .padding(.vertical, 7)
    }

    private var productNowCompactCard: some View {
        let context = vm.state?.currentContext
        let present = vm.state?.present
        let signals = vm.state?.signals
        let fsm = vm.state?.sessionFsm
        let statusAccent = fsm?.stateColor ?? (vm.ping != nil ? gGreen : gOrange)
        let statusLabel = fsm?.stateLabel ?? (vm.ping != nil ? "Daemon actif" : "Daemon injoignable")
        let activity = present?.activityLabel ?? context?.activityLabel ?? "—"
        let updatedAt = present?.updatedAt ?? vm.todaySummary?.generatedAt

        return GlassCard(accent: statusAccent) {
            VStack(alignment: .leading, spacing: 10) {
                cardTitle("État Pulse", icon: "checkmark.circle")

                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 8) {
                        Circle()
                            .fill(Color(hex: statusAccent))
                            .frame(width: 7, height: 7)
                        Text(statusLabel)
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(.primary)
                    }

                    Text("Signal live : \(activity)")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }

                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text("Dernière mise à jour")
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(.tertiary)
                        Spacer()
                        Text(dashboardRelativeTimestamp(updatedAt))
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(.secondary)
                    }

                    HStack {
                        Text("Confiance")
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(.tertiary)
                        Spacer()
                        Text(signals?.taskEvidenceLabel ?? "Lecture live")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(isWeakProductTask(context, present) ? .tertiary : .secondary)
                            .lineLimit(1)
                    }
                }
                .padding(.top, 2)

                if let lastSignal = fsm?.lastMeaningfulActivityAt {
                    Text("Dernier signal \(dashboardRelativeTimestamp(lastSignal))")
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
        }
    }

    private var productProjectsCompactCard: some View {
        let projects = vm.todaySummary?.projects ?? []

        return GlassCard(accent: gBlue) {
            VStack(alignment: .leading, spacing: 12) {
                cardTitle("Projets du jour", icon: "square.grid.2x2")

                if projects.isEmpty {
                    emptyState("Aucun projet persistant")
                } else {
                    VStack(spacing: 0) {
                        ForEach(projects.prefix(4)) { project in
                            HStack(alignment: .firstTextBaseline, spacing: 10) {
                                Circle()
                                    .fill(Color(hex: gBlue).opacity(0.65))
                                    .frame(width: 6, height: 6)
                                VStack(alignment: .leading, spacing: 3) {
                                    HStack {
                                        Text(project.name)
                                            .font(.system(size: 12, weight: .semibold))
                                            .foregroundStyle(.primary)
                                            .lineLimit(1)
                                        Spacer()
                                        Text(dashboardMinutes(project.workedMin))
                                            .font(.system(size: 11, weight: .semibold, design: .rounded))
                                            .foregroundStyle(.secondary)
                                            .monospacedDigit()
                                    }
                                    if !project.topTasks.isEmpty {
                                        Text(project.topTasks.prefix(2).map(todayTaskLabel).joined(separator: " · "))
                                            .font(.system(size: 10))
                                            .foregroundStyle(.tertiary)
                                            .lineLimit(1)
                                    }
                                }
                            }
                            .padding(.vertical, 7)
                        }
                    }
                }
            }
        }
    }

    private var todayOverviewCard: some View {
        let summary = vm.todaySummary
        let totals = summary?.totals
        let currentWindow = summary?.currentWindow
        let currentBlock = summary?.workBlocks.last
        let recentBlocks = Array((summary?.workBlocks ?? []).suffix(3).reversed())

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
                            Text("Bloc du jour en cours")
                                .font(.system(size: 10, weight: .semibold))
                                .foregroundStyle(.secondary)
                        }
                        TimelineView(.periodic(from: .now, by: 1)) { _ in
                            Text(sessionDurationLabel(from: currentBlock?.startedAt ?? currentWindow?.startedAt))
                                .font(.system(size: 22, weight: .bold, design: .rounded))
                                .foregroundStyle(.primary)
                        }
                        signalRow("Projet", currentBlock?.project ?? currentWindow?.project ?? "—")
                        signalRow("Tâche principale", currentBlock?.taskLabel ?? currentWindow?.taskLabel ?? "—")
                        signalRow("Activité récente", currentWindow?.activityLabel ?? "—")
                        signalRow("Commits", "\(currentWindow?.commitCount ?? totals?.commitCount ?? 0)")
                    }
                }

                if !recentBlocks.isEmpty {
                    Divider()
                    VStack(alignment: .leading, spacing: 8) {
                        HStack(spacing: 6) {
                            Image(systemName: "list.bullet.rectangle")
                                .font(.system(size: 10))
                                .foregroundStyle(.secondary)
                            Text("Derniers blocs")
                                .font(.system(size: 10, weight: .semibold))
                                .foregroundStyle(.secondary)
                        }
                        ForEach(recentBlocks) { block in
                            let visibleFiles = Array((block.topFiles ?? []).prefix(2))
                            let hiddenFileCount = max((block.topFiles ?? []).count - visibleFiles.count, 0)
                            VStack(alignment: .leading, spacing: 3) {
                                Text("\(dashboardShortTime(block.startedAt)) → \(dashboardShortTime(block.endedAt)) · \(dashboardMinutes(block.durationMin))")
                                    .font(.system(size: 11, weight: .semibold))
                                    .foregroundStyle(.primary)
                                    .lineLimit(1)
                                HStack(spacing: 6) {
                                    Text(block.taskLabel)
                                    if let project = block.project, !project.isEmpty {
                                        Text("·")
                                        Text(project)
                                    }
                                }
                                .font(.system(size: 10))
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                                Text("Signal récent : \(block.activityLabel)")
                                    .font(.system(size: 10))
                                    .foregroundStyle(.tertiary)
                                    .lineLimit(1)
                                if !visibleFiles.isEmpty {
                                    HStack(spacing: 4) {
                                        Text(visibleFiles.joined(separator: " · "))
                                        if hiddenFileCount > 0 {
                                            Text("· +\(hiddenFileCount)")
                                        }
                                    }
                                        .font(.system(size: 11))
                                        .foregroundStyle(.secondary)
                                        .lineLimit(1)
                                }
                            }
                        }
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

    private var episodesView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Séquences reconstruites (debug)")
                            .font(.system(size: 24, weight: .bold, design: .rounded))
                        Text(vm.debugWorkEpisodes?.date ?? vm.debugCommitEpisodeLinks?.date ?? "aujourd’hui")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                        Text("Reconstruction debug depuis événements/journal, pas source Core canonique.")
                            .font(.system(size: 11))
                            .foregroundStyle(.tertiary)
                    }
                    Spacer()
                    Button {
                        Task { await vm.refresh() }
                    } label: {
                        Label("Rafraîchir", systemImage: "arrow.clockwise")
                    }
                    .buttonStyle(.bordered)
                }

                WorkTimelineSection(
                    episodes: vm.debugWorkEpisodes?.episodes ?? [],
                    commitLinks: vm.debugCommitEpisodeLinks?.links ?? [],
                    unlinkedCommits: vm.debugCommitEpisodeLinks?.unlinkedCommits ?? []
                )

                DisclosureGroup {
                    HStack(alignment: .top, spacing: 16) {
                        debugWorkEpisodesCard
                        debugCommitLinksCard
                    }
                    .padding(.top, 8)
                } label: {
                    Label("Debug reconstruction", systemImage: "wrench.and.screwdriver")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(.secondary)
                }
            }
            .padding(24)
        }
    }

    private var debugWorkEpisodesCard: some View {
        let episodes = vm.debugWorkEpisodes?.episodes ?? []

        return GlassCard(accent: gOrange) {
            VStack(alignment: .leading, spacing: 12) {
                cardTitle("Séquences debug", icon: "rectangle.stack")

                if episodes.isEmpty {
                    emptyState("Aucun épisode reçu ou route debug indisponible")
                } else {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(episodes.prefix(12)) { episode in
                            VStack(alignment: .leading, spacing: 7) {
                                HStack(alignment: .firstTextBaseline) {
                                    Text("\(dashboardAbsoluteTimestamp(episode.startedAt)) → \(dashboardAbsoluteTimestamp(episode.endedAt))")
                                        .font(.system(size: 12, weight: .semibold))
                                        .foregroundStyle(.primary)
                                    Spacer()
                                    Text(dashboardMinutes(episode.durationMin))
                                        .font(.system(size: 11, weight: .medium))
                                        .foregroundStyle(.secondary)
                                }

                                HStack(spacing: 6) {
                                    debugPill(episode.project ?? "—", color: gBlue)
                                    debugPill(episode.dominantScope ?? "scope —", color: gOrange)
                                    debugPill(episode.probableTask ?? "task —", color: gGray)
                                }

                                HStack(spacing: 12) {
                                    Text("boundary \(episode.boundaryReason ?? "—")")
                                    Text("S \(episode.strongEventCount ?? 0) / W \(episode.weakEventCount ?? 0)")
                                    Text("conf \(dashboardScore(episode.confidence))")
                                }
                                .font(.system(size: 10))
                                .foregroundStyle(.secondary)

                                if let reason = episode.debugReason, !reason.isEmpty {
                                    Text(reason)
                                        .font(.system(size: 10))
                                        .foregroundStyle(.tertiary)
                                        .lineLimit(3)
                                }
                            }
                            .padding(.vertical, 8)

                            if episode.id != episodes.prefix(12).last?.id {
                                Divider()
                            }
                        }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity)
    }

    private var debugCommitLinksCard: some View {
        let payload = vm.debugCommitEpisodeLinks
        let links = payload?.links ?? []
        let unlinked = payload?.unlinkedCommits ?? []

        return GlassCard(accent: gBlue) {
            VStack(alignment: .leading, spacing: 12) {
                cardTitle("Commit links", icon: "point.3.connected.trianglepath.dotted")

                HStack(spacing: 14) {
                    statBadge("Commits", dashboardCount(payload?.commitCount), gGray)
                    statBadge("Liés", dashboardCount(payload?.linkedCount), gGreen)
                    statBadge("Non liés", dashboardCount(payload?.unlinkedCount), gRed)
                }

                if links.isEmpty && unlinked.isEmpty {
                    emptyState("Aucun commit link reçu ou route debug indisponible")
                } else {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(links.prefix(10)) { link in
                            debugCommitLinkRow(link, linked: true)
                            if link.id != links.prefix(10).last?.id || !unlinked.isEmpty {
                                Divider()
                            }
                        }
                        ForEach(unlinked.prefix(5)) { link in
                            debugCommitLinkRow(link, linked: false)
                            if link.id != unlinked.prefix(5).last?.id {
                                Divider()
                            }
                        }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity)
    }

    private func debugCommitLinkRow(_ link: DebugCommitEpisodeLink, linked: Bool) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(alignment: .firstTextBaseline) {
                Text(link.commitSubject ?? "Commit sans sujet")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(.primary)
                    .lineLimit(2)
                Spacer()
                Text(dashboardScore(link.confidence))
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(linked ? Color(hex: gGreen) : Color(hex: gRed))
            }

            VStack(alignment: .leading, spacing: 3) {
                if let displayWindow = commitLinkDisplayEpisodeWindowLabel(link) {
                    Text(displayWindow)
                }
                if let evidenceWindow = commitLinkEvidenceWindowLabel(link) {
                    Text(evidenceWindow)
                }
                if let journalWindow = commitLinkJournalWindowLabel(link) {
                    Text(journalWindow)
                }
            }
            .font(.system(size: 10))
            .foregroundStyle(.secondary)

            HStack(spacing: 10) {
                Text(link.linkReason ?? (linked ? "linked" : "unlinked"))
                Text("delivery Δ \(debugOptionalMinutes(link.deliveryDeltaMin))")
                if let overlap = link.overlapMin {
                    Text("overlap \(overlap) min")
                }
            }
            .font(.system(size: 10))
            .foregroundStyle(.secondary)

            let flags = (link.flags ?? []).prefix(5)
            if !flags.isEmpty {
                HStack(spacing: 5) {
                    ForEach(Array(flags), id: \.self) { flag in
                        debugPill(flag, color: linked ? gBlue : gGray)
                    }
                }
            }
        }
        .padding(.vertical, 8)
    }

    private func debugPill(_ text: String, color: String) -> some View {
        Text(text)
            .font(.system(size: 10, weight: .medium))
            .foregroundStyle(Color(hex: color))
            .lineLimit(1)
            .padding(.horizontal, 7)
            .padding(.vertical, 3)
            .background(Color(hex: color).opacity(0.12))
            .clipShape(Capsule())
    }

    private func debugOptionalMinutes(_ value: Int?) -> String {
        guard let value else { return "—" }
        return "\(value) min"
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


    private func workContextList(title: String, icon: String, items: [String], empty: String, accent: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Image(systemName: icon)
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(Color(hex: accent))
                Text(title)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(.secondary)
            }

            if items.isEmpty {
                Text(empty)
                    .font(.system(size: 11))
                    .foregroundStyle(.tertiary)
            } else {
                VStack(alignment: .leading, spacing: 5) {
                    ForEach(items.prefix(5), id: \.self) { item in
                        HStack(alignment: .top, spacing: 6) {
                            Circle()
                                .fill(Color(hex: accent).opacity(0.65))
                                .frame(width: 5, height: 5)
                                .padding(.top, 5)
                            Text(item)
                                .font(.system(size: 11))
                                .foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var currentContextCard: some View {
        let context = vm.state?.currentContext
        let present = vm.state?.present
        let liveSignals = vm.state?.signals
        let workContextCard = vm.workContextCard
        let weakContext = isWeakProductTask(context, present)
        let evidenceLabel = workContextCard?.hasStrongProjectContext == true
            ? workContextCard?.projectContextLabel ?? "Projet corroboré"
            : liveSignals?.taskEvidenceLabel ?? "Faible"
        let accent = context?.taskAccentHex ?? present?.taskAccentHex ?? gGray

        return GlassCard(accent: context?.boundaryColor ?? gBlue) {
            VStack(alignment: .leading, spacing: 12) {
                cardTitle("Lecture courante", icon: "timeline.selection")
                Text("Le contexte live décrit l’instant courant. Les séquences et le résumé du jour agrègent une période plus large.")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                if let context {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(productTaskTitle(context, present))
                            .font(.system(size: weakContext ? 18 : 22, weight: weakContext ? .semibold : .bold, design: .rounded))
                            .foregroundStyle(weakContext ? .secondary : Color(hex: accent))
                        HStack(spacing: 8) {
                            evidenceBadge(evidenceLabel, weak: weakContext && workContextCard?.hasStrongProjectContext != true)
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
                            Text("Hypothèse live")
                                .font(.system(size: 10, weight: .semibold))
                                .foregroundStyle(.secondary)
                        }

                        signalRow("Projet", context.activeProject ?? present?.activeProject ?? "—")
                        if let projectHintLabel = vm.workContextCard?.projectHintLabel {
                            HStack(alignment: .top, spacing: 6) {
                                Image(systemName: "lightbulb")
                                    .font(.system(size: 10, weight: .medium))
                                    .foregroundStyle(Color(hex: gOrange))
                                    .padding(.top, 2)
                                Text(projectHintLabel)
                                    .font(.system(size: 11, weight: .medium))
                                    .foregroundStyle(Color(hex: gOrange))
                                    .fixedSize(horizontal: false, vertical: true)
                                Spacer()
                            }
                            .padding(.top, 2)
                        }
                        signalRow("Tâche principale", context.taskLabel)
                        signalRow("Activité récente", context.activityLabel)
                        signalRow("Focus", focusLabel(present?.focusLevel))
                        signalRow("Confiance tâche", dashboardPercent(context.taskConfidence))
                        if context.boundaryReason == "idle_timeout" {
                            signalRow("Fin", "Estimée par inactivité")
                        }
                    }

                    if let liveSignals {
                        Divider()
                        Text(workContextCard?.hasStrongProjectContext == true ? workContextCard?.projectContextSummary ?? liveSignals.taskEvidenceSummary : liveSignals.taskEvidenceSummary)
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    if let card = vm.workContextCard {
                        Divider()

                        VStack(alignment: .leading, spacing: 12) {
                            if !card.evidence.isEmpty {
                                workContextList(
                                    title: "Pourquoi Pulse pense ça",
                                    icon: "checkmark.seal",
                                    items: card.evidence,
                                    empty: "Aucune preuve forte",
                                    accent: gGreen
                                )
                            }

                            if !card.missingContext.isEmpty {
                                workContextList(
                                    title: "Contexte manquant",
                                    icon: "questionmark.folder",
                                    items: card.missingContext,
                                    empty: "Rien de bloquant",
                                    accent: gOrange
                                )
                            }

                            if !card.safeNextProbes.isEmpty {
                                HStack(alignment: .center, spacing: 8) {
                                    Image(systemName: "shield")
                                        .font(.system(size: 10, weight: .medium))
                                        .foregroundStyle(.tertiary)

                                    Text("Probes safe possibles")
                                        .font(.system(size: 10, weight: .semibold))
                                        .foregroundStyle(.tertiary)

                                    ForEach(card.safeNextProbes, id: \.self) { probe in
                                        Text(probe)
                                            .font(.system(size: 10, weight: .semibold, design: .monospaced))
                                            .foregroundStyle(Color(hex: gBlue))
                                            .padding(.horizontal, 7)
                                            .padding(.vertical, 3)
                                            .background(Color(hex: gBlue).opacity(0.10))
                                            .clipShape(Capsule())
                                    }

                                    Spacer()
                                }
                            }
                        }
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
        let workContextCard = vm.workContextCard
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
                        evidenceBadge(
                            workContextCard?.hasStrongProjectContext == true ? workContextCard?.projectContextLabel ?? signals.taskEvidenceLabel : signals.taskEvidenceLabel,
                            weak: weakTask && workContextCard?.hasStrongProjectContext != true
                        )
                        Text(workContextCard?.hasStrongProjectContext == true ? workContextCard?.projectContextSummary ?? signals.taskEvidenceSummary : signals.taskEvidenceSummary)
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }

                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        metaLabel("Confiance tâche")
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
                    Text("Activité récente: \((present?.activityLabel ?? context?.activityLabel) ?? "—")")
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
                        Text("DayDream est une expérimentation Lab, non requise par le Core. Son déclenchement automatique est désactivé ou ignoré en mode Core.")
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
            return "Mode Lab : le résumé nocturne attend le prochain verrouillage d’écran après 23h59."
        case "running":
            return "Mode Lab : le résumé de la journée est en cours de génération."
        case "generated":
            return "Mode Lab : le résumé a été généré avec succès."
        case "already_exists":
            return "Le fichier DayDream existait déjà; aucune régénération n’a été faite."
        case "already_completed_for_date":
            return "Mode Lab : cette journée a déjà été consolidée."
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
                        cardTitle("Profil Lab pour contexte LLM", icon: "brain.head.profile")
                        if let profile = vm.factsProfile?.profile, !profile.isEmpty {
                            Text(profile)
                                .font(.system(size: 12))
                                .foregroundStyle(.primary)
                                .textSelection(.enabled)
                                .fixedSize(horizontal: false, vertical: true)
                        } else {
                            emptyState("Aucun profil Lab consolidé")
                        }
                    }
                }

                GlassCard {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            cardTitle("Faits Lab consolidés", icon: "checkmark.seal")
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
                        cardTitle("Snapshot mémoire Lab / debug", icon: "memorychip")
                        HStack(spacing: 6) {
                            Image(systemName: "clock")
                                .font(.system(size: 11))
                                .foregroundStyle(.secondary)
                            Text("Gelée à \(dashboardAbsoluteTimestamp(vm.memory?.frozenAt))")
                                .font(.system(size: 12))
                                .foregroundStyle(.secondary)
                        }
                        Text("Vue Lab issue des faits et journaux. Non requise par le Core et non injectée dans le chemin Core.")
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

            Text("Les événements user_presence sont masqués par défaut pour réduire le bruit.")
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 24)
                .padding(.vertical, 8)

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
                if !activeWorkIntentCandidates.isEmpty {
                    GlassCard(accent: gPurple) {
                        workIntentCandidatesSection
                    }
                }

                GlassCard(accent: gBlue) {
                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            cardTitle("Demandes de contexte", icon: "shield.lefthalf.filled")
                            Spacer()
                            Button {
                                Task { await vm.createFocusedElementTextProbeRequest() }
                            } label: {
                                Label("Lire le champ texte actif", systemImage: "text.cursor")
                            }
                            .buttonStyle(.bordered)
                            Button {
                                vm.diagnoseActiveAccessibilityElement()
                            } label: {
                                Label("Diagnostiquer l'élément actif", systemImage: "stethoscope")
                            }
                            .buttonStyle(.bordered)
                            statBadge("Demandes", "\(vm.contextProbeRequests.count)", gBlue)
                        }
                        Text("Demandes de contexte contrôlées par validation humaine. Les metadata brutes et les valeurs capturées ne sont pas affichées ici.")
                            .font(.system(size: 11))
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                        if let diagnostic = vm.accessibilityProbeDiagnostic {
                            DisclosureGroup {
                                accessibilityDiagnosticBlock(diagnostic)
                                    .padding(.top, 8)
                            } label: {
                                Label("Diagnostic AX", systemImage: "stethoscope")
                                    .font(.system(size: 11, weight: .semibold))
                                    .foregroundStyle(.secondary)
                            }
                        }
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

    private var activeWorkIntentCandidates: [WorkIntentCandidatePayload] {
        vm.workIntentCandidates
            .filter { $0.status == "candidate" && $0.isActive }
            .sorted { $0.createdAt ?? "" > $1.createdAt ?? "" }
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

    private var workIntentCandidatesSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                cardTitle("Intentions proposées", icon: "target")
                Spacer()
                statBadge("À valider", "\(activeWorkIntentCandidates.count)", gPurple)
            }
            Text("Candidates issues des context probes validées. Le texte affiché est déjà borné et redigé côté daemon.")
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            ForEach(activeWorkIntentCandidates) { candidate in
                workIntentCandidateRow(candidate)
            }
        }
    }

    private func workIntentCandidateRow(_ candidate: WorkIntentCandidatePayload) -> some View {
        let statusColor = Color(hex: candidate.statusAccentHex)

        return VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 10) {
                VStack(alignment: .leading, spacing: 5) {
                    HStack(spacing: 8) {
                        Text(candidate.sourceLabel)
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(.secondary)
                        Text(candidate.statusLabel)
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(statusColor)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 4)
                            .background(statusColor.opacity(0.12))
                            .clipShape(Capsule())
                    }
                    Text(candidate.summary)
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(.primary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer()
            }

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), alignment: .leading)], alignment: .leading, spacing: 6) {
                contextProbeMetaPill("Projet", candidate.project?.isEmpty == false ? candidate.project! : "n/a")
                contextProbeMetaPill("Confiance", candidate.confidenceLabel)
                contextProbeMetaPill("Expire", candidate.expiresAt ?? "n/a")
                contextProbeMetaPill("Evidence", candidate.evidenceRefs.isEmpty ? "n/a" : candidate.evidenceRefs.joined(separator: " · "))
            }

            HStack(spacing: 8) {
                Button {
                    Task { await vm.acceptWorkIntentCandidate(candidate) }
                } label: {
                    Label("Utiliser comme intention", systemImage: "checkmark.circle")
                }
                .buttonStyle(.borderedProminent)
                .tint(Color(hex: gGreen))

                Button(role: .destructive) {
                    Task { await vm.refuseWorkIntentCandidate(candidate) }
                } label: {
                    Label("Ignorer", systemImage: "xmark.circle")
                }
                .buttonStyle(.bordered)

                Spacer()
            }
        }
        .padding(12)
        .background(Color.white.opacity(0.035))
        .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
    }

    private func accessibilityDiagnosticBlock(_ diagnostic: AccessibilityTextProbeDiagnostic) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Divider()
            HStack(spacing: 8) {
                Image(systemName: diagnostic.isAllowed ? "checkmark.shield" : "exclamationmark.shield")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(diagnostic.isAllowed ? Color(hex: gGreen) : Color(hex: "#F5A623"))
                Text("Diagnostic AX local")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(.secondary)
                Spacer()
                Text(diagnostic.rejectionReason)
                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                    .foregroundStyle(diagnostic.isAllowed ? Color(hex: gGreen) : Color(hex: "#F5A623"))
            }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 180), alignment: .leading)], alignment: .leading, spacing: 6) {
                contextProbeMetaPill("App", diagnostic.appName)
                contextProbeMetaPill("Bundle", diagnostic.bundleId)
                contextProbeMetaPill("PID", "\(diagnostic.pid)")
                contextProbeMetaPill("AX trusted", diagnostic.axTrusted ? "oui" : "non")
                contextProbeMetaPill("Focused", diagnostic.focusedElementStatus)
                contextProbeMetaPill("Role", diagnostic.focusedRole ?? "n/a")
                contextProbeMetaPill("Subrole", diagnostic.focusedSubrole ?? "n/a")
                contextProbeMetaPill("Description", diagnostic.roleDescription ?? "n/a")
                contextProbeMetaPill("Selected", diagnostic.canReadSelectedText ? "\(diagnostic.selectedTextLength ?? 0) chars" : "non")
                contextProbeMetaPill("Value", diagnostic.canReadValue ? "\(diagnostic.valueLength ?? 0) chars" : "non")
                contextProbeMetaPill("Window", diagnostic.focusedWindowStatus)
                contextProbeMetaPill("Window role", diagnostic.focusedWindowRole ?? "n/a")
                contextProbeMetaPill("Window title", diagnostic.focusedWindowTitleAvailable ? "oui" : "non")
                contextProbeMetaPill("Secure", diagnostic.isSecureField ? "oui" : "non")
                contextProbeMetaPill("WebArea", diagnostic.isWebArea ? "oui" : "non")
            }
            if let tree = diagnostic.treeSummary {
                Divider()
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 180), alignment: .leading)], alignment: .leading, spacing: 6) {
                    contextProbeMetaPill("Tree inspected", tree.treeInspected ? "oui" : "non")
                    contextProbeMetaPill("Tree depth", "\(tree.treeDepthLimit)")
                    contextProbeMetaPill("Tree nodes", "\(tree.totalNodesSeen)/\(tree.treeNodeLimit)")
                    contextProbeMetaPill("Tree truncated", tree.treeTruncated ? "oui" : "non")
                    contextProbeMetaPill("Editable", "\(tree.editableCandidateCount)")
                    contextProbeMetaPill("TextArea", "\(tree.textAreaCount)")
                    contextProbeMetaPill("TextField", "\(tree.textFieldCount)")
                    contextProbeMetaPill("ComboBox", "\(tree.comboBoxCount)")
                    contextProbeMetaPill("SearchField", "\(tree.searchFieldCount)")
                    contextProbeMetaPill("WebArea", "\(tree.webAreaCount)")
                    contextProbeMetaPill("SecureField", "\(tree.secureTextFieldCount)")
                    contextProbeMetaPill("Unknown roles", "\(tree.unknownRoleCount)")
                    contextProbeMetaPill("Candidates", tree.candidateRolesFound.isEmpty ? "aucun" : tree.candidateRolesFound.joined(separator: " > "))
                    contextProbeMetaPill("First path", tree.firstCandidatePathRoles.isEmpty ? "n/a" : tree.firstCandidatePathRoles.joined(separator: " > "))
                    contextProbeMetaPill("Tree rejection", tree.rejectionSummary ?? "n/a")
                }
                if !tree.rolesCount.isEmpty {
                    Text(tree.rolesCount.sorted { $0.key < $1.key }.map { "\($0.key): \($0.value)" }.joined(separator: " · "))
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
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

                if request.canCaptureFromAccessibility {
                    Button {
                        Task { await vm.captureFocusedElementText(request) }
                    } label: {
                        Label("Lire maintenant", systemImage: "text.cursor")
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

            if result.kind == "window_title"
                || result.kind == "focused_element_text"
                || result.kind == "selected_text"
                || result.kind == "clipboard_sample"
                || result.kind == "manual_context_note" {
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

                GlassCard(accent: vm.appleFoundationLocalStatus?.available == true ? gGreen : gGray) {
                    VStack(alignment: .leading, spacing: 10) {
                        cardTitle("Apple Foundation", icon: "sparkles")
                        HStack(spacing: 8) {
                            statBadge(
                                "Apple",
                                dashboardBoolLabel(vm.appleFoundationLocalStatus?.available),
                                vm.appleFoundationLocalStatus?.available == true ? gGreen : gGray
                            )
                            statBadge(
                                "Worker",
                                dashboardBoolLabel(vm.appleFoundationLocalStatus?.workerRunning),
                                vm.appleFoundationLocalStatus?.workerRunning == true ? gGreen : gGray
                            )
                        }
                        if let queue = vm.lightweightLLMStatus?.queue {
                            HStack(spacing: 8) {
                                statBadge("Pending", "\(queue.pending)", queue.pending > 0 ? gOrange : gGray)
                                statBadge("Run", "\(queue.inProgress)", queue.inProgress > 0 ? gBlue : gGray)
                                statBadge("OK", "\(queue.completed)", gGreen)
                                statBadge("Fail", "\(queue.failed)", queue.failed > 0 ? gOrange : gGray)
                            }
                        }
                        if let last = vm.lightweightLLMStatus?.lastResult {
                            Divider()
                            signalRow("Dernier", last.status)
                            signalRow("Type", last.kind)
                            signalRow("Terminé", dashboardAbsoluteTimestamp(last.completedAt))
                            if let error = last.error, !error.isEmpty {
                                signalRow("Erreur", error)
                            }
                        }
                    }
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
        guard eventFilter != "all" else {
            return ordered.filter { $0.type != "user_presence" }
        }
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
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(dashboardPanelBackground)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(
                    accent.map { Color(hex: $0).opacity(0.16) } ?? dashboardStroke,
                    lineWidth: 1
                )
        )
        .overlay(alignment: .topLeading) {
            if let accent {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(Color(hex: accent).opacity(0.22))
                    .frame(width: 2)
                    .padding(.vertical, 10)
            }
        }
    }
}

private struct WorkTimelineSection: View {
    let episodes: [DebugWorkEpisode]
    let commitLinks: [DebugCommitEpisodeLink]
    let unlinkedCommits: [DebugCommitEpisodeLink]

    private var linksByEpisode: [String: [DebugCommitEpisodeLink]] {
        Dictionary(grouping: commitLinks.filter { ($0.status ?? "linked") == "linked" && $0.episodeId != nil && !isSyntheticJournalWindowLink($0) }) {
            $0.episodeId ?? ""
        }
    }

    private var unlinked: [DebugCommitEpisodeLink] {
        let fromLinks = commitLinks.filter { ($0.status == "unlinked") || $0.episodeId == nil }
        return fromLinks + unlinkedCommits
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 14) {
                timelineStat("Épisodes", "\(timelineItems.count)", gOrange)
                timelineStat("Commits liés", "\(commitLinks.filter { ($0.status ?? "linked") == "linked" && $0.episodeId != nil }.count)", gGreen)
                timelineStat("Non reliés", "\(unlinked.count)", gGray)
            }

            if timelineItems.isEmpty {
                GlassCard(accent: gOrange) {
                    HStack {
                        Spacer()
                        Text("Aucun épisode reçu ou route debug indisponible")
                            .font(.system(size: 12))
                            .foregroundStyle(.tertiary)
                        Spacer()
                    }
                    .padding(.vertical, 12)
                }
            } else {
                VStack(alignment: .leading, spacing: 12) {
                    ForEach(timelineItems) { item in
                        WorkEpisodeCard(
                            episode: item.episode,
                            linkedCommits: item.linkedCommits,
                            isSyntheticJournalWindow: item.isSyntheticJournalWindow
                        )
                    }
                }
            }

            UnlinkedCommitsSection(commits: unlinked)
        }
    }

    private var timelineItems: [WorkTimelineItem] {
        buildWorkTimelineItems(episodes: episodes, commitLinks: commitLinks)
    }

    private func timelineStat(_ label: String, _ value: String, _ colorHex: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label)
                .font(.system(size: 10))
                .foregroundStyle(.tertiary)
            Text(value)
                .font(.system(size: 15, weight: .semibold, design: .rounded))
                .foregroundStyle(Color(hex: colorHex))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct WorkTimelineItem: Identifiable {
    let id: String
    let episode: DebugWorkEpisode
    let linkedCommits: [DebugCommitEpisodeLink]
    let isSyntheticJournalWindow: Bool
}

func buildWorkTimelineItems(
    episodes: [DebugWorkEpisode],
    commitLinks: [DebugCommitEpisodeLink]
) -> [WorkTimelineItem] {
    let syntheticLinks = commitLinks.filter { ($0.status ?? "linked") == "linked" && isSyntheticJournalWindowLink($0) }
    let syntheticByEpisode = Dictionary(grouping: syntheticLinks) { $0.episodeId ?? $0.id }
    let syntheticEpisodeIds = Set(syntheticByEpisode.keys)
    let realLinksByEpisode = Dictionary(
        grouping: commitLinks.filter {
            ($0.status ?? "linked") == "linked"
            && $0.episodeId != nil
            && !syntheticEpisodeIds.contains($0.episodeId ?? "")
            && !isSyntheticJournalWindowLink($0)
        }
    ) { $0.episodeId ?? "" }

    var items = episodes.map { episode in
        WorkTimelineItem(
            id: episode.id,
            episode: episode,
            linkedCommits: realLinksByEpisode[episode.id] ?? [],
            isSyntheticJournalWindow: false
        )
    }

    for (episodeId, links) in syntheticByEpisode {
        guard let synthetic = syntheticJournalWindowEpisode(id: episodeId, links: links) else {
            continue
        }
        items.append(WorkTimelineItem(
            id: synthetic.id,
            episode: synthetic,
            linkedCommits: links.sorted(by: commitLinkSortDescending),
            isSyntheticJournalWindow: true
        ))
    }

    return items.sorted {
        (dashboardDate(from: $0.episode.startedAt) ?? .distantPast) > (dashboardDate(from: $1.episode.startedAt) ?? .distantPast)
    }
}

func isSyntheticJournalWindowLink(_ link: DebugCommitEpisodeLink) -> Bool {
    let flags = Set(link.flags ?? [])
    return (link.episodeId ?? "").hasPrefix("journal-file-window-")
        || flags.contains("display_uses_journal_window")
}

private func syntheticJournalWindowEpisode(id: String, links: [DebugCommitEpisodeLink]) -> DebugWorkEpisode? {
    guard let first = links.sorted(by: commitLinkSortAscending).first else {
        return nil
    }
    let startedAt = first.episodeStartedAt ?? first.evidenceStartedAt ?? first.journalStartedAt
    let endedAt = first.episodeEndedAt ?? first.evidenceEndedAt ?? first.journalEndedAt
    return DebugWorkEpisode(
        id: id,
        project: first.project,
        probableTask: "coding",
        activityLevel: "editing",
        startedAt: startedAt,
        endedAt: endedAt,
        durationMin: dashboardDurationMinutes(startedAt: startedAt, endedAt: endedAt),
        evidenceCount: links.count,
        confidence: first.confidence,
        boundaryReason: "journal_file_window",
        uncertaintyFlags: ["display_uses_journal_window"],
        dominantScope: "journal_file_window",
        previousScope: nil,
        nextScope: nil,
        strongEventCount: nil,
        weakEventCount: nil,
        boundaryEventType: nil,
        boundaryEventAt: nil,
        debugReason: "synthetic timeline card from journal-backed commit link"
    )
}

private func commitLinkSortAscending(_ left: DebugCommitEpisodeLink, _ right: DebugCommitEpisodeLink) -> Bool {
    (dashboardDate(from: left.episodeStartedAt ?? left.evidenceStartedAt ?? left.journalStartedAt) ?? .distantPast)
        < (dashboardDate(from: right.episodeStartedAt ?? right.evidenceStartedAt ?? right.journalStartedAt) ?? .distantPast)
}

private func commitLinkSortDescending(_ left: DebugCommitEpisodeLink, _ right: DebugCommitEpisodeLink) -> Bool {
    !commitLinkSortAscending(left, right)
}

private func dashboardDurationMinutes(startedAt: String?, endedAt: String?) -> Int? {
    guard let start = dashboardDate(from: startedAt), let end = dashboardDate(from: endedAt), end >= start else {
        return nil
    }
    return max(Int(end.timeIntervalSince(start) / 60), 1)
}

private struct WorkEpisodeCard: View {
    let episode: DebugWorkEpisode
    let linkedCommits: [DebugCommitEpisodeLink]
    var isSyntheticJournalWindow: Bool = false

    private var status: EpisodeStatus {
        if isSyntheticJournalWindow {
            return .solid
        }
        if isDeliveryPhase {
            return .delivery
        }
        if episode.boundaryReason == "end_of_events" {
            return .ongoing
        }
        let scope = episode.dominantScope ?? "unknown"
        let hasTemporalCommit = linkedCommits.contains { ($0.flags ?? []).contains("temporal_only_link") || ($0.flags ?? []).contains("no_file_scope_match") }
        if (episode.durationMin ?? 0) <= 2 || scope == "unknown" || (episode.strongEventCount ?? 0) <= 1 || hasTemporalCommit {
            return .needsReview
        }
        if (episode.confidence ?? 0) < 0.75 {
            return .probable
        }
        if (episode.strongEventCount ?? 0) >= 5 && scope != "unknown" {
            return .solid
        }
        return .probable
    }

    private var isDeliveryPhase: Bool {
        isGitDeliveryEpisode(scope: episode.dominantScope, task: episode.probableTask)
    }

    var body: some View {
        GlassCard(accent: status.colorHex) {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text("\(dashboardTime(episode.startedAt)) → \(dashboardTime(episode.endedAt))")
                        .font(.system(size: 14, weight: .semibold, design: .rounded))
                        .foregroundStyle(.primary)
                    Text(dashboardMinutes(episode.durationMin))
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.secondary)
                    Spacer()
                    timelinePill(status.label, color: status.colorHex)
                }

                HStack(spacing: 6) {
                    timelinePill(episode.project ?? "Projet inconnu", color: gBlue)
                    timelinePill(
                        isSyntheticJournalWindow ? "Fenêtre confirmée par le journal" : episodeScopeLabel(scope: episode.dominantScope, task: episode.probableTask),
                        color: isDeliveryPhase ? gGray : gOrange
                    )
                    timelinePill(taskLabel(episode.probableTask), color: gGray)
                }

                Text(episodeSummary)
                    .font(.system(size: 13))
                    .foregroundStyle(.primary)
                    .fixedSize(horizontal: false, vertical: true)

                HStack(spacing: 14) {
                    compactMetric("Strong", "\(episode.strongEventCount ?? 0)", gGreen)
                    compactMetric("Weak", "\(episode.weakEventCount ?? 0)", gGray)
                    compactMetric("Fin", boundaryLabel(episode.boundaryReason), status.colorHex)
                    if let confidence = episode.confidence {
                        compactMetric("Confiance séquence", dashboardScore(confidence), gBlue)
                    }
                }

                EpisodeLinkedCommitsView(commits: linkedCommits)
                DebugDetailsView(episode: episode, commits: linkedCommits)
            }
        }
    }

    private var episodeSummary: String {
        let scope = episode.dominantScope ?? "unknown"
        let task = episode.probableTask ?? "general"
        if isSyntheticJournalWindow {
            return "Travail confirmé par le journal et rattaché par les fichiers du commit."
        }
        if isDeliveryPhase {
            return "Phase de livraison ou de contrôle Git, distincte du travail qui a produit le commit."
        }
        if episode.boundaryReason == "end_of_events" {
            return "Pulse observe encore cette séquence de travail."
        }
        if (episode.durationMin ?? 0) <= 2 && (episode.strongEventCount ?? 0) <= 1 {
            return "Courte activité isolée, probablement à vérifier."
        }
        switch scope {
        case "routes":
            return "Pulse a détecté une séquence de travail sur les routes debug mémoire."
        case "work_episode":
            return "Pulse pense que tu as travaillé sur les épisodes de travail."
        case "tests":
            return "Pulse pense que tu as travaillé sur les tests."
        case "memory":
            return "Pulse a détecté une séquence de travail sur la mémoire Pulse."
        case "app_swift":
            return "Pulse a détecté une séquence de travail sur l’app Swift."
        case "git":
            return "Activité de livraison ou de contrôle Git détectée."
        case "unknown":
            return "Pulse a détecté du travail, mais le contexte reste incertain."
        default:
            if task == "tests" {
                return "Pulse pense que tu as travaillé sur les tests et la validation."
            }
            return "Pulse a détecté une séquence de travail \(taskLabel(task).lowercased())."
        }
    }

    private func compactMetric(_ label: String, _ value: String, _ colorHex: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(.tertiary)
            Text(value)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(Color(hex: colorHex))
                .lineLimit(1)
        }
    }
}

private struct EpisodeLinkedCommitsView: View {
    let commits: [DebugCommitEpisodeLink]

    var body: some View {
        if !commits.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Text("Commits liés")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(.secondary)
                    .textCase(.uppercase)
                    .tracking(0.4)
                ForEach(commits) { commit in
                    VStack(alignment: .leading, spacing: 5) {
                        HStack(alignment: .firstTextBaseline) {
                            Text(commit.commitSubject ?? "Commit sans sujet")
                                .font(.system(size: 12, weight: .semibold))
                                .foregroundStyle(.primary)
                                .lineLimit(2)
                            Spacer()
                            if let delivered = deliveredAtLabel(commit.deliveredAt) {
                                Text(delivered)
                                    .font(.system(size: 11, weight: .medium))
                                    .foregroundStyle(.secondary)
                            }
                        }
                        HStack(spacing: 6) {
                            if let evidence = commit.evidenceLevel, !evidence.isEmpty {
                                timelinePill(evidenceLabel(evidence), color: gOrange)
                            }
                            ForEach(importantFlags(commit.flags), id: \.self) { flag in
                                timelinePill(flagLabel(flag), color: flagColor(flag))
                            }
                        }
                    }
                    .padding(.vertical, 7)
                    .padding(.horizontal, 10)
                    .background(Color.white.opacity(0.035))
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                }
            }
        }
    }
}

private struct UnlinkedCommitsSection: View {
    let commits: [DebugCommitEpisodeLink]

    var body: some View {
        if !commits.isEmpty {
            GlassCard(accent: gGray) {
                VStack(alignment: .leading, spacing: 10) {
                    Label("Commits non reliés", systemImage: "link.badge.plus")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(.secondary)
                        .textCase(.uppercase)
                        .tracking(0.4)

                    ForEach(commits.prefix(10)) { commit in
                        VStack(alignment: .leading, spacing: 5) {
                            HStack(alignment: .firstTextBaseline) {
                                Text(commit.commitSubject ?? "Commit sans sujet")
                                    .font(.system(size: 12, weight: .semibold))
                                    .foregroundStyle(.primary)
                                    .lineLimit(2)
                                Spacer()
                                Text(dashboardTime(commit.deliveredAt))
                                    .font(.system(size: 11))
                                    .foregroundStyle(.secondary)
                            }
                            Text("Aucun épisode fermé plausible au moment du commit.")
                                .font(.system(size: 11))
                                .foregroundStyle(.secondary)
                            HStack(spacing: 6) {
                                ForEach(importantFlags(commit.flags), id: \.self) { flag in
                                    timelinePill(flagLabel(flag), color: flagColor(flag))
                                }
                            }
                        }
                        .padding(.vertical, 6)
                    }
                }
            }
        }
    }
}

private struct DebugDetailsView: View {
    let episode: DebugWorkEpisode
    let commits: [DebugCommitEpisodeLink]

    var body: some View {
        DisclosureGroup {
            VStack(alignment: .leading, spacing: 5) {
                debugLine("debug_reason", episode.debugReason)
                debugLine("boundary_reason", episode.boundaryReason)
                debugLine("dominant_scope", episode.dominantScope)
                debugLine("probable_task", episode.probableTask)
                debugLine("flags", episode.uncertaintyFlags?.joined(separator: ", "))
                if !commits.isEmpty {
                    debugLine("commit_flags", commits.flatMap { $0.flags ?? [] }.joined(separator: ", "))
                    debugLine("commit_link_reason", commits.map { $0.linkReason ?? "—" }.joined(separator: ", "))
                    debugLine("commit_evidence", commits.map { $0.evidenceLevel ?? "—" }.joined(separator: ", "))
                    debugLine("candidate_id", commits.map { $0.candidateId ?? "—" }.joined(separator: ", "))
                    debugLine("evidence_candidate_id", commits.map { $0.evidenceCandidateId ?? "—" }.joined(separator: ", "))
                    debugLine("display_episode_window", commits.compactMap(commitLinkDisplayEpisodeWindowLabel).joined(separator: " · "))
                    debugLine("evidence_window", commits.compactMap(commitLinkEvidenceWindowLabel).joined(separator: " · "))
                    debugLine("journal_window", commits.compactMap(commitLinkJournalWindowLabel).joined(separator: " · "))
                }
            }
            .padding(.top, 6)
        } label: {
            Text("Détails debug")
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(.tertiary)
        }
        .font(.system(size: 10))
        .foregroundStyle(.tertiary)
    }

    private func debugLine(_ label: String, _ value: String?) -> some View {
        HStack(alignment: .top, spacing: 6) {
            Text(label)
                .font(.system(size: 10, design: .monospaced))
                .foregroundStyle(.tertiary)
                .frame(width: 95, alignment: .leading)
            Text(value?.isEmpty == false ? value! : "—")
                .font(.system(size: 10, design: .monospaced))
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
        }
    }
}

private enum EpisodeStatus {
    case solid
    case probable
    case needsReview
    case ongoing
    case delivery

    var label: String {
        switch self {
        case .solid: return "Solide"
        case .probable: return "Probable"
        case .needsReview: return "À vérifier"
        case .ongoing: return "En cours"
        case .delivery: return "Livraison"
        }
    }

    var colorHex: String {
        switch self {
        case .solid: return gGreen
        case .probable: return gBlue
        case .needsReview: return gOrange
        case .ongoing: return gPurple
        case .delivery: return gGray
        }
    }
}

private func timelinePill(_ text: String, color: String) -> some View {
    Text(text)
        .font(.system(size: 10, weight: .medium))
        .foregroundStyle(Color(hex: color))
        .lineLimit(1)
        .padding(.horizontal, 7)
        .padding(.vertical, 3)
        .background(Color(hex: color).opacity(0.12))
        .clipShape(Capsule())
}

private func dashboardTime(_ raw: String?) -> String {
    guard let date = dashboardDate(from: raw) else { return "—" }
    let formatter = DateFormatter()
    formatter.locale = Locale(identifier: "fr_FR")
    formatter.timeZone = .current
    formatter.timeStyle = .short
    formatter.dateStyle = .none
    return formatter.string(from: date)
}

func scopeLabel(_ scope: String?) -> String {
    switch scope {
    case "app_swift": return "App Swift"
    case "routes": return "Routes"
    case "memory": return "Mémoire"
    case "work_episode": return "Séquences debug"
    case "tests": return "Tests"
    case "git": return "Git"
    case "extractor": return "Extracteur"
    case "docs": return "Docs"
    case "daemon_python": return "Daemon Python"
    case "unknown", nil: return "Contexte incertain"
    default: return scope ?? "Contexte incertain"
    }
}

func isGitDeliveryEpisode(scope: String?, task: String?) -> Bool {
    scope == "git" || task == "terminal_execution"
}

func episodeScopeLabel(scope: String?, task: String?) -> String {
    if isGitDeliveryEpisode(scope: scope, task: task) {
        return "Phase Git / livraison"
    }
    return scopeLabel(scope)
}

private func taskLabel(_ task: String?) -> String {
    switch task {
    case "coding": return "Code"
    case "tests": return "Tests"
    case "writing": return "Rédaction"
    case "version_control": return "Livraison"
    case "debug": return "Debug"
    case "build": return "Build"
    case "general", nil: return "Travail"
    default: return task ?? "Travail"
    }
}

private func boundaryLabel(_ boundary: String?) -> String {
    switch boundary {
    case "screen_locked": return "Verrouillage"
    case "non_work_title": return "Hors travail"
    case "scope_change": return "Changement"
    case "long_gap": return "Pause"
    case "weak_after_strong_timeout": return "Signal faible"
    case "end_of_events": return "Ouvert"
    default: return boundary ?? "—"
    }
}

func evidenceLabel(_ evidence: String) -> String {
    switch evidence {
    case "file_scope": return "Rattaché par fichiers"
    case "temporal_only": return "Lien temporel à vérifier"
    default: return evidence
    }
}

func importantFlags(_ flags: [String]?) -> [String] {
    let priority = [
        "linked_by_journal_file_window",
        "work_episode_link",
        "delayed_delivery",
        "temporal_only_link",
        "ambiguous_candidates",
        "commit_only_journal_entry",
    ]
    let present = Set(flags ?? [])
    return priority.filter { present.contains($0) }
}

func flagLabel(_ flag: String) -> String {
    switch flag {
    case "linked_by_journal_file_window": return "Fenêtre confirmée par le journal"
    case "work_episode_link": return "Commit rattaché au travail"
    case "delayed_delivery": return "Livré après le travail"
    case "temporal_only_link": return "Lien temporel à vérifier"
    case "no_file_scope_match": return "Sans fichiers"
    case "ambiguous_candidates": return "Ambigu"
    case "commit_only_journal_entry": return "Commit seul"
    case "delivery_after_episode": return "Livré après"
    case "delivery_near_candidate_end": return "Livraison proche de cet épisode"
    default: return flag
    }
}

func flagColor(_ flag: String) -> String {
    switch flag {
    case "linked_by_journal_file_window", "work_episode_link": return gGreen
    case "delayed_delivery": return gBlue
    case "ambiguous_candidates", "commit_only_journal_entry", "delivery_after_episode": return gOrange
    case "no_file_scope_match", "temporal_only_link": return gGray
    default: return gBlue
    }
}

func deliveredAtLabel(_ raw: String?) -> String? {
    let time = dashboardTime(raw)
    return time == "—" ? nil : "Livré à \(time)"
}

func commitLinkDisplayEpisodeWindowLabel(_ link: DebugCommitEpisodeLink) -> String? {
    guard link.episodeStartedAt != nil || link.episodeEndedAt != nil else { return nil }
    return "Épisode affiché : \(dashboardAbsoluteTimestamp(link.episodeStartedAt)) → \(dashboardAbsoluteTimestamp(link.episodeEndedAt))"
}

func commitLinkEvidenceWindowLabel(_ link: DebugCommitEpisodeLink) -> String? {
    guard link.evidenceStartedAt != nil || link.evidenceEndedAt != nil else { return nil }
    let source = link.evidenceSource.map { " (\($0))" } ?? ""
    return "Preuve de rattachement\(source) : \(dashboardAbsoluteTimestamp(link.evidenceStartedAt)) → \(dashboardAbsoluteTimestamp(link.evidenceEndedAt))"
}

func commitLinkJournalWindowLabel(_ link: DebugCommitEpisodeLink) -> String? {
    guard link.journalStartedAt != nil || link.journalEndedAt != nil else { return nil }
    return "Fenêtre journal : \(dashboardAbsoluteTimestamp(link.journalStartedAt)) → \(dashboardAbsoluteTimestamp(link.journalEndedAt))"
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

private func dashboardShortTime(_ raw: String?) -> String {
    guard let date = dashboardDate(from: raw) else { return "—" }
    return DashboardDateFormatting.shortTime.string(from: date)
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

    static let shortTime: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "fr_FR")
        f.timeZone = .current
        f.dateFormat = "HH:mm"
        return f
    }()
}
