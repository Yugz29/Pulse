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

    func showResumeCard(_ card: ResumeCard) {
        activeResumeCard = card
        withAnimation(.spring(response: 0.35, dampingFraction: 0.82)) {
            transientStatusText = nil
            isStartupExpanded = false
            panelMode = .resumeCard
            isExpanded = true
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 60.0) {
            guard self.activeResumeCard?.id == card.id, self.panelMode == .resumeCard else { return }
            self.dismissResumeCard()
        }
    }

    func dismissResumeCard() {
        withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) {
            activeResumeCard = nil
            panelMode = .dashboard
            isExpanded = false
        }
    }

    func toggleObservation() {
        isObservingEnabled.toggle()
        onObservationToggle?(isObservingEnabled)
    }

    func triggerStartupAnimation() {
        // Glow supprimé — le startup est géré par le transient status.
    }

    func updateBreathingGlow() {
        // Glow supprimé — les états dégradés sont gérés par le transient status persistant.
    }

    func showTransientStatus(_ text: String, accent: Color? = nil, duration: Double = 3.0, persistent: Bool = false) {
        transientStatusAccent = accent ?? Color(hex: "#5DCAA5")
        transientStatusText = text
        withAnimation(.spring(response: 0.42, dampingFraction: 0.82)) {
            isStartupExpanded = true
        }
        guard !persistent else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + duration) {
            withAnimation(.spring(response: 0.42, dampingFraction: 0.85)) {
                self.transientStatusText = nil
                self.isStartupExpanded = false
            }
        }
    }

    func dismissPersistentStatus() {
        guard transientStatusText != nil else { return }
        withAnimation(.spring(response: 0.42, dampingFraction: 0.85)) {
            transientStatusText = nil
            isStartupExpanded = false
        }
    }
}
