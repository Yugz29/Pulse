import SwiftUI
import Combine
import AppKit

private let pureBlack = Color(red: 0, green: 0, blue: 0)
private let startupExtensionHeight: CGFloat = 22

// --- ViewModel ---
@MainActor
class PulseViewModel: ObservableObject {

    @Published var isExpanded        = false
    @Published var isStartupExpanded = false
    @Published var isStartupVisible  = false
    @Published var isHovering        = false
    @Published var isFullscreen      = false
    @Published var isDaemonActive    = false
    @Published var inputText         = ""

    @Published var activeProject: String?   = nil
    @Published var activeApp: String?       = nil
    @Published var sessionDuration: Int     = 0
    @Published var pendingCommand: CommandAnalysis? = nil

    private let bridge = DaemonBridge()

    var currentPanelHeight: CGFloat {
        pendingCommand != nil ? NotchWindow.commandHeight : NotchWindow.dashboardHeight
    }

    private var pollTask: Task<Void, Never>?

    func startMcpPolling() {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            guard let self else { return }
            while !Task.isCancelled {
                let alive = await self.bridge.ping()
                self.isDaemonActive = alive
                if alive, let cmd = try? await self.bridge.fetchPendingCommand() {
                    withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) {
                        self.pendingCommand = cmd
                        self.isExpanded = true
                    }
                }
                try? await Task.sleep(nanoseconds: 500_000_000)
            }
        }
    }

    func stopMcpPolling() { pollTask?.cancel(); pollTask = nil }

    func toggle() {
        withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) { isExpanded.toggle() }
        if isExpanded { refreshState() }
    }

    func refreshState() {
        Task {
            guard let state = try? await bridge.getState() else { return }
            self.activeProject   = state.activeProject
            self.activeApp       = state.activeApp
            self.sessionDuration = state.sessionDurationMin
        }
    }

    func sendDecision(allow: Bool) {
        guard let command = pendingCommand else { return }
        Task {
            try? await bridge.sendMcpDecision(toolUseId: command.toolUseId, allow: allow)
            self.pendingCommand = nil
            self.isExpanded     = false
        }
    }

    func triggerStartupAnimation() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            withAnimation(.spring(response: 0.5, dampingFraction: 0.8)) { self.isStartupExpanded = true }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { self.isStartupVisible = true }
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) {
            withAnimation(.spring(response: 0.5, dampingFraction: 0.85)) {
                self.isStartupVisible  = false
                self.isStartupExpanded = false
            }
        }
    }
}


// MARK: - NotchRootView

struct NotchRootView: View {
    @ObservedObject var vm: PulseViewModel

    var notchWidth: CGFloat {
        guard let screen = NotchWindow.displayScreen() else { return 200 }
        return NotchWindow.realNotchWidth(for: screen)
    }
    var notchHeight: CGFloat {
        NotchWindow.displayScreen()?.safeAreaInsets.top ?? 37
    }
    let panelWidth:  CGFloat = NotchWindow.panelWidth

    var panelHeight: CGFloat { vm.currentPanelHeight }

    var shapePanelWidth: CGFloat {
        vm.isExpanded ? panelWidth : notchWidth
    }

    var shapePanelHeight: CGFloat {
        if vm.isExpanded        { return panelHeight }
        if vm.isStartupExpanded { return startupExtensionHeight }
        return 0
    }

    var hoverExtra: CGFloat {
        guard vm.isHovering && !vm.isExpanded && !vm.isStartupExpanded else { return 0 }
        return 8
    }

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .top) {

                NotchPanelShape(
                    bottomCornerRadius: 12,
                    notchWidth:  notchWidth,
                    notchHeight: notchHeight,
                    panelWidth:  shapePanelWidth,
                    panelHeight: shapePanelHeight + hoverExtra
                )
                .fill(pureBlack)
                .frame(width: geo.size.width)
                .animation(.bouncy.speed(1.2), value: vm.isHovering)
                .animation(.spring(response: 0.5, dampingFraction: 0.82), value: vm.isStartupExpanded)
                .animation(.spring(response: 0.42, dampingFraction: 0.82), value: vm.isExpanded)

                if vm.isStartupVisible && vm.isStartupExpanded {
                    HStack(spacing: 6) {
                        Circle()
                            .fill(Color(hex: "#ff453a"))
                            .frame(width: 5, height: 5)
                        Text("Pulse est actif")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundColor(.white.opacity(0.6))
                    }
                    .frame(width: notchWidth)
                    .offset(y: notchHeight + 3)
                    .transition(.opacity)
                }

                if vm.isExpanded {
                    Group {
                        if let command = vm.pendingCommand {
                            CommandTranslationView(command: command, vm: vm)
                        } else {
                            DashboardView(vm: vm)
                        }
                    }
                    .frame(width: panelWidth)
                    .offset(y: notchHeight)
                    .transition(.opacity.combined(with: .move(edge: .top)))
                }

                Color.clear
                    .frame(width: notchWidth, height: notchHeight)
                    .contentShape(Rectangle())
                    .onHover { h in withAnimation { vm.isHovering = h } }
                    .onTapGesture { vm.toggle() }
            }
        }
        .opacity(vm.isFullscreen ? 0 : 1)
        .onAppear {
            vm.refreshState()
            vm.startMcpPolling()
            vm.triggerStartupAnimation()
        }
    }
}


