import SwiftUI

extension PulseViewModel {
    func startMcpPolling() {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            guard let self else { return }
            var tick = 0
            while !Task.isCancelled {
                tick += 1
                let ping = try? await self.bridge.pingStatus()
                let alive = ping != nil
                let paused = ping?.paused ?? false
                let daemonJustCameBack = alive && !self.isDaemonActive
                self.syncDaemonReachability(alive: alive, paused: paused)
                if daemonJustCameBack {
                    self.onDaemonReconnected?()
                    // Grace period de 15s pour le chargement LLM au démarrage
                    self.startupGracePeriodEnd = Date().addingTimeInterval(15)
                    // "Pulse est actif" dès le premier ping réussi
                    self.showTransientStatus("Pulse est actif", accent: Color(hex: "#5DCAA5"), duration: 3.0)
                }
                self.updateBreathingGlow()

                // Notifications persistantes pour les états dégradés.
                // On attend la fin de la grace period avant de notifier LLM indisponible.
                let inGracePeriod = self.startupGracePeriodEnd.map { Date() < $0 } ?? false
                switch self.serviceStatus {
                case .daemonOffline:
                    if self.transientStatusText != "Daemon hors ligne" {
                        self.showTransientStatus("Daemon hors ligne", accent: Color(hex: "#ff453a"), persistent: true)
                    }
                case .llmUnavailable:
                    if !inGracePeriod && self.transientStatusText != "LLM indisponible" {
                        self.showTransientStatus("LLM indisponible", accent: Color(hex: "#F5A623"), persistent: true)
                    }
                case .daemonPaused:
                    if self.transientStatusText != "Pulse en pause" {
                        self.showTransientStatus("Pulse en pause", accent: Color(hex: "#F5A623"), persistent: true)
                    }
                case .observationPaused:
                    if self.transientStatusText != "Observation en pause" {
                        self.showTransientStatus("Observation en pause", accent: Color(hex: "#F5A623"), persistent: true)
                    }
                case .healthy:
                    let knownPersistent: Set<String> = ["Daemon hors ligne", "LLM indisponible", "Pulse en pause", "Observation en pause"]
                    if let current = self.transientStatusText, knownPersistent.contains(current) {
                        self.dismissPersistentStatus()
                    }
                }

                if alive {
                    let forceRefresh = daemonJustCameBack || !self.isOllamaOnline || !self.isLLMReady
                    if self.shouldRefreshModels(force: forceRefresh) {
                        if let models = try? await self.bridge.getLLMModels() {
                            self.applyLLMModels(models)
                        }
                    }

                    if tick % 6 == 0 {
                        self.refreshState()
                    }

                    if (self.panelMode == .insight || self.panelMode == .currentState) && self.isExpanded && tick % 4 == 0 {
                        self.refreshInsights()
                    }

                    if let cmd = try? await self.bridge.fetchPendingCommand() {
                        withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) {
                            self.pendingCommand = cmd
                            self.panelMode = .dashboard
                            self.isExpanded = true
                        }
                    }

                    // Feed des événements notables — notifications live dans l'encoche.
                    let feedEvents = await self.bridge.fetchFeed(since: self.lastFeedTimestamp)
                    if let latest = feedEvents.last {
                        self.lastFeedTimestamp = latest.timestamp
                    }
                    for event in feedEvents {
                        // Stocke dans l'historique dashboard (max 50)
                        self.feedHistory.insert(event, at: 0)
                        if self.feedHistory.count > 50 {
                            self.feedHistory = Array(self.feedHistory.prefix(50))
                        }

                        // Notifications LLM — affichage persistent jusqu'à llm_ready
                        if event.kind == "llm_loading" {
                            self.showTransientStatus(
                                "Chargement du modèle…",
                                accent: Color(hex: "#F5A623"),
                                persistent: true
                            )
                        } else if event.kind == "llm_ready" {
                            // Dismiss immédiat de la notification loading
                            withAnimation(.easeOut(duration: 0.4)) {
                                self.transientStatusText = nil
                                self.isStartupExpanded = false
                            }
                        } else if event.kind == "resume_card", let card = event.resumeCard {
                            self.showResumeCard(card)
                        }
                    }
                } else {
                    self.isLLMActive = false
                    self.isOllamaOnline = false
                    self.lastModelsRefreshAt = nil
                }

                try? await Task.sleep(nanoseconds: 500_000_000)
            }
        }
    }

    func stopMcpPolling() {
        pollTask?.cancel()
        pollTask = nil
    }

    func refreshState() {
        Task {
            guard let state = try? await bridge.getState() else { return }
            if let paused = state.runtimePaused {
                self.syncDaemonReachability(alive: true, paused: paused)
            }
            self.applyState(state)
        }
    }

    func refreshInsights() {
        Task {
            async let stateTask = bridge.getState()
            async let eventsTask = bridge.getInsights()
            async let proposalsTask = bridge.getRecentProposals()
            let (state, events, proposals) = await (try? stateTask, eventsTask, proposalsTask)
            if let state {
                self.applyState(state)
            }
            self.recentEvents = events
            self.recentProposals = proposals
        }
    }

    @discardableResult
    func refreshModels() async -> Bool {
        guard let response = try? await bridge.getLLMModels() else { return false }
        applyLLMModels(response)
        return true
    }
}

