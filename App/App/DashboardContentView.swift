import SwiftUI

struct DashboardView: View {
    @ObservedObject var vm: PulseViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            NowSummaryCard(vm: vm)

            HStack(spacing: 8) {
                TextField("Demande…", text: $vm.inputText)
                    .font(.system(size: 12))
                    .foregroundColor(.white.opacity(0.75))
                    .textFieldStyle(.plain)
                    .onSubmit { vm.sendMessage() }

                Button(action: { vm.sendMessage() }) {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.system(size: 15))
                        .foregroundColor(
                            vm.inputText.isEmpty
                                ? .white.opacity(0.18)
                                : Color(hex: "#5DCAA5")
                        )
                }
                .buttonStyle(.plain)
                .disabled(vm.inputText.isEmpty)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(Color.white.opacity(0.08))
            .clipShape(Capsule())
        }
        .padding(.horizontal, 18)
        .padding(.top, 12)
        .padding(.bottom, 10)
        .frame(height: NotchWindow.dashboardHeight - .panelContentGap)
    }
}

struct FeedView: View {
    @ObservedObject var vm: PulseViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if vm.feedHistory.isEmpty {
                VStack(spacing: 8) {
                    Image(systemName: "bell.slash")
                        .font(.system(size: 20, weight: .light))
                        .foregroundColor(.white.opacity(0.2))
                    Text("Aucune notification")
                        .font(.system(size: 12))
                        .foregroundColor(.white.opacity(0.3))
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScrollView(.vertical, showsIndicators: false) {
                    VStack(spacing: 0) {
                        ForEach(vm.feedHistory) { event in
                            FeedRow(event: event)
                            Divider().background(Color.white.opacity(0.05))
                        }
                    }
                    .padding(.vertical, 4)
                }
            }
        }
        .padding(.horizontal, 18)
        .frame(height: NotchWindow.feedHeight - .panelContentGap, alignment: .top)
    }
}

struct ResumeCardNotificationView: View {
    @ObservedObject var vm: PulseViewModel

    var body: some View {
        if let card = vm.activeResumeCard {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 8) {
                    Image(systemName: "arrow.clockwise.circle.fill")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundColor(Color(hex: "#5E9EFF"))
                    Text(card.project ?? card.title)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundColor(.white.opacity(0.88))
                        .lineLimit(1)
                    Spacer()
                }

                VStack(alignment: .leading, spacing: 6) {
                    Text(card.summary)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundColor(.white.opacity(0.72))
                        .lineLimit(2)
                    Text(card.lastObjective)
                        .font(.system(size: 12))
                        .foregroundColor(.white.opacity(0.62))
                        .lineLimit(2)
                    Text(card.nextAction)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundColor(Color(hex: "#5DCAA5"))
                        .lineLimit(2)
                }

                HStack(spacing: 8) {
                    Text(card.generatedBy == "llm" ? "LLM + journal" : "journal local")
                        .font(.system(size: 10, weight: .medium))
                        .foregroundColor(.white.opacity(0.32))
                    Spacer()
                    Button {
                        withAnimation(.spring(response: 0.35, dampingFraction: 0.82)) {
                            vm.panelMode = .feed
                        }
                    } label: {
                        Image(systemName: "bell")
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundColor(.white.opacity(0.5))
                            .frame(width: 22, height: 22)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 18)
            .padding(.top, 12)
            .frame(height: card.displayHeight - .panelContentGap, alignment: .top)
            .contentShape(Rectangle())
            .onTapGesture {
                withAnimation(.spring(response: 0.35, dampingFraction: 0.82)) {
                    vm.panelMode = .feed
                }
            }
        } else {
            EmptyView()
        }
    }
}

private struct FeedRow: View {
    let event: FeedEvent

    private var timeLabel: String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "fr_FR")
        formatter.dateFormat = "HH:mm"
        // Parse ISO8601
        let isoFormatter = ISO8601DateFormatter()
        isoFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let date = isoFormatter.date(from: event.timestamp)
            ?? ISO8601DateFormatter().date(from: event.timestamp)
        guard let date else { return "" }
        return formatter.string(from: date)
    }

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: event.icon)
                .font(.system(size: 11, weight: .medium))
                .foregroundColor(Color(hex: event.accentHex))
                .frame(width: 20)

            Text(event.label)
                .font(.system(size: 12, weight: .medium))
                .foregroundColor(.white.opacity(0.82))
                .lineLimit(1)

            Spacer()

            Text(timeLabel)
                .font(.system(size: 10, design: .monospaced))
                .foregroundColor(.white.opacity(0.3))
        }
        .padding(.vertical, 9)
    }
}

