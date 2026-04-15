import Foundation

extension DaemonBridge {
    func ping() async -> Bool {
        (try? await pingStatus()) != nil
    }

    func pingStatus() async throws -> PingResponse {
        let url = try makeURL("/ping")
        let (data, response) = try await data(from: url)
        try validate(response, expectedStatus: 200)
        return try decode(PingResponse.self, from: data)
    }

    func getState() async throws -> StateResponse {
        let url = try makeURL("/state")
        let (data, response) = try await data(from: url)
        try validate(response, expectedStatus: 200)
        return try decode(StateResponse.self, from: data)
    }

    func sendEvent(_ payload: [String: String]) async throws {
        let request = try jsonRequest(path: "/event", body: payload, timeout: 3)
        _ = try? await data(for: request)
    }

    func fetchPendingCommand() async throws -> CommandAnalysis? {
        let url = try makeURL("/mcp/pending")
        let (data, response) = try await data(from: url)
        let statusCode = (response as? HTTPURLResponse)?.statusCode
        guard statusCode == 200 else { return nil }
        guard !data.isEmpty else { return nil }
        do {
            return try decode(CommandAnalysis.self, from: data)
        } catch {
            let raw = String(data: data, encoding: .utf8) ?? "<non-UTF8>"
            print("[DaemonBridge] ✗ Échec décodage CommandAnalysis: \(error)")
            print("[DaemonBridge]   JSON brut: \(raw)")
            return nil
        }
    }

    func sendMcpDecision(toolUseId: String, allow: Bool) async throws {
        let request = try jsonObjectRequest(
            path: "/mcp/decision",
            body: [
                "tool_use_id": toolUseId,
                "decision": allow ? "allow" : "deny",
            ]
        )
        let (data, response) = try await data(for: request)
        try validate(response, expectedStatus: 200)
        if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let ok = json["ok"] as? Bool,
           !ok {
            throw DaemonError.badResponse
        }
    }

    func pauseDaemon() async throws {
        try await post(path: "/daemon/pause")
    }

    func resumeDaemon() async throws {
        try await post(path: "/daemon/resume")
    }

    func getInsights(limit: Int = 25) async -> [InsightEvent] {
        guard let url = URL(string: "\(base)/insights?limit=\(limit)") else { return [] }
        guard let (data, response) = try? await data(from: url) else { return [] }
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { return [] }
        guard let array = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] else { return [] }
        return array.compactMap { dict in
            guard let type = dict["type"] as? String,
                  let timestamp = dict["timestamp"] as? String else { return nil }
            let payload = dict["payload"] as? [String: Any] ?? [:]
            let keyValue =
                (payload["app_name"] as? String)
                ?? (payload["path"] as? String).map { URL(fileURLWithPath: $0).lastPathComponent }
                ?? (payload["content_kind"] as? String)
                ?? (payload["decision"] as? String)
            return InsightEvent(type: type, timestamp: timestamp, keyValue: keyValue)
        }
    }

    func getRecentProposals(limit: Int = 6) async -> [ProposalRecord] {
        guard let url = URL(string: "\(base)/mcp/proposals?limit=\(limit)") else { return [] }
        guard let (data, response) = try? await data(from: url) else { return [] }
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { return [] }
        guard let payload = try? decode(ProposalHistoryResponse.self, from: data) else { return [] }
        return payload.items
    }
}
