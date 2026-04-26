import SwiftUI

extension PulseViewModel {
    func toggle() {
        let willOpen = !isExpanded
        withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) {
            isExpanded.toggle()
        }
        if willOpen {
            panelMode = .dashboard
        }
        if isExpanded {
            refreshState()
        }
    }

    func switchMode(_ mode: PanelMode) {
        withAnimation(.spring(response: 0.35, dampingFraction: 0.82)) {
            panelMode = panelMode == mode ? .dashboard : mode
        }
        if panelMode == .status {
            Task { await refreshModels() }
        }
    }

    func toggleObservation() {
        isObservingEnabled.toggle()
        onObservationToggle?(isObservingEnabled)
    }

    func triggerStartupAnimation() {
        // Couleur basée sur isDaemonActive uniquement — pas sur serviceStatus
        // qui dépend du LLM pas encore chargé au moment du premier ping.
        let color: Color = isDaemonActive
            ? Color(hex: "#5DCAA5")  // vert — daemon actif
            : Color(hex: "#ff453a") // rouge — daemon mort
        startupGlowColor = color
        startupGlowActive = true

        // Pulse fort → fade progressif
        withAnimation(.easeOut(duration: 0.3)) {
            glowIntensity = 0.9
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
            withAnimation(.easeInOut(duration: 2.4)) {
                self.glowIntensity = 0.0
            }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 3.5) {
            self.startupGlowActive = false
        }
    }

    func updateBreathingGlow() {
        guard !startupGlowActive else { return }
        switch serviceStatus {
        case .daemonOffline, .daemonPaused, .observationPaused:
            let target: Double = breathingPhase ? 0.25 : 0.75
            breathingPhase.toggle()
            withAnimation(.easeInOut(duration: 2.0)) {
                glowIntensity = target
            }
        default:
            if glowIntensity > 0 && !startupGlowActive {
                withAnimation(.easeOut(duration: 0.6)) {
                    glowIntensity = 0.0
                }
            }
        }
    }

    func showTransientStatus(_ text: String, accent: Color? = nil, duration: Double = 3.0) {
        transientStatusAccent = accent ?? Color(hex: "#5DCAA5")
        transientStatusText = text
        withAnimation(.spring(response: 0.42, dampingFraction: 0.82)) {
            isStartupExpanded = true
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + duration) {
            withAnimation(.spring(response: 0.42, dampingFraction: 0.85)) {
                self.transientStatusText = nil
                self.isStartupExpanded = false
            }
        }
    }
}
