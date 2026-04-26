import SwiftUI

// MARK: - GlowState

enum GlowState: Equatable {
    case hidden
    case startup(color: Color)
    case breathing(color: Color)

    var color: Color {
        switch self {
        case .hidden: return .clear
        case .startup(let c): return c
        case .breathing(let c): return c
        }
    }

    var isVisible: Bool {
        if case .hidden = self { return false }
        return true
    }

    static func == (lhs: GlowState, rhs: GlowState) -> Bool {
        switch (lhs, rhs) {
        case (.hidden, .hidden): return true
        case (.startup(let a), .startup(let b)): return a == b
        case (.breathing(let a), .breathing(let b)): return a == b
        default: return false
        }
    }
}

// MARK: - NotchGlowView

struct NotchGlowView: View {
    let state: GlowState
    let notchHeight: CGFloat

    @State private var intensity: Double = 0.0
    @State private var breathingPhase: Bool = false
    @State private var breathingTask: DispatchWorkItem? = nil

    var body: some View {
        GeometryReader { geo in
            if state.isVisible {
                RadialGradient(
                    gradient: Gradient(colors: [
                        state.color.opacity(0.7 * intensity),
                        state.color.opacity(0.30 * intensity),
                        state.color.opacity(0.08 * intensity),
                        Color.clear
                    ]),
                    center: UnitPoint(x: 0.5, y: 0.0),
                    startRadius: 0,
                    endRadius: geo.size.width * 0.52
                )
                .frame(width: geo.size.width, height: geo.size.height)
                .blur(radius: 6)
            }
        }
        .allowsHitTesting(false)
        .onChange(of: state) { _, newState in
            handleStateChange(newState)
        }
        .onAppear {
            handleStateChange(state)
        }
    }

    private func handleStateChange(_ newState: GlowState) {
        breathingTask?.cancel()
        breathingTask = nil

        switch newState {
        case .hidden:
            withAnimation(.easeOut(duration: 0.8)) {
                intensity = 0.0
            }

        case .startup:
            withAnimation(.easeOut(duration: 0.25)) {
                intensity = 1.0
            }
            let task = DispatchWorkItem {
                withAnimation(.easeInOut(duration: 2.4)) {
                    intensity = 0.0
                }
            }
            breathingTask = task
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.8, execute: task)

        case .breathing:
            breathingPhase = false
            intensity = 0.0
            scheduleBreathing()
        }
    }

    private func scheduleBreathing() {
        let target: Double = breathingPhase ? 0.3 : 0.9
        breathingPhase.toggle()

        withAnimation(.easeInOut(duration: 2.0)) {
            intensity = target
        }

        let task = DispatchWorkItem { [self] in
            if case .breathing = state {
                scheduleBreathing()
            }
        }
        breathingTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.0, execute: task)
    }
}

// MARK: - GlowState depuis PulseViewModel

extension PulseViewModel {
    var glowState: GlowState {
        // Startup glow prioritaire
        if startupGlowActive {
            return .startup(color: startupGlowColor)
        }
        switch serviceStatus {
        case .healthy:
            return .hidden
        case .daemonOffline:
            return .breathing(color: Color(hex: "#ff453a"))
        case .daemonPaused:
            return .breathing(color: Color(hex: "#F5A623"))
        case .observationPaused:
            return .breathing(color: Color(hex: "#F5A623"))
        case .llmUnavailable:
            return .hidden
        }
    }
}
