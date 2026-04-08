import Foundation

// MARK: - Modèles

struct PingResponse: Codable {
    let status: String
    let version: String
}

struct StateResponse: Codable {
    let activeApp: String?
    let activeFile: String?
    let activeProject: String?
    let sessionDurationMin: Int
    let lastEventType: String?

    enum CodingKeys: String, CodingKey {
        case activeApp          = "active_app"
        case activeFile         = "active_file"
        case activeProject      = "active_project"
        case sessionDurationMin = "session_duration_min"
        case lastEventType      = "last_event_type"
    }
}

struct CommandAnalysis: Codable {
    let toolUseId: String
    let command: String
    let translated: String
    let riskLevel: String
    let riskScore: Int
    let isReadOnly: Bool
    let affects: [String]?   // nullable — certaines commandes n'ont pas de cibles explicites
    let warning: String?
    let needsLlm: Bool

    enum CodingKeys: String, CodingKey {
        case toolUseId  = "tool_use_id"
        case command    = "command"
        case translated = "translated"
        case riskLevel  = "risk_level"
        case riskScore  = "risk_score"
        case isReadOnly = "is_read_only"
        case affects    = "affects"
        case warning    = "warning"
        case needsLlm   = "needs_llm"
    }
}

struct ContextResponse: Codable {
    let context: String
}

struct LLMModelsResponse: Codable {
    let provider: String
    let availableModels: [String]
    let selectedCommandModel: String
    let selectedSummaryModel: String

    enum CodingKeys: String, CodingKey {
        case provider
        case availableModels = "available_models"
        case selectedCommandModel = "selected_command_model"
        case selectedSummaryModel = "selected_summary_model"
    }
}

struct SetLLMModelResponse: Codable {
    let ok: Bool
    let kind: String?
    let selectedModel: String?
    let selectedCommandModel: String?
    let selectedSummaryModel: String?

    enum CodingKeys: String, CodingKey {
        case ok
        case kind
        case selectedModel = "selected_model"
        case selectedCommandModel = "selected_command_model"
        case selectedSummaryModel = "selected_summary_model"
    }
}

// MARK: - Erreurs

enum DaemonError: Error {
    case badResponse
    case unreachable
}

// MARK: - Bridge

struct DaemonBridge {
    private let base = "http://localhost:8765"
    private let session = URLSession.shared

    // MARK: Ping

    func ping() async -> Bool {
        guard let url = URL(string: "\(base)/ping") else { return false }
        do {
            let (_, response) = try await session.data(from: url)
            return (response as? HTTPURLResponse)?.statusCode == 200
        } catch {
            return false
        }
    }

    // MARK: État

    func getState() async throws -> StateResponse {
        let url = URL(string: "\(base)/state")!
        let (data, _) = try await session.data(from: url)
        return try JSONDecoder().decode(StateResponse.self, from: data)
    }

    // MARK: Events système (appelé par SystemObserver)
    // Accepte un dict plat [String: String] avec "type" comme clé obligatoire.

    func sendEvent(_ payload: [String: String]) async throws {
        let url = URL(string: "\(base)/event")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 3
        request.httpBody = try JSONEncoder().encode(payload)
        _ = try? await session.data(for: request) // fire-and-forget
    }

    // MARK: Commande MCP en attente (polling depuis PulseViewModel)

    func fetchPendingCommand() async throws -> CommandAnalysis? {
        let url = URL(string: "\(base)/mcp/pending")!
        let (data, response) = try await session.data(from: url)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { return nil }
        // 204 No Content = pas de commande en attente
        guard !data.isEmpty else { return nil }
        do {
            return try JSONDecoder().decode(CommandAnalysis.self, from: data)
        } catch {
            // Log explicite : sans ça, un type mismatch passe inaperçu et le panel ne s'ouvre jamais
            let raw = String(data: data, encoding: .utf8) ?? "<non-UTF8>"
            print("[DaemonBridge] ✗ Échec décodage CommandAnalysis: \(error)")
            print("[DaemonBridge]   JSON brut: \(raw)")
            return nil
        }
    }

    // MARK: Décision MCP (Autoriser / Refuser)

    func sendMcpDecision(toolUseId: String, allow: Bool) async throws {
        let url = URL(string: "\(base)/mcp/decision")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "tool_use_id": toolUseId,
            "decision": allow ? "allow" : "deny"
        ])
        let (_, response) = try await session.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            throw DaemonError.badResponse
        }
    }

    // MARK: LLM

    func getContext() async throws -> String {
        let url = URL(string: "\(base)/context")!
        let (data, _) = try await session.data(from: url)
        let response = try JSONDecoder().decode(ContextResponse.self, from: data)
        return response.context
    }

    func getLLMModels() async throws -> LLMModelsResponse {
        let url = URL(string: "\(base)/llm/models")!
        let (data, _) = try await session.data(from: url)
        return try JSONDecoder().decode(LLMModelsResponse.self, from: data)
    }

    func setLLMModel(_ model: String, kind: String) async throws -> SetLLMModelResponse {
        let url = URL(string: "\(base)/llm/model")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "model": model,
            "kind": kind
        ])
        let (data, response) = try await session.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            throw DaemonError.badResponse
        }
        return try JSONDecoder().decode(SetLLMModelResponse.self, from: data)
    }

    func ask(_ message: String) async throws -> String {
        let url = URL(string: "\(base)/ask")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["message": message])
        let (data, _) = try await session.data(for: request)
        let resp = try JSONDecoder().decode([String: String].self, from: data)
        return resp["response"] ?? ""
    }
}
