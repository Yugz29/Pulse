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
                    // Glow au démarrage — déclenché après le premier ping réussi,
                    // pas à onAppear (sinon serviceStatus pas encore à jour).
                    self.triggerStartupAnimation()
                }

                // Glow breathing si état dégradé
                self.updateBreathingGlow()

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
                                duration: 120  // reste jusqu'à llm_ready
                            )
                        } else if event.kind == "llm_ready" {
                            // Dismiss immédiat de la notification loading
                            withAnimation(.easeOut(duration: 0.4)) {
                                self.transientStatusText = nil
                                self.isStartupExpanded = false
                            }
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
        currentPresent = state.present
        currentEpisode = state.currentEpisode
        currentSignals = state.signals

        let productProject = state.currentEpisode?.activeProject
            ?? state.present?.activeProject
            ?? state.activeProject
        let productTask = state.currentEpisode?.probableTask
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
