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

                    if self.panelMode == .insight && self.isExpanded && tick % 4 == 0 {
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
            let (state, events) = await (try? stateTask, eventsTask)
            if let state {
                self.applyState(state)
            }
            self.recentEvents = events
        }
    }

    func refreshModels() async {
        guard let response = try? await bridge.getLLMModels() else { return }
        applyLLMModels(response)
    }
}

private extension PulseViewModel {
    func applyState(_ state: StateResponse) {
        activeProject = state.activeProject
        activeApp = state.activeApp
        sessionDuration = state.sessionDurationMin
        activeFile = state.activeFile
        if let sig = state.signals {
            probableTask = sig.probableTask ?? "general"
            focusLevel = sig.focusLevel ?? "normal"
            frictionScore = sig.frictionScore ?? 0.0
            recentApps = sig.recentApps ?? []
        }
    }

    func shouldRefreshModels(force: Bool = false) -> Bool {
        if force || availableModels.isEmpty || selectedCommandModel.isEmpty || selectedSummaryModel.isEmpty {
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
        selectedCommandModel = response.selectedCommandModel
        selectedSummaryModel = response.selectedSummaryModel
        isOllamaOnline = response.ollamaOnline ?? false
        isLLMActive = response.llmActive
            ?? ((response.ollamaOnline ?? false) && !response.availableModels.isEmpty)
        lastModelsRefreshAt = Date()
    }
}