struct ChatView: View {
    @ObservedObject var vm: PulseViewModel

    var body: some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView(.vertical, showsIndicators: false) {
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(vm.chatMessages) { message in
                            if !message.content.isEmpty || message.role == "user" || !message.isStreaming {
                                ChatMessageRow(
                                    message: message,
                                    showsCursor: vm.isAsking
                                        && message.id == vm.chatMessages.last?.id
                                        && message.role == "assistant"
                                )
                            }
                        }

                        if let status = vm.activeRequestStatusText {
                            HStack(spacing: 8) {
                                ProgressView()
                                    .controlSize(.small)
                                    .tint(.white.opacity(0.4))
                                Text(status)
                                    .font(.system(size: 12))
                                    .foregroundColor(.white.opacity(0.35))
                            }
                            .padding(.top, 12)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }

                        if let systemMessage = vm.activeRequestSystemMessage {
                            Text(systemMessage)
                                .font(.system(size: 12, weight: .medium))
                                .foregroundColor(Color(hex: "#EF9F27"))
                                .padding(.top, 12)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }

                        if vm.activeRequestStatusText != nil || vm.activeRequestSystemMessage != nil {
                            Color.clear
                            .id("bottom")
                        }
                    }
                    .padding(.horizontal, 18)
                    .frame(maxWidth: .infinity)
                }
                .frame(maxHeight: .infinity)
                .onChange(of: vm.chatMessages.count) {
                    withAnimation { proxy.scrollTo("bottom", anchor: .bottom) }
                }
                .onChange(of: vm.chatMessages.last?.content ?? "") {
                    withAnimation { proxy.scrollTo("bottom", anchor: .bottom) }
                }
                .onChange(of: vm.isAsking) {
                    withAnimation { proxy.scrollTo("bottom", anchor: .bottom) }
                }
            }

            Divider().background(Color.white.opacity(0.06))

            HStack(spacing: 8) {
                TextField("Nouvelle question…", text: $vm.inputText)
                    .font(.system(size: 12))
                    .foregroundColor(.white.opacity(0.75))
                    .textFieldStyle(.plain)
                    .onSubmit { vm.sendMessage() }
                    .disabled(vm.isAsking)

                Button(action: { vm.sendMessage() }) {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.system(size: 15))
                        .foregroundColor(
                            vm.inputText.isEmpty || vm.isAsking
                                ? .white.opacity(0.18)
                                : Color(hex: "#5DCAA5")
                        )
                }
                .buttonStyle(.plain)
                .disabled(vm.inputText.isEmpty || vm.isAsking)

                if vm.isAsking {
                    Button(action: { vm.stopAsking() }) {
                        Image(systemName: "stop.circle")
                            .font(.system(size: 15))
                            .foregroundColor(Color(hex: "#EF9F27"))
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 18)
            .padding(.vertical, 10)
        }
        .frame(height: NotchWindow.chatHeight - .panelContentGap)
    }
}

private struct ChatMessageRow: View {
    let message: ChatMessage
    let showsCursor: Bool

    private var isUser: Bool { message.role == "user" }

    var body: some View {
        HStack {
            if isUser { Spacer(minLength: 30) }

            HStack(alignment: .bottom, spacing: 2) {
                Text(message.content)
                    .font(.system(size: 13))
                    .foregroundColor(isUser ? .white.opacity(0.9) : .white.opacity(0.85))
                    .lineSpacing(4)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)

                if showsCursor {
                    BlinkingCursor()
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .background(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(isUser ? Color.white.opacity(0.09) : Color.white.opacity(0.05))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .stroke(Color.white.opacity(isUser ? 0.08 : 0.04), lineWidth: 0.8)
            )
            .frame(maxWidth: 300, alignment: isUser ? .trailing : .leading)

            if !isUser { Spacer(minLength: 30) }
        }
        .padding(.top, 12)
        .id(message.id)
    }
}

private struct BlinkingCursor: View {
    @State private var visible = true

    var body: some View {
        Rectangle()
            .fill(Color(hex: "#5DCAA5").opacity(visible ? 0.8 : 0))
            .frame(width: 2, height: 14)
            .onAppear {
                withAnimation(.easeInOut(duration: 0.5).repeatForever(autoreverses: true)) {
                    visible = false
                }
            }
    }
}

struct NowSummaryCard: View {
    @ObservedObject var vm: PulseViewModel

