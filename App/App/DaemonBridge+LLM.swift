import Foundation

extension DaemonBridge {
    func getContext() async throws -> String {
        let url = try makeURL("/context")
        let (data, httpResponse) = try await data(from: url)
        try validate(httpResponse, expectedStatus: 200)
        let contextResponse = try decode(ContextResponse.self, from: data)
        return contextResponse.context
    }

    func getLLMModels() async throws -> LLMModelsResponse {
        let url = try makeURL("/llm/models")
        let (data, response) = try await data(from: url)
        try validate(response, expectedStatus: 200)
        return try decode(LLMModelsResponse.self, from: data)
    }

    func setLLMModel(_ model: String) async throws -> SetLLMModelResponse {
        let request = try jsonObjectRequest(
            path: "/llm/model",
            body: [
                "model": model,
            ]
        )
        let (data, response) = try await data(for: request)
        try validate(response, expectedStatus: 200)
        return try decode(SetLLMModelResponse.self, from: data)
    }

    func askStream(_ message: String, history: [ChatMessage] = []) -> AsyncThrowingStream<String, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    // Historique : max 6 messages (3 échanges) pour rester dans le contexte
                    let historyPayload = history.suffix(6).map {
                        ["role": $0.role, "content": $0.content]
                    }
                    let body: [String: Any] = [
                        "message": message,
                        "history": historyPayload,
                    ]
                    let request = try jsonObjectRequest(path: "/ask/stream", body: body, timeout: 300)
                    let (bytes, response) = try await bytes(for: request)
                    try validate(response, expectedStatus: 200)

                    for try await line in bytes.lines {
                        try Task.checkCancellation()
                        guard line.hasPrefix("data: "),
                              let data = String(line.dropFirst(6)).data(using: .utf8),
                              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
                        else { continue }

                        if let state = object["state"] as? String {
                            let message = (object["error"] as? String)
                                ?? (state == "degraded" ? "Réponse incomplète." : "Réponse finale invalide.")
                            continuation.finish(throwing: DaemonError.llm(message))
                            return
                        }
                        if let error = object["error"] as? String {
                            continuation.finish(throwing: DaemonError.llm(error))
                            return
                        }
                        // Heartbeat "thinking" et status — ignorés, gardent la connexion vivante
                        if object["status"] != nil && object["token"] == nil && object["tool_call"] == nil {
                            continue
                        }
                        // Signal intermédiaire d'outil : jamais exposé comme texte assistant.
                        if object["tool_call"] as? String != nil {
                            continue
                        }
                        if let token = object["token"] as? String, !token.isEmpty {
                            continuation.yield(token)
                        }
                        if object["done"] as? Bool == true {
                            break
                        }
                    }
                    continuation.finish()
                } catch is CancellationError {
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    func ask(_ message: String) async throws -> String {
        let request = try jsonObjectRequest(
            path: "/ask",
            body: ["message": message],
            timeout: 300
        )
        let (data, httpResponse) = try await data(for: request)
        try validate(httpResponse, expectedStatus: 200)
        let askResponse = try decode(AskResponse.self, from: data)
        guard askResponse.ok, let message = askResponse.response else {
            throw DaemonError.badResponse
        }
        return message
    }
}