private extension PulseViewModel {
    func applyState(_ state: StateResponse) {
        let resolvedContext = state.currentContext
        currentPresent = state.present
        currentContext = resolvedContext
        currentSignals = state.signals

        let productProject = resolvedContext?.activeProject
            ?? state.present?.activeProject
            ?? state.activeProject
        let productTask = resolvedContext?.probableTask
            ?? state.present?.probableTask
            ?? "general"
        let liveFocus = state.present?.focusLevel
            ?? state.signals?.focusLevel
            ?? "normal"
        let liveFriction = state.present?.frictionScore
            ?? state.signals?.frictionScore
            ?? 0.0
        let liveDuration = state.present?.sessionDurationMin ?? state.sessionDurationMin
        let liveFile = state.present?.activeFile ?? state.activeFile

        activeProject = productProject
        activeApp = state.activeApp
        sessionDuration = max(liveDuration, 0)
        activeFile = liveFile
        probableTask = productTask
        focusLevel = liveFocus
        frictionScore = liveFriction
        recentApps = state.signals?.recentApps ?? []
    }

    func shouldRefreshModels(force: Bool = false) -> Bool {
        if force || availableModels.isEmpty || selectedModel.isEmpty {
            return true
        }
        guard let lastRefresh = lastModelsRefreshAt else { return true }
        let interval = (panelMode == .settings || panelMode == .status) ? 5.0 : 30.0
        return Date().timeIntervalSince(lastRefresh) >= interval
    }

    func syncDaemonReachability(alive: Bool, paused: Bool) {
        isDaemonActive = alive
        if alive {
            daemonController.state = paused ? .paused : .running
            daemonController.lastError = nil
            return
        }
        if daemonController.state == .running || daemonController.state == .paused {
            daemonController.state = .stopped
        }
    }

    func applyLLMModels(_ response: LLMModelsResponse) {
        availableModels = response.availableModels
        selectedModel = response.selectedModel
            ?? (!response.selectedCommandModel.isEmpty ? response.selectedCommandModel : response.selectedSummaryModel)
        selectedCommandModel = response.selectedCommandModel
        selectedSummaryModel = response.selectedSummaryModel
        isOllamaOnline = response.ollamaOnline ?? false
        isModelSelected = response.modelSelected
            ?? !selectedModel.isEmpty
        llmReadyState = response.llmReady
            ?? ((response.ollamaOnline ?? false) && isModelSelected)
        isLLMActive = response.llmActive ?? false
        lastModelsRefreshAt = Date()
    }
}