    private var taskColor: Color {
        switch vm.probableTask {
        case "coding": return Color(hex: "#5DCAA5")
        case "debug": return Color(hex: "#ff453a")
        case "writing": return Color(hex: "#5E9EFF")
        case "exploration", "browsing": return Color(hex: "#EF9F27")
        default: return Color(hex: "#7c7c80")
        }
    }

    private var focusColor: Color {
        switch vm.focusLevel {
        case "deep": return Color(hex: "#5DCAA5")
        case "scattered": return Color(hex: "#EF9F27")
        case "idle": return Color(hex: "#7c7c80")
        default: return Color(hex: "#5DCAA5")
        }
    }

    private var currentAppLabel: String {
        if let project = vm.activeProject, !project.isEmpty { return project }
        return vm.activeApp ?? (vm.isDaemonActive ? "Contexte non détecté" : "Inactif")
    }

    private var currentFileLabel: String {
        guard let file = vm.activeFile, !file.isEmpty else { return "Aucun fichier actif" }
        return URL(fileURLWithPath: file).lastPathComponent
    }

    private var taskLabel: String {
        switch vm.probableTask {
        case "coding":   return "Développement"
        case "debug":    return "Débogage"
        case "writing":  return "Rédaction"
        case "exploration", "browsing": return "Exploration"
        default:         return "Général"
        }
    }

    private var focusLabel: String {
        switch vm.focusLevel {
        case "deep": return "profond"
        case "scattered": return "fragmenté"
        case "idle": return "faible"
        default: return "normal"
        }
    }

    private var frictionLabel: String {
        switch vm.frictionScore {
        case 0.6...: return "élevée"
        case 0.3...: return "moyenne"
        default: return "faible"
        }
    }

    private var frictionColor: Color {
        if vm.frictionScore > 0.6 { return Color(hex: "#ff453a") }
        if vm.frictionScore > 0.3 { return Color(hex: "#EF9F27") }
        return Color(hex: "#5DCAA5")
    }

    private var isPresenceOnly: Bool {
        vm.probableTask == "general"
    }

    private var cardOpacity: Double {
        isPresenceOnly ? 0.6 : 1.0
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .top, spacing: 12) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(currentAppLabel)
                            .font(.system(size: 13, weight: isPresenceOnly ? .regular : .semibold))
                            .foregroundColor(.white.opacity(isPresenceOnly ? 0.52 : 0.84))
                            .lineLimit(1)
                        Text(currentFileLabel)
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundColor(.white.opacity(0.30))
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }

                    Spacer()

                    if vm.frictionScore >= 0.3 {
                        VStack(alignment: .trailing, spacing: 5) {
                            Text("Friction")
                                .font(.system(size: 9, weight: .semibold))
                                .foregroundColor(.white.opacity(0.32))
                            Text(frictionLabel)
                                .font(.system(size: 11, weight: .semibold))
                                .foregroundColor(frictionColor)
                                .padding(.horizontal, 8)
                                .padding(.vertical, 4)
                                .background(frictionColor.opacity(0.14))
                                .clipShape(Capsule())
                        }
                    }
                }

                HStack(spacing: 8) {
                    if !isPresenceOnly {
                        summaryMetric(label: "Tâche", value: taskLabel, tint: taskColor)
                        summaryMetric(label: "Focus", value: focusLabel, tint: focusColor)
                    }
                    summaryMetric(
                        label: isPresenceOnly ? "Présence" : "Session",
                        value: "\(max(vm.sessionDuration, 0)) min",
                        tint: isPresenceOnly ? Color.white.opacity(0.22) : Color.white.opacity(0.42)
                    )
                }

                if !vm.recentApps.isEmpty {
                    HStack(spacing: 6) {
                        Image(systemName: "square.stack.3d.up")
                            .font(.system(size: 10, weight: .medium))
                            .foregroundColor(.white.opacity(0.28))
                        Text(vm.recentApps.prefix(4).joined(separator: " · "))
                            .font(.system(size: 10))
                            .foregroundColor(.white.opacity(0.36))
                            .lineLimit(1)
                    }
                }
            }
            .padding(12)
            .background(Color.white.opacity(0.045))
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        }
    }

    private func summaryMetric(label: String, value: String, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label)
                .font(.system(size: 9, weight: .semibold))
                .foregroundColor(.white.opacity(0.3))
            HStack(spacing: 5) {
                Circle()
                    .fill(tint)
                    .frame(width: 5, height: 5)
                Text(value)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundColor(.white.opacity(0.74))
                    .lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(Color.white.opacity(0.035))
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}
