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
        let (_, response) = try await data(for: request)
        try validate(response, expectedStatus: 200)
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

    func fetchFeed(since: String?) async -> [FeedEvent] {
        var urlStr = "\(base)/feed"
        if let since { urlStr += "?since=\(since.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? since)" }
        guard let url = URL(string: urlStr) else { return [] }
        guard let (data, response) = try? await data(from: url) else { return [] }
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { return [] }
        guard let array = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] else { return [] }
        return array.compactMap { dict in
            guard let kind = dict["kind"] as? String,
                  let label = dict["label"] as? String,
                  let timestamp = dict["timestamp"] as? String else { return nil }
            return FeedEvent(
                kind: kind,
                label: label,
                success: dict["success"] as? Bool,
                command: dict["command"] as? String,
                timestamp: timestamp,
                resumeCard: Self.resumeCard(from: dict["resume_card"] as? [String: Any])
            )
        }
    }

    private static func resumeCard(from dict: [String: Any]?) -> ResumeCard? {
        guard let dict,
              let id = dict["id"] as? String,
              let title = dict["title"] as? String,
              let summary = dict["summary"] as? String,
              let lastObjective = dict["last_objective"] as? String,
              let nextAction = dict["next_action"] as? String
        else { return nil }

        return ResumeCard(
            id: id,
            project: dict["project"] as? String,
            title: title,
            summary: summary,
            lastObjective: lastObjective,
            nextAction: nextAction,
            confidence: dict["confidence"] as? Double ?? 0,
            sourceRefs: dict["source_refs"] as? [String] ?? [],
            generatedBy: dict["generated_by"] as? String ?? "deterministic",
            displaySize: dict["display_size"] as? String ?? "standard",
            createdAt: dict["created_at"] as? String
        )
    }

    func getObservation() async -> ObservationData? {
        guard let url = URL(string: "\(base)/observation") else { return nil }
        guard let (data, _) = try? await self.data(from: url),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return nil }

        let titles = (json["window_titles"] as? [[String: Any]] ?? []).compactMap { d -> ObservationWindowTitle? in
            guard let title = d["title"] as? String else { return nil }
            return ObservationWindowTitle(
                title: title,
                app: d["app"] as? String ?? "",
                timestamp: d["timestamp"] as? String ?? "",
                elapsedSec: d["elapsed_sec"] as? Int ?? 0
            )
        }
        let commands = (json["terminal_commands"] as? [[String: Any]] ?? []).compactMap { d -> ObservationTerminalCommand? in
            guard let cmd = d["command"] as? String else { return nil }
            return ObservationTerminalCommand(
                command: cmd,
                summary: d["summary"] as? String ?? "",
                success: d["success"] as? Bool,
                durationMs: d["duration_ms"] as? Int,
                project: d["project"] as? String ?? "",
                timestamp: d["timestamp"] as? String ?? ""
            )
        }
        return ObservationData(windowTitles: titles, terminalCommands: commands)
    }

    func getDaydreamData() async -> ([DaydreamEntry], DaydreamStatus?) {
        guard let url = URL(string: "\(base)/daydreams") else { return ([], nil) }
        guard let (data, _) = try? await self.data(from: url),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return ([], nil) }

        let rawEntries: [[String: Any]] = json["daydreams"] as? [[String: Any]] ?? []
        let entries: [DaydreamEntry] = rawEntries.compactMap { d in
            guard let date = d["date"] as? String,
                  let content = d["content"] as? String
            else { return nil }
            return DaydreamEntry(id: date, date: date, content: content)
        }

        let statusDict: [String: Any]? = json["status"] as? [String: Any]
        let status: DaydreamStatus? = statusDict.map { d in
            DaydreamStatus(
                status: d["status"] as? String ?? "idle",
                pending: d["pending"] as? Bool ?? false,
                targetDate: d["target_date"] as? String,
                doneForDate: d["done_for_date"] as? String,
                lastReason: d["last_reason"] as? String,
                lastError: d["last_error"] as? String,
                lastAttemptAt: d["last_attempt_at"] as? String,
                lastCompletedAt: d["last_completed_at"] as? String,
                lastOutputPath: d["last_output_path"] as? String
            )
        }

        return (entries, status)
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

    func getContextProbeRequests(status: String? = nil, includeTerminal: Bool = true) async -> ContextProbeListResponse? {
        var queryItems: [String] = []
        if let status, !status.isEmpty {
            let encoded = status.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? status
            queryItems.append("status=\(encoded)")
        }
        if !includeTerminal {
            queryItems.append("include_terminal=false")
        }
        let query = queryItems.isEmpty ? "" : "?\(queryItems.joined(separator: "&"))"
        guard let url = URL(string: "\(base)/context-probes/requests\(query)") else { return nil }
        guard let (data, response) = try? await data(from: url) else { return nil }
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { return nil }
        return try? decode(ContextProbeListResponse.self, from: data)
    }

    func approveContextProbeRequest(_ requestId: String, reason: String? = nil) async -> ContextProbeActionResponse? {
        await sendContextProbeDecision(requestId: requestId, action: "approve", reason: reason)
    }

    func refuseContextProbeRequest(_ requestId: String, reason: String? = nil) async -> ContextProbeActionResponse? {
        await sendContextProbeDecision(requestId: requestId, action: "refuse", reason: reason)
    }

    func executeContextProbeRequest(_ requestId: String) async -> ContextProbeExecuteResponse? {
        guard let encodedId = requestId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) else { return nil }
        let request: URLRequest
        do {
            request = try jsonObjectRequest(
                path: "/context-probes/requests/\(encodedId)/execute",
                body: [:]
            )
        } catch {
            return nil
        }
        guard let (data, response) = try? await data(for: request) else { return nil }
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { return nil }
        return try? decode(ContextProbeExecuteResponse.self, from: data)
    }

    private func sendContextProbeDecision(requestId: String, action: String, reason: String?) async -> ContextProbeActionResponse? {
        guard let encodedId = requestId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) else { return nil }
        var body: [String: Any] = [:]
        if let reason, !reason.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            body["reason"] = reason
        }
        let request: URLRequest
        do {
            request = try jsonObjectRequest(
                path: "/context-probes/requests/\(encodedId)/\(action)",
                body: body
            )
        } catch {
            return nil
        }
        guard let (data, response) = try? await data(for: request) else { return nil }
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { return nil }
        return try? decode(ContextProbeActionResponse.self, from: data)
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

    func getTodaySummary() async -> TodaySummaryResponse? {
        guard let url = URL(string: "\(base)/today_summary") else { return nil }
        guard let (data, response) = try? await data(from: url) else { return nil }
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { return nil }
        return try? decode(TodaySummaryResponse.self, from: data)
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
