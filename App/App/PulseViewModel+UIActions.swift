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
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            withAnimation(.spring(response: 0.5, dampingFraction: 0.8)) {
                self.isStartupExpanded = true
            }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
            self.isStartupVisible = true
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) {
            withAnimation(.spring(response: 0.5, dampingFraction: 0.85)) {
                self.isStartupVisible = false
                self.isStartupExpanded = false
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
