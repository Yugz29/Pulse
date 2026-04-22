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
            guard !_isNoisyEvent(type: type, payload: payload) else { return nil }
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

    func getFacts(limit: Int = 30) async -> FactsResponse? {
        guard let url = URL(string: "\(base)/facts?limit=\(limit)") else { return nil }
        guard let (data, response) = try? await data(from: url) else { return nil }
        let statusCode = (response as? HTTPURLResponse)?.statusCode ?? -1
        guard statusCode == 200 || statusCode == 503 else { return nil }
        return try? decode(FactsResponse.self, from: data)
    }

    func getFactsStats() async -> FactsStatsResponse? {
        guard let url = URL(string: "\(base)/facts/stats") else { return nil }
        guard let (data, response) = try? await data(from: url) else { return nil }
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { return nil }
        return try? decode(FactsStatsResponse.self, from: data)
    }

    func getFactsProfile() async -> FactsProfileResponse? {
        guard let url = URL(string: "\(base)/facts/profile") else { return nil }
        guard let (data, response) = try? await data(from: url) else { return nil }
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { return nil }
        return try? decode(FactsProfileResponse.self, from: data)
    }

    func getArchivedFacts(limit: Int = 30) async -> FactsResponse? {
        guard let url = URL(string: "\(base)/facts?limit=\(limit)&archived=true") else { return nil }
        guard let (data, response) = try? await data(from: url) else { return nil }
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { return nil }
        return try? decode(FactsResponse.self, from: data)
    }

    func getMemory() async -> MemoryResponse? {
        guard let url = URL(string: "\(base)/memory") else { return nil }
        guard let (data, response) = try? await data(from: url) else { return nil }
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { return nil }
        return try? decode(MemoryResponse.self, from: data)
    }

    func getSessionJournals(limit: Int = 7) async -> SessionsResponse? {
        guard let url = URL(string: "\(base)/memory/sessions?limit=\(limit)") else { return nil }
        guard let (data, response) = try? await data(from: url) else { return nil }
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { return nil }
        return try? decode(SessionsResponse.self, from: data)
    }

    func getScoringStatus() async -> ScoringStatusResponse? {
        guard let url = URL(string: "\(base)/scoring/status") else { return nil }
        guard let (data, response) = try? await data(from: url) else { return nil }
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { return nil }
        return try? decode(ScoringStatusResponse.self, from: data)
    }
}

// MARK: - Insight filtering

/// Returns true if the event should be hidden from the Observation feed.
/// Keeps the list human-readable by removing technical noise.
private func _isNoisyEvent(type: String, payload: [String: Any]) -> Bool {
    // Only file events can be noisy — other types are always meaningful.
    let fileEventTypes: Set<String> = [
        "file_created", "file_modified", "file_renamed",
        "file_deleted", "file_change",
    ]
    guard fileEventTypes.contains(type) else { return false }

    guard let path = payload["path"] as? String, !path.isEmpty else { return true }

    let name = URL(fileURLWithPath: path).lastPathComponent

    // Noisy filename suffixes
    let noisySuffixes = [
        ".sqlite", ".sqlite3", ".db", ".db-journal", ".db-wal", ".db-shm",
        ".log", ".jsonl", ".tmp", ".temp", ".swp", ".swo",
        "-journal", "-wal", "-shm",
    ]
    for suffix in noisySuffixes where name.hasSuffix(suffix) { return true }

    // Noisy exact filenames
    let noisyNames: Set<String> = ["COMMIT_EDITMSG", "MERGE_MSG", "FETCH_HEAD", "ORIG_HEAD"]
    if noisyNames.contains(name) { return true }

    // Hidden files
    if name.hasPrefix(".") { return true }

    // macOS sandbox noise
    if name.contains(".sb-") { return true }

    // Noisy path segments
    let noisySegments = [
        // Dev tooling
        "/.git/", "/node_modules/", "/__pycache__/",
        "/xcuserdata/", "/DerivedData/",
        // Python environments
        "/site-packages/", "/dist-packages/", "/.venv/", "/venv/",
        // macOS system & Homebrew libraries
        "/opt/homebrew/Cellar/", "/opt/homebrew/lib/",
        "/usr/local/lib/", "/usr/lib/", "/usr/share/",
        "/System/Library/", "/private/var/",
        // macOS user library
        "/Library/Caches/", "/Library/Containers/",
        "/Library/Application Support/",
        // Pulse internal
        "/.pulse/",
    ]
    for segment in noisySegments where path.contains(segment) { return true }

    // UUID-looking filenames (macOS temp files, cache keys, etc.)
    // Pattern: 8-4-4-4-12 hex chars
    let uuidPattern = #"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"#
    if name.range(of: uuidPattern, options: .regularExpression) != nil { return true }

    return false
}
