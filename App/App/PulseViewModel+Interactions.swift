import SwiftUI

extension PulseViewModel {
    func updateSelectedModel(_ model: String) {
        guard !model.isEmpty, model != selectedModel, !isUpdatingModel else { return }
        isUpdatingModel = true
        let previousModel = selectedModel
        selectedModel = model
        selectedCommandModel = model
        selectedSummaryModel = model

        Task {
            do {
                let result = try await bridge.setLLMModel(model)
                await MainActor.run {
                    self.isUpdatingModel = false
                    if result.ok {
                        let selectedModel = result.selectedModel
                            ?? result.selectedCommandModel
                            ?? result.selectedSummaryModel
                            ?? model
                        self.selectedModel = selectedModel
                        self.selectedCommandModel = selectedModel
                        self.selectedSummaryModel = selectedModel
                        self.showTransientStatus("Modèle : \(model)")
                    } else {
                        self.selectedModel = previousModel
                        self.selectedCommandModel = previousModel
                        self.selectedSummaryModel = previousModel
                        self.showTransientStatus("Échec changement de modèle", accent: Color(hex: "#ff453a"))
                    }
                }
            } catch let error as DaemonError {
                await MainActor.run {
                    self.isUpdatingModel = false
                    self.selectedModel = previousModel
                    self.selectedCommandModel = previousModel
                    self.selectedSummaryModel = previousModel
                    self.showTransientStatus(error.userMessage, accent: Color(hex: "#ff453a"))
                }
            } catch {
                await MainActor.run {
                    self.isUpdatingModel = false
                    self.selectedModel = previousModel
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
        isAsking  = true
        shouldShowCancellationFeedback = true
        activeRequestStatusText = "Pulse réfléchit…"
        activeRequestSystemMessage = nil

        // Historique complet avant ce message (sans les messages en cours de streaming)
        let historySnapshot = chatMessages.filter { !$0.isStreaming }

        // Ajoute le message utilisateur + une réponse vide (remplie par le stream)
        chatMessages.append(ChatMessage(role: "user",      content: message))
        chatMessages.append(ChatMessage(role: "assistant", content: "", isStreaming: true))

        withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) {
            panelMode  = .chat
            isExpanded = true
        }

        askTask = Task { [weak self] in
            guard let self else { return }
            defer {
                self.isAsking = false
                self.askTask  = nil
                self.activeRequestStatusText = nil
                // Marque le dernier message comme terminé
                if let idx = self.chatMessages.indices.last {
                    self.chatMessages[idx].isStreaming = false
                }
            }
            do {
                for try await token in self.bridge.askStream(message, history: historySnapshot) {
                    try Task.checkCancellation()
                    if let idx = self.chatMessages.indices.last {
                        self.chatMessages[idx].content += token
                    }
                }
            } catch is CancellationError {
                if self.shouldShowCancellationFeedback {
                    self.handleCancelledRequest()
                }
                return
            } catch let error as DaemonError {
                self.handleChatFailure(errorMessage: self.userFacingChatError(for: error))
            } catch {
                self.handleChatFailure(errorMessage: "Pulse n'est pas disponible pour le moment.")
            }
        }
    }

    func stopAsking() {
        guard isAsking else { return }
        askTask?.cancel()
        askTask = nil
        isAsking = false
        activeRequestStatusText = nil
        shouldShowCancellationFeedback = true
        handleCancelledRequest()
        if let idx = chatMessages.indices.last {
            chatMessages[idx].isStreaming = false
        }
    }

    func closeChat() {
        shouldShowCancellationFeedback = false
        askTask?.cancel()
        askTask = nil
        withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) {
            panelMode = .dashboard
        }
        // Réinitialise la conversation
        chatMessages = []
        isAsking     = false
        activeRequestStatusText = nil
        activeRequestSystemMessage = nil
    }
}

private extension PulseViewModel {
    func userFacingChatError(for error: DaemonError) -> String {
        if case .llm(let message) = error {
            return message
        }
        return error.userMessage
    }

    func lastAssistantMessageIndex() -> Int? {
        chatMessages.lastIndex { $0.role == "assistant" }
    }

    func removeTrailingEmptyAssistantMessageIfNeeded() {
        guard let idx = lastAssistantMessageIndex(),
              chatMessages[idx].content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else { return }
        chatMessages.remove(at: idx)
    }

    func handleChatFailure(errorMessage: String) {
        guard let idx = lastAssistantMessageIndex() else {
            activeRequestSystemMessage = errorMessage
            return
        }

        let hasAssistantContent = !chatMessages[idx].content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        if hasAssistantContent {
            activeRequestSystemMessage = "Réponse interrompue."
        } else {
            removeTrailingEmptyAssistantMessageIfNeeded()
            activeRequestSystemMessage = errorMessage
        }
    }

    func handleCancelledRequest() {
        guard let idx = lastAssistantMessageIndex() else {
            activeRequestSystemMessage = "Requête arrêtée."
            return
        }

        let hasAssistantContent = !chatMessages[idx].content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        if hasAssistantContent {
            activeRequestSystemMessage = "Réponse interrompue."
        } else {
            removeTrailingEmptyAssistantMessageIfNeeded()
            activeRequestSystemMessage = "Requête arrêtée."
        }
    }
}
