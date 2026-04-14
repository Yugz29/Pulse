import SwiftUI

private struct ServiceStateDot: View {
    let color: Color
    let isTransitioning: Bool

    var body: some View {
        Circle()
            .fill(color)
            .frame(width: 6, height: 6)
            .opacity(isTransitioning ? 0.6 : 1)
            .animation(
                isTransitioning
                    ? .easeInOut(duration: 0.8).repeatForever(autoreverses: true)
                    : .easeOut(duration: 0.15),
                value: isTransitioning
            )
    }
}

private struct RoundIconButton: View {
    let systemName: String
    let foregroundColor: Color
    let backgroundOpacity: Double
    let action: () -> Void

    init(
        _ systemName: String,
        foregroundColor: Color = .white.opacity(0.55),
        backgroundOpacity: Double = 0.07,
        action: @escaping () -> Void
    ) {
        self.systemName = systemName
        self.foregroundColor = foregroundColor
        self.backgroundOpacity = backgroundOpacity
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.system(size: 10, weight: .semibold))
                .foregroundColor(foregroundColor)
                .frame(width: 24, height: 24)
                .background(Color.white.opacity(backgroundOpacity))
                .clipShape(Circle())
        }
        .buttonStyle(.plain)
    }
}

private struct RoundIconMenu<Content: View>: View {
    let systemName: String
    let isDisabled: Bool
    @ViewBuilder let content: () -> Content

    var body: some View {
        Menu {
            content()
        } label: {
            Image(systemName: systemName)
                .font(.system(size: 10, weight: .semibold))
                .foregroundColor(.white.opacity(0.55))
                .frame(width: 24, height: 24)
                .background(Color.white.opacity(0.07))
                .clipShape(Circle())
        }
        .menuStyle(.borderlessButton)
        .disabled(isDisabled)
    }
}

private struct ServiceRow<Accessory: View>: View {
    let label: String
    let sublabel: String
    let dotColor: Color
    let isTransitioning: Bool
    let sublabelColor: Color
    @ViewBuilder let accessory: () -> Accessory

    var body: some View {
        HStack(spacing: 10) {
            ServiceStateDot(color: dotColor, isTransitioning: isTransitioning)
            VStack(alignment: .leading, spacing: 1) {
                Text(label)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundColor(.white.opacity(0.82))
                Text(sublabel)
                    .font(.system(size: 10))
                    .foregroundColor(sublabelColor)
                    .lineLimit(1)
            }
            Spacer()
            accessory()
        }
        .padding(.vertical, 9)
    }
}

struct DaemonRow: View {
    @ObservedObject var controller: DaemonController

    private var dotColor: Color {
        switch controller.state {
        case .running:
            return Color(hex: "#5DCAA5")
        case .paused, .starting, .restarting:
            return Color(hex: "#EF9F27")
        default:
            return Color(hex: "#4a4a4c")
        }
    }

    private var isTransitioning: Bool {
        switch controller.state {
        case .starting, .stopping, .restarting:
            return true
        default:
            return false
        }
    }

    var body: some View {
        ServiceRow(
            label: "Daemon Python",
            sublabel: controller.lastError ?? "localhost:8765",
            dotColor: dotColor,
            isTransitioning: isTransitioning,
            sublabelColor: controller.lastError != nil
                ? Color(hex: "#ff453a").opacity(0.8)
                : .white.opacity(0.38),
            accessory: {
                if !isTransitioning {
                    HStack(spacing: 6) {
                        if controller.state == .running {
                            RoundIconButton("pause.fill") { controller.pause() }
                            RoundIconButton("arrow.clockwise") { controller.restart() }
                            RoundIconButton("stop.fill") { controller.stop() }
                        } else if controller.state == .paused {
                            RoundIconButton("play.fill") { controller.resume() }
                            RoundIconButton("stop.fill") { controller.stop() }
                        } else {
                            RoundIconButton("play.fill") { controller.start() }
                        }
                    }
                } else {
                    ProgressView()
                        .controlSize(.small)
                        .tint(.white.opacity(0.4))
                }
            }
        )
    }
}

