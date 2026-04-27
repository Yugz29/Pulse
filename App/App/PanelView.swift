import SwiftUI

private let pureBlack = Color(red: 0, green: 0, blue: 0)
private let startupExtensionHeight: CGFloat = 22
private let panelHeaderGap: CGFloat = 12

struct NotchRootView: View {
    @ObservedObject var vm: PulseViewModel

    var notchWidth: CGFloat {
        guard let screen = NotchWindow.displayScreen() else { return 200 }
        return NotchWindow.realNotchWidth(for: screen)
    }

    var notchHeight: CGFloat { NotchWindow.displayScreen()?.safeAreaInsets.top ?? 37 }
    let panelWidth: CGFloat = NotchWindow.panelWidth
    var panelHeight: CGFloat { vm.currentPanelHeight }

    var shapePanelWidth: CGFloat { vm.isExpanded ? panelWidth : notchWidth + (hoverExtra * 2) }

    var shapePanelHeight: CGFloat {
        if vm.isExpanded { return panelHeight }
        if vm.isStartupExpanded { return startupExtensionHeight }
        return 0
    }

    var hoverExtra: CGFloat {
        guard vm.isHovering && !vm.isExpanded && !vm.isStartupExpanded else { return 0 }
        // +8 pour compenser le décalage rt des coins concaves dans openPanelPath
        return 16
    }

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .top) {
                NotchPanelShape(
                    bottomCornerRadius: 12,
                    notchWidth: notchWidth,
                    notchHeight: notchHeight,
                    panelWidth: shapePanelWidth,
                    panelHeight: shapePanelHeight + hoverExtra
                )
                .fill(pureBlack)
                .frame(width: geo.size.width)
                .animation(.bouncy.speed(1.2), value: vm.isHovering)
                .animation(.spring(response: 0.5, dampingFraction: 0.82), value: vm.isStartupExpanded)
                .animation(.spring(response: 0.42, dampingFraction: 0.82), value: vm.isExpanded)

                if let status = vm.transientStatusText, vm.isStartupExpanded {
                    HStack(spacing: 6) {
                        Circle().fill(vm.transientStatusAccent).frame(width: 6, height: 6)
                        Text(status)
                            .font(.system(size: 11, weight: .medium))
                            .foregroundColor(.white.opacity(0.78))
                    }
                    .frame(width: notchWidth)
                    .offset(y: notchHeight + 3)
                    .transition(.opacity.combined(with: .move(edge: .top)))
                }

                if vm.isExpanded {
                    Group {
                        if let command = vm.pendingCommand {
                            CommandTranslationView(command: command, vm: vm)
                        } else {
                            switch vm.panelMode {
                            case .chat:
                                ChatView(vm: vm)
                            case .currentState:
                                CurrentStateView(vm: vm)
                            case .insight:
                                InsightView(vm: vm)
                            case .feed:
                                FeedView(vm: vm)
                            case .settings:
                                SettingsView()
                            case .status:
                                StatusView(vm: vm)
                            default:
                                DashboardView(vm: vm)
                            }
                        }
                    }
                    .frame(width: panelWidth)
                    .offset(y: notchHeight + panelHeaderGap)
                    .transition(.opacity.combined(with: .move(edge: .top)))
                }

                if vm.isExpanded && vm.pendingCommand == nil {
                    NotchExpandedHeader(
                        vm: vm,
                        geometryWidth: geo.size.width,
                        panelWidth: panelWidth,
                        notchWidth: notchWidth,
                        notchHeight: notchHeight
                    )
                }

                Color.clear
                    .frame(width: notchWidth, height: notchHeight)
                    .contentShape(Rectangle())
                    .onHover { hovering in withAnimation { vm.isHovering = hovering } }
                    .onTapGesture { vm.toggle() }
            }
        }
        .opacity(vm.isFullscreen ? 0 : 1)
        .onAppear {
            vm.refreshState()
            vm.startMcpPolling()
        }
    }
}