// MARK: - DashboardView

struct DashboardView: View {
    @ObservedObject var vm: PulseViewModel

    var appLabel: String {
        if let p = vm.activeProject { return p }
        if let a = vm.activeApp    { return a }
        return vm.isDaemonActive ? "Pulse" : "Inactif"
    }

    var dotColor: Color {
        vm.isDaemonActive ? Color(hex: "#5DCAA5") : Color(hex: "#ff453a")
    }

    var body: some View {
        HStack(spacing: 12) {
            HStack(spacing: 7) {
                Circle().fill(dotColor).frame(width: 7, height: 7)
                Text(appLabel)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundColor(.white.opacity(0.88))
                    .lineLimit(1)
                if vm.sessionDuration > 0 {
                    Text("·").foregroundColor(.white.opacity(0.25))
                    Text("\(vm.sessionDuration) min")
                        .font(.system(size: 12))
                        .foregroundColor(.white.opacity(0.35))
                }
            }

            Spacer()

            HStack(spacing: 6) {
                TextField("Demande…", text: $vm.inputText)
                    .font(.system(size: 12))
                    .foregroundColor(.white.opacity(0.75))
                    .textFieldStyle(.plain)
                    .onSubmit { vm.inputText = "" }
                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 15))
                    .foregroundColor(.white.opacity(0.25))
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(Color.white.opacity(0.09))
            .clipShape(Capsule())
            .frame(width: 150)
        }
        .padding(.horizontal, 18)
        .frame(height: NotchWindow.dashboardHeight)
    }
}


// MARK: - CommandTranslationView

struct CommandTranslationView: View {
    let command: CommandAnalysis
    @ObservedObject var vm: PulseViewModel

    var riskColor: Color {
        switch command.riskLevel {
        case "safe", "low":      return Color(hex: "#5DCAA5")
        case "medium":           return Color(hex: "#EF9F27")
        case "high", "critical": return Color(hex: "#ff453a")
        default:                 return Color(hex: "#888780")
        }
    }

    var riskIcon: String {
        switch command.riskLevel {
        case "safe", "low": return "checkmark.shield.fill"
        case "medium":      return "exclamationmark.triangle.fill"
        case "high":        return "exclamationmark.octagon.fill"
        case "critical":    return "xmark.shield.fill"
        default:            return "questionmark.circle.fill"
        }
    }

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: riskIcon)
                .font(.system(size: 18, weight: .medium))
                .foregroundColor(riskColor)
                .frame(width: 28)

            VStack(alignment: .leading, spacing: 2) {
                Text(command.translated)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundColor(.white.opacity(0.90))
                    .lineLimit(2)
                Text(command.command)
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundColor(.white.opacity(0.28))
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            HStack(spacing: 6) {
                pillButton("Autoriser") { vm.sendDecision(allow: true) }
                    .foregroundColor(Color(hex: "#5DCAA5"))
                pillButton("Refuser") { vm.sendDecision(allow: false) }
                    .foregroundColor(Color(hex: "#ff453a"))
            }
        }
        .padding(.horizontal, 18)
        .frame(height: NotchWindow.commandHeight)
    }
}


// MARK: - Bouton pill

private func pillButton(_ label: String, action: @escaping () -> Void) -> some View {
    Button(action: action) {
        Text(label)
            .font(.system(size: 12, weight: .medium))
            .padding(.horizontal, 14)
            .padding(.vertical, 7)
            .background(Color.white.opacity(0.10))
            .clipShape(Capsule())
    }
    .buttonStyle(.plain)
}


// MARK: - Extension couleur hex

extension Color {
    init(hex: String) {
        let hex = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var int: UInt64 = 0
        Scanner(string: hex).scanHexInt64(&int)
        let r = Double((int >> 16) & 0xFF) / 255
        let g = Double((int >> 8)  & 0xFF) / 255
        let b = Double(int         & 0xFF) / 255
        self.init(red: r, green: g, blue: b)
    }
}