struct StatusView: View {
    @ObservedObject var vm: PulseViewModel

    private var llmMenu: some View {
        RoundIconMenu(
            systemName: "slider.horizontal.3",
            isDisabled: vm.availableModels.isEmpty || vm.isUpdatingModel
        ) {
            if vm.availableModels.isEmpty {
                Text("Aucun modèle détecté")
            } else {
                ForEach(vm.availableModels, id: \.self) { model in
                    Button(model) { vm.updateSelectedModel(model) }
                }
            }
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            DaemonRow(controller: vm.daemonController)

            Divider().background(Color.white.opacity(0.06))

            let obsEffective = vm.isDaemonActive
                && vm.isObservingEnabled
                && vm.daemonController.state != .paused
            ServiceRow(
                label: "Observation",
                sublabel: vm.daemonController.state == .paused
                    ? "daemon en pause"
                    : (vm.isObservingEnabled ? "apps · fichiers · clipboard" : "suspendue"),
                dotColor: obsEffective ? Color(hex: "#5DCAA5") : Color(hex: "#4a4a4c"),
                isTransitioning: false,
                sublabelColor: .white.opacity(0.38),
                accessory: {
                    if vm.isDaemonActive {
                        if vm.isObservingEnabled {
                            RoundIconButton("pause.fill") { vm.toggleObservation() }
                        } else {
                            RoundIconButton("play.fill") { vm.toggleObservation() }
                        }
                    } else {
                        Text("—")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundColor(Color(hex: "#4a4a4c"))
                    }
                }
            )

            Divider().background(Color.white.opacity(0.06))

            ServiceRow(
                label: "LLM",
                sublabel: vm.llmStatusSubtitle,
                dotColor: vm.isLLMReady ? Color(hex: "#5DCAA5") : Color(hex: "#4a4a4c"),
                isTransitioning: false,
                sublabelColor: .white.opacity(0.38),
                accessory: {
                        HStack(spacing: 6) {
                            RoundIconButton("arrow.clockwise") {
                            Task {
                                let ok = await vm.refreshModels()
                                await MainActor.run {
                                    if ok {
                                        vm.showTransientStatus("Modèles rechargés")
                                    } else {
                                        vm.showTransientStatus("Échec rechargement modèles", accent: Color(hex: "#ff453a"))
                                    }
                                }
                            }
                        }

                        if vm.isUpdatingModel {
                            ProgressView()
                                .controlSize(.small)
                                .tint(.white.opacity(0.4))
                                .frame(width: 24, height: 24)
                        } else {
                            llmMenu
                        }
                    }
                }
            )
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 10)
        .frame(height: NotchWindow.statusHeight - .panelContentGap, alignment: .top)
    }
}

struct SettingsView: View {
    var body: some View {
        Color.clear
            .frame(height: NotchWindow.settingsHeight - .panelContentGap)
    }
}

struct CommandTranslationView: View {
    let command: CommandAnalysis
    @ObservedObject var vm: PulseViewModel

    var riskColor: Color {
        switch command.riskLevel {
        case "safe", "low":
            return Color(hex: "#5DCAA5")
        case "medium":
            return Color(hex: "#EF9F27")
        case "high", "critical":
            return Color(hex: "#ff453a")
        default:
            return Color(hex: "#888780")
        }
    }

    var riskIcon: String {
        switch command.riskLevel {
        case "safe", "low":
            return "checkmark.shield.fill"
        case "medium":
            return "exclamationmark.triangle.fill"
        case "high":
            return "exclamationmark.octagon.fill"
        case "critical":
            return "xmark.shield.fill"
        default:
            return "questionmark.circle.fill"
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
        .frame(height: NotchWindow.commandHeight - .panelContentGap)
    }
}

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
