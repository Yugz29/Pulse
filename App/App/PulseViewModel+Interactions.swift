import SwiftUI

extension PulseViewModel {
    func updateSelectedModel(_ model: String) {
        guard !model.isEmpty, model != selectedCommandModel, !isUpdatingModel else { return }
        isUpdatingModel = true
        let previousModel = selectedCommandModel
        selectedCommandModel = model
        selectedSummaryModel = model

        Task {
            do {
                let result = try await bridge.setLLMModel(model, kind: "command")
                await MainActor.run {
                    self.isUpdatingModel = false
                    if result.ok {
                        let selectedModel = result.selectedCommandModel ?? model
                        self.selectedCommandModel = selectedModel
                        self.selectedSummaryModel = selectedModel
                        self.showTransientStatus("Modèle : \(model)")
                    } else {
                        self.selectedCommandModel = previousModel
                        self.selectedSummaryModel = previousModel
                        self.showTransientStatus("Échec changement de modèle", accent: Color(hex: "#ff453a"))
                    }
                }
            } catch let error as DaemonError {
                await MainActor.run {
                    self.isUpdatingModel = false
                    self.selectedCommandModel = previousModel
                    self.selectedSummaryModel = previousModel
                    self.showTransientStatus(error.userMessage, accent: Color(hex: "#ff453a"))
                }
            } catch {
                await MainActor.run {
                    self.isUpdatingModel = false
                    self.selectedCommandModel = previousModel
                    self.selectedSummaryModel = previousModel
                    self.showTransientStatus("Échec changement de modèle", accent: Color(hex: "#ff453a"))
                }
            }
        }
    }

    func sendDecision(allow: Bool) {
        guard let command = pendingCommand else { return }
        Task {
            do {
                try await bridge.sendMcpDecision(toolUseId: command.toolUseId, allow: allow)
                self.pendingCommand = nil
                self.panelMode = .dashboard
                self.isExpanded = false
            } catch let error as DaemonError {
                self.showTransientStatus(error.userMessage, accent: Color(hex: "#ff453a"))
            } catch {
                self.showTransientStatus("Échec envoi décision", accent: Color(hex: "#ff453a"))
            }
        }
    }

    func sendMessage() {
        let message = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !message.isEmpty, !isAsking else { return }
        askTask?.cancel()
        inputText = ""
        isAsking = true
        askResponse = nil
        withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) {
            panelMode = .chat
            isExpanded = true
        }
        askTask = Task { [weak self] in
            guard let self else { return }
            defer {
                self.isAsking = false
                self.askTask = nil
            }
            do {
                for try await token in self.bridge.askStream(message) {
                    try Task.checkCancellation()
                    if self.askResponse == nil {
                        self.askResponse = token
                    } else {
                        self.askResponse! += token
                    }
                }
            } catch is CancellationError {
                return
            } catch let error as DaemonError {
                if case .llm(let message) = error {
                    if self.askResponse == nil {
                        self.askResponse = message
                    }
                } else if self.askResponse == nil {
                    self.askResponse = error.userMessage
                }
            } catch {
                if self.askResponse == nil {
                    self.askResponse = "Pulse n'est pas disponible pour le moment."
                }
            }
        }
    }

    func closeChat() {
        askTask?.cancel()
        askTask = nil
        withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) {
            panelMode = .dashboard
            askResponse = nil
            isAsking = false
        }
    }
}
