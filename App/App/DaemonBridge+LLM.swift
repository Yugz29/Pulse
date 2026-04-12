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

    func setLLMModel(_ model: String, kind: String) async throws -> SetLLMModelResponse {
        let request = try jsonObjectRequest(
            path: "/llm/model",
            body: [
                "model": model,
                "kind": kind,
            ]
        )
        let (data, response) = try await data(for: request)
        try validate(response, expectedStatus: 200)
        return try decode(SetLLMModelResponse.self, from: data)
    }

    func askStream(_ message: String) -> AsyncThrowingStream<String, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let request = try jsonObjectRequest(path: "/ask/stream", body: ["message": message])
                    let (bytes, response) = try await bytes(for: request)
                    try validate(response, expectedStatus: 200)

                    for try await line in bytes.lines {
                        try Task.checkCancellation()
                        guard line.hasPrefix("data: "),
                              let data = String(line.dropFirst(6)).data(using: .utf8),
                              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
                        else { continue }

                        if let error = object["error"] as? String {
                            continuation.finish(throwing: DaemonError.llm(error))
                            return
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
