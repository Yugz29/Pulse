import SwiftUI

private func serviceHealthIcon(vm: PulseViewModel) -> String {
    vm.serviceStatus.iconName
}

private func serviceHealthColor(vm: PulseViewModel) -> Color {
    vm.serviceStatus.color
}

private struct NotchHeaderButton: View {
    let systemName: String
    let size: CGFloat
    let baseOpacity: Double
    let hoverOpacity: Double
    let baseBackgroundOpacity: Double
    let hoverBackgroundOpacity: Double
    let baseStrokeOpacity: Double
    let hoverStrokeOpacity: Double
    let hoverScale: CGFloat
    let foregroundColor: Color
    let action: () -> Void

    @State private var isHovering = false

    var body: some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.system(size: size, weight: .semibold))
                .foregroundColor(foregroundColor.opacity(isHovering ? hoverOpacity : baseOpacity))
                .frame(width: 22, height: 22)
                .background(Circle().fill(Color.white.opacity(isHovering ? hoverBackgroundOpacity : baseBackgroundOpacity)))
                .overlay(Circle().stroke(Color.white.opacity(isHovering ? hoverStrokeOpacity : baseStrokeOpacity), lineWidth: 0.8))
                .scaleEffect(isHovering ? hoverScale : 1.0)
        }
        .buttonStyle(.plain)
        .onHover { hovering in
            withAnimation(.easeInOut(duration: 0.15)) {
                isHovering = hovering
            }
        }
    }
}

struct NotchExpandedHeader: View {
    @ObservedObject var vm: PulseViewModel
    let geometryWidth: CGFloat
    let panelWidth: CGFloat
    let notchWidth: CGFloat
    let notchHeight: CGFloat

    private var title: String? {
        switch vm.panelMode {
        case .settings:
            return "Réglages"
        case .status:
            return "Services"
        case .chat:
            return "Pulse"
        case .currentState:
            return "Maintenant"
        case .insight:
            return "Observation"
        case .feed:
            return "Notifications"
        default:
            return nil
        }
    }

    var body: some View {
        ZStack {
            if let title {
                Text(title)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundColor(.white.opacity(0.82))
                    .frame(width: panelWidth, alignment: .center)
                    .frame(height: notchHeight)
            }

            NotchHeaderButton(
                systemName: serviceHealthIcon(vm: vm),
                size: 12,
                baseOpacity: 0.6,
                hoverOpacity: 1.0,
                baseBackgroundOpacity: 0.03,
                hoverBackgroundOpacity: 0.10,
                baseStrokeOpacity: 0.05,
                hoverStrokeOpacity: 0.18,
                hoverScale: 1.0,
                foregroundColor: serviceHealthColor(vm: vm),
                action: { vm.switchMode(.status) }
            )
            .position(x: (geometryWidth - panelWidth) / 2 + 32, y: notchHeight / 2)

            NotchHeaderButton(
                systemName: "waveform.path.ecg",
                size: 11,
                baseOpacity: vm.panelMode == .currentState ? 0.95 : 0.42,
                hoverOpacity: 0.95,
                baseBackgroundOpacity: vm.panelMode == .currentState ? 0.14 : 0.03,
                hoverBackgroundOpacity: 0.14,
                baseStrokeOpacity: vm.panelMode == .currentState ? 0.24 : 0.06,
                hoverStrokeOpacity: 0.24,
                hoverScale: 1.0,
                foregroundColor: .white,
                action: {
                    vm.switchMode(.currentState)
                    if vm.panelMode == .currentState { vm.refreshInsights() }
                }
            )
            .position(x: (geometryWidth - panelWidth) / 2 + 60, y: notchHeight / 2)

            NotchHeaderButton(
                systemName: vm.panelMode == .insight ? "eye.fill" : "eye",
                size: 11,
                baseOpacity: vm.panelMode == .insight ? 0.95 : 0.42,
                hoverOpacity: 0.95,
                baseBackgroundOpacity: vm.panelMode == .insight ? 0.14 : 0.03,
                hoverBackgroundOpacity: 0.14,
                baseStrokeOpacity: vm.panelMode == .insight ? 0.24 : 0.06,
                hoverStrokeOpacity: 0.24,
                hoverScale: 1.0,
                foregroundColor: .white,
                action: {
                    vm.switchMode(.insight)
                    if vm.panelMode == .insight { vm.refreshInsights() }
                }
            )
            .position(x: (geometryWidth - panelWidth) / 2 + 88, y: notchHeight / 2)

            NotchHeaderButton(
                systemName: vm.panelMode == .feed ? "bell.fill" : "bell",
                size: 11,
                baseOpacity: vm.panelMode == .feed ? 0.95 : 0.42,
                hoverOpacity: 0.95,
                baseBackgroundOpacity: vm.panelMode == .feed ? 0.14 : 0.03,
                hoverBackgroundOpacity: 0.14,
                baseStrokeOpacity: vm.panelMode == .feed ? 0.24 : 0.06,
                hoverStrokeOpacity: 0.24,
                hoverScale: 1.0,
                foregroundColor: vm.feedHistory.isEmpty ? .white : Color(hex: "#5DCAA5"),
                action: { vm.switchMode(.feed) }
            )
            .position(x: (geometryWidth - panelWidth) / 2 + 116, y: notchHeight / 2)

            NotchHeaderButton(
                systemName: "gearshape.fill",
                size: 11,
                baseOpacity: 0.42,
                hoverOpacity: 0.95,
                baseBackgroundOpacity: 0.03,
                hoverBackgroundOpacity: 0.14,
                baseStrokeOpacity: 0.06,
                hoverStrokeOpacity: 0.24,
                hoverScale: 1.04,
                foregroundColor: .white,
                action: { vm.switchMode(.settings) }
            )
            .position(x: geometryWidth / 2 + notchWidth / 2 + 24, y: notchHeight / 2)

            NotchHeaderButton(
                systemName: "rectangle.on.rectangle",
                size: 11,
                baseOpacity: 0.42,
                hoverOpacity: 0.95,
                baseBackgroundOpacity: 0.03,
                hoverBackgroundOpacity: 0.14,
                baseStrokeOpacity: 0.06,
                hoverStrokeOpacity: 0.24,
                hoverScale: 1.04,
                foregroundColor: .white,
                action: { vm.onToggleDashboard?() }
            )
            .position(x: geometryWidth / 2 + notchWidth / 2 + 52, y: notchHeight / 2)

            if vm.panelMode == .chat {
                NotchHeaderButton(
                    systemName: "xmark",
                    size: 10,
                    baseOpacity: 0.48,
                    hoverOpacity: 0.95,
                    baseBackgroundOpacity: 0.03,
                    hoverBackgroundOpacity: 0.12,
                    baseStrokeOpacity: 0.06,
                    hoverStrokeOpacity: 0.22,
                    hoverScale: 1.0,
                    foregroundColor: .white,
                    action: { vm.closeChat() }
                )
                .position(x: (geometryWidth - panelWidth) / 2 + 116, y: notchHeight / 2)
            }
        }
        .frame(width: geometryWidth, height: notchHeight)
    }
}
