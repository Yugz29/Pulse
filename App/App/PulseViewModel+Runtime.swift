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
        activeProject = state.activeProject
        activeApp = state.activeApp
        sessionDuration = state.sessionDurationMin
        activeFile = state.activeFile
        currentSignals = state.signals
        if let sig = state.signals {
            probableTask = sig.probableTask ?? "general"
            focusLevel = sig.focusLevel ?? "normal"
            frictionScore = sig.frictionScore ?? 0.0
            recentApps = sig.recentApps ?? []
        }
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
