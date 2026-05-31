import XCTest
@testable import App

@MainActor
final class PulseViewModelInteractionsTests: XCTestCase {
    private func makeBridge(body: String, statusCode: Int = 200) -> DaemonBridge {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)

        MockURLProtocol.handler = { request in
            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: statusCode,
                httpVersion: nil,
                headerFields: ["Content-Type": "text/event-stream"]
            )!
            return (response, Data(body.utf8))
        }

        return DaemonBridge(base: "http://127.0.0.1:8765", session: session)
    }

    private func makeJSONBridge(json: String, path: String = "/llm/models", statusCode: Int = 200) -> DaemonBridge {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)

        MockURLProtocol.handler = { request in
            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: statusCode,
                httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!
            XCTAssertEqual(request.url?.path, path)
            return (response, Data(json.utf8))
        }

        return DaemonBridge(base: "http://127.0.0.1:8765", session: session)
    }

    private func waitUntil(_ condition: @escaping @MainActor () -> Bool, timeout: TimeInterval = 1.0) async {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if condition() { return }
            try? await Task.sleep(nanoseconds: 20_000_000)
        }
    }

    private final class RequestCallRecorder: @unchecked Sendable {
        private let lock = NSLock()
        private var calls: [String] = []

        func record(_ request: URLRequest) {
            lock.lock()
            calls.append("\(request.httpMethod ?? "GET") \(request.url?.path ?? "")")
            lock.unlock()
        }

        var snapshot: [String] {
            lock.lock()
            let value = calls
            lock.unlock()
            return value
        }
    }

    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    func testInsightEventLabelsUseReadableLifecycleNames() {
        XCTAssertEqual(
            InsightEvent(type: "screen_locked", timestamp: "", keyValue: nil).label,
            "Verrouillage écran"
        )
        XCTAssertEqual(
            InsightEvent(type: "screen_unlocked", timestamp: "", keyValue: nil).label,
            "Déverrouillage écran"
        )
        XCTAssertEqual(
            InsightEvent(type: "user_presence", timestamp: "", keyValue: nil).label,
            "Présence"
        )
    }

    func testSendMessageNormalResponseRemainsUnchanged() async {
        let body = """
        data: {"token":"Bonjour","done":false}

        data: {"token":"","done":true,"model":"mistral"}

        """
        let vm = PulseViewModel(bridge: makeBridge(body: body))
        vm.inputText = "Salut"

        vm.sendMessage()
        await waitUntil { !vm.isAsking }

        XCTAssertEqual(vm.chatMessages.count, 2)
        XCTAssertEqual(vm.chatMessages[0].role, "user")
        XCTAssertEqual(vm.chatMessages[1].role, "assistant")
        XCTAssertEqual(vm.chatMessages[1].content, "Bonjour")
        XCTAssertFalse(vm.chatMessages[1].isStreaming)
        XCTAssertNil(vm.activeRequestSystemMessage)
        XCTAssertNil(vm.activeRequestStatusText)
    }

    func testSendMessagePartialTokensThenDegradedMarksMessageIncomplete() async {
        let body = """
        data: {"token":"Réponse ","done":false}

        data: {"state":"degraded","error":"Réponse incomplète.","code":"degraded_response"}

        """
        let vm = PulseViewModel(bridge: makeBridge(body: body))
        vm.inputText = "Salut"

        vm.sendMessage()
        XCTAssertEqual(vm.activeRequestStatusText, "Pulse réfléchit…")
        await waitUntil { !vm.isAsking }

        XCTAssertEqual(vm.chatMessages.count, 2)
        XCTAssertEqual(vm.chatMessages[1].content, "Réponse ")
        XCTAssertFalse(vm.chatMessages[1].isStreaming)
        XCTAssertEqual(vm.activeRequestSystemMessage, "Réponse interrompue.")
        XCTAssertNil(vm.activeRequestStatusText)
    }

    func testSendMessageInvalidWithoutTokensShowsExplicitFailure() async {
        let body = """
        data: {"state":"invalid","error":"Réponse finale invalide.","code":"invalid_response"}

        """
        let vm = PulseViewModel(bridge: makeBridge(body: body))
        vm.inputText = "Salut"

        vm.sendMessage()
        await waitUntil { !vm.isAsking }

        XCTAssertEqual(vm.chatMessages.count, 1)
        XCTAssertEqual(vm.activeRequestSystemMessage, "Réponse finale invalide.")
        XCTAssertNil(vm.activeRequestStatusText)
    }

    func testSendMessageToolCallDoesNotLeakMarkerIntoVisibleAssistantMessage() async {
        let body = """
        data: {"status":"thinking"}

        data: {"tool_call":"score_project","status":"running"}

        data: {"token":"Réponse finale","done":false}

        data: {"token":"","done":true,"model":"mistral"}

        """
        let vm = PulseViewModel(bridge: makeBridge(body: body))
        vm.inputText = "Salut"

        vm.sendMessage()
        await waitUntil { !vm.isAsking }

        XCTAssertEqual(vm.chatMessages.count, 2)
        XCTAssertEqual(vm.chatMessages[1].content, "Réponse finale")
        XCTAssertFalse(vm.chatMessages[1].content.contains("[score_project]"))
        XCTAssertFalse(vm.chatMessages[1].isStreaming)
        XCTAssertNil(vm.activeRequestSystemMessage)
    }

    func testSendMessageMultipleToolCallsDoNotPolluteVisibleResponse() async {
        let body = """
        data: {"status":"thinking"}

        data: {"tool_call":"score_project","status":"running"}

        data: {"tool_call":"score_file","status":"running"}

        data: {"token":"Réponse ","done":false}

        data: {"token":"finale","done":false}

        data: {"token":"","done":true,"model":"mistral"}

        """
        let vm = PulseViewModel(bridge: makeBridge(body: body))
        vm.inputText = "Salut"

        vm.sendMessage()
        await waitUntil { !vm.isAsking }

        XCTAssertEqual(vm.chatMessages.count, 2)
        XCTAssertEqual(vm.chatMessages[1].content, "Réponse finale")
        XCTAssertFalse(vm.chatMessages[1].content.contains("[score_project]"))
        XCTAssertFalse(vm.chatMessages[1].content.contains("[score_file]"))
        XCTAssertFalse(vm.chatMessages[1].isStreaming)
        XCTAssertNil(vm.activeRequestSystemMessage)
    }

    func testStopAskingKeepsConversationAndSetsSystemMessage() {
        let vm = PulseViewModel()
        vm.chatMessages = [
            ChatMessage(role: "user", content: "Salut"),
            ChatMessage(role: "assistant", content: "Réponse partielle", isStreaming: true),
        ]
        vm.isAsking = true
        vm.activeRequestStatusText = "Pulse réfléchit…"
        vm.askTask = Task { try? await Task.sleep(nanoseconds: 1_000_000_000) }

        vm.stopAsking()

        XCTAssertEqual(vm.chatMessages.count, 2)
        XCTAssertEqual(vm.chatMessages[1].content, "Réponse partielle")
        XCTAssertFalse(vm.isAsking)
        XCTAssertNil(vm.activeRequestStatusText)
        XCTAssertEqual(vm.activeRequestSystemMessage, "Réponse interrompue.")
    }

    func testRefreshModelsReturnsFalseOnFailure() async {
        let vm = PulseViewModel(bridge: makeJSONBridge(json: "{}", statusCode: 503))

        let ok = await vm.refreshModels()

        XCTAssertFalse(ok)
    }

    func testCoreHealthOkKeepsGlobalStatusHealthyWhenLLMUnavailable() {
        let vm = PulseViewModel()
        vm.isDaemonActive = true
        vm.isOllamaOnline = false
        vm.isModelSelected = false
        vm.llmReadyState = false
        vm.coreHealth = CoreHealthResponse(
            status: "ok",
            pulseMode: "core",
            experimentalEnabled: false
        )

        switch vm.serviceStatus {
        case .healthy:
            break
        default:
            XCTFail("Core health ok should keep Pulse globally healthy even when LLM is unavailable")
        }
    }

    func testDaemonBridgeDecodesCoreHealth() async throws {
        let json = """
        {
          "status": "ok",
          "pulse_mode": "core",
          "experimental_enabled": false
        }
        """
        let bridge = makeJSONBridge(json: json, path: "/health/core")

        let health = try await bridge.getCoreHealth()

        XCTAssertTrue(health.isOK)
        XCTAssertEqual(health.pulseMode, "core")
        XCTAssertEqual(health.experimentalEnabled, false)
    }

    func testToggleObservationDoesNotShowImmediateSuccessStatus() {
        let vm = PulseViewModel()
        vm.isObservingEnabled = true

        vm.toggleObservation()

        XCTAssertFalse(vm.isObservingEnabled)
        XCTAssertNil(vm.transientStatusText)
    }

    func testRefreshModelsAvailableInventoryDoesNotMakeLLMReady() async {
        let json = """
        {
          "provider": "ollama",
          "available_models": ["mistral"],
          "selected_model": "",
          "selected_command_model": "",
          "selected_summary_model": "",
          "ollama_online": true,
          "model_selected": false,
          "llm_ready": false,
          "llm_active": false
        }
        """
        let vm = PulseViewModel(bridge: makeJSONBridge(json: json))
        vm.isDaemonActive = true

        let ok = await vm.refreshModels()

        XCTAssertTrue(ok)
        XCTAssertTrue(vm.isOllamaOnline)
        XCTAssertEqual(vm.selectedModel, "")
        XCTAssertFalse(vm.isModelSelected)
        XCTAssertFalse(vm.isLLMReady)
        XCTAssertEqual(vm.llmStatusSubtitle, "Aucun modèle sélectionné")
    }

    func testRefreshModelsSelectedModelMakesLLMReady() async {
        let json = """
        {
          "provider": "ollama",
          "available_models": ["mistral"],
          "selected_model": "mistral",
          "selected_command_model": "mistral",
          "selected_summary_model": "mistral",
          "ollama_online": true,
          "model_selected": true,
          "llm_ready": true,
          "llm_active": false
        }
        """
        let vm = PulseViewModel(bridge: makeJSONBridge(json: json))
        vm.isDaemonActive = true

        let ok = await vm.refreshModels()

        XCTAssertTrue(ok)
        XCTAssertTrue(vm.isOllamaOnline)
        XCTAssertEqual(vm.selectedModel, "mistral")
        XCTAssertTrue(vm.isModelSelected)
        XCTAssertTrue(vm.isLLMReady)
        XCTAssertEqual(vm.llmStatusSubtitle, "mistral")
    }

    func testRefreshInsightsLoadsRecentProposals() async {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)

        MockURLProtocol.handler = { request in
            let url = try XCTUnwrap(request.url)
            let response = HTTPURLResponse(
                url: url,
                statusCode: 200,
                httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!

            switch url.path {
            case "/state":
                let json = """
                {
                  "active_app": "Xcode",
                  "active_project": "Pulse",
                  "session_duration_min": 42,
                  "signals": {
                    "probable_task": "coding",
                    "focus_level": "normal",
                    "friction_score": 0.2,
                    "recent_apps": ["Xcode"]
                  }
                }
                """
                return (response, Data(json.utf8))
            case "/insights":
                return (response, Data("[]".utf8))
            case "/mcp/proposals":
                let json = """
                {
                  "items": [
                    {
                      "id": "proposal-1",
                      "type": "context_injection",
                      "title": "Contexte de session prêt à être injecté",
                      "summary": "Le contexte local est jugé assez riche pour une réponse assistée.",
                      "rationale": "La session a accumulé assez de contexte local.",
                      "status": "executed",
                      "created_at": "2026-04-15T12:00:00",
                      "updated_at": "2026-04-15T12:01:00",
                      "decided_at": "2026-04-15T12:01:00"
                    }
                  ]
                }
                """
                return (response, Data(json.utf8))
            default:
                XCTFail("Chemin inattendu: \(url.path)")
                return (response, Data("{}".utf8))
            }
        }

        let vm = PulseViewModel(bridge: DaemonBridge(base: "http://127.0.0.1:8765", session: session))

        vm.refreshInsights()
        await waitUntil { !vm.recentProposals.isEmpty }

        XCTAssertEqual(vm.recentProposals.count, 1)
        XCTAssertEqual(vm.recentProposals[0].type, "context_injection")
        XCTAssertEqual(vm.recentProposals[0].status, "executed")
        XCTAssertEqual(vm.recentProposals[0].displayTitle, "Contexte de session prêt à être injecté")
    }

    func testRefreshStateUsesPresentSessionDurationBeforeSignalsAndLegacyTopLevelField() async {
        let json = """
        {
          "active_app": "Xcode",
          "active_project": "Pulse",
          "active_file": "/tmp/runtime_orchestrator.py",
          "session_duration_min": 240,
          "present": {
            "session_status": "active",
            "awake": true,
            "locked": false,
            "active_file": "/tmp/runtime_orchestrator.py",
            "active_project": "Pulse",
            "probable_task": "coding",
            "activity_level": "editing",
            "focus_level": "normal",
            "friction_score": 0.2,
            "clipboard_context": null,
            "session_duration_min": 33,
            "updated_at": "2026-04-15T12:00:00"
          },
          "signals": {
            "probable_task": "coding",
            "focus_level": "normal",
            "friction_score": 0.2,
            "session_duration_min": 45,
            "recent_apps": ["Xcode"]
          }
        }
        """
        let vm = PulseViewModel(bridge: makeJSONBridge(json: json, path: "/state"))

        vm.refreshState()
        await waitUntil { vm.sessionDuration == 33 }

        XCTAssertEqual(vm.sessionDuration, 33)
    }

    func testRefreshStateFallsBackToLegacyDurationWhenPresentIsMissing() async {
        let json = """
        {
          "active_app": "Xcode",
          "active_project": "Pulse",
          "session_duration_min": 90
        }
        """
        let vm = PulseViewModel(bridge: makeJSONBridge(json: json, path: "/state"))
        vm.sessionDuration = 12

        vm.refreshState()
        await waitUntil { vm.sessionDuration == 90 }

        XCTAssertEqual(vm.sessionDuration, 90)
    }

    func testRefreshStateKeepsZeroWhenPresentSessionDurationIsZero() async {
        let json = """
        {
          "active_app": "Xcode",
          "active_project": "Pulse",
          "session_duration_min": 90,
          "present": {
            "session_status": "active",
            "awake": true,
            "locked": false,
            "active_file": "/tmp/runtime_orchestrator.py",
            "active_project": "Pulse",
            "probable_task": "coding",
            "activity_level": "editing",
            "focus_level": "normal",
            "friction_score": 0.2,
            "clipboard_context": null,
            "session_duration_min": 0,
            "updated_at": "2026-04-15T12:00:00"
          },
          "signals": {
            "probable_task": "coding",
            "focus_level": "normal",
            "friction_score": 0.2,
            "session_duration_min": 45,
            "recent_apps": ["Xcode"]
          }
        }
        """
        let vm = PulseViewModel(bridge: makeJSONBridge(json: json, path: "/state"))
        vm.sessionDuration = 18

        vm.refreshState()
        await waitUntil { vm.sessionDuration == 0 }

        XCTAssertEqual(vm.sessionDuration, 0)
    }

    func testCurrentStateModeUsesDedicatedPanelHeight() {
        let vm = PulseViewModel()

        vm.panelMode = .currentState

        XCTAssertEqual(vm.currentPanelHeight, NotchWindow.currentStateHeight)
    }

    func testStartMcpPollingDeclencheLeRappelQuandLeDaemonRevient() async {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        let lock = NSLock()
        var pingCount = 0

        MockURLProtocol.handler = { request in
            let url = try XCTUnwrap(request.url)
            let path = url.path

            if path == "/ping" {
                lock.lock()
                pingCount += 1
                let currentCount = pingCount
                lock.unlock()

                let statusCode = currentCount == 1 ? 503 : 200
                let body = currentCount == 1
                    ? "{}"
                    : #"{"status":"ok","version":"0.1.0","paused":false}"#
                let response = HTTPURLResponse(
                    url: url,
                    statusCode: statusCode,
                    httpVersion: nil,
                    headerFields: ["Content-Type": "application/json"]
                )!
                return (response, Data(body.utf8))
            }

            if path == "/llm/models" {
                let response = HTTPURLResponse(
                    url: url,
                    statusCode: 200,
                    httpVersion: nil,
                    headerFields: ["Content-Type": "application/json"]
                )!
                let json = """
                {
                  "provider": "ollama",
                  "available_models": [],
                  "selected_model": "",
                  "selected_command_model": "",
                  "selected_summary_model": "",
                  "ollama_online": false,
                  "model_selected": false,
                  "llm_ready": false,
                  "llm_active": false
                }
                """
                return (response, Data(json.utf8))
            }

            if path == "/health/core" {
                let response = HTTPURLResponse(
                    url: url,
                    statusCode: 200,
                    httpVersion: nil,
                    headerFields: ["Content-Type": "application/json"]
                )!
                return (response, Data(#"{"status":"ok","pulse_mode":"core","experimental_enabled":false}"#.utf8))
            }

            if path == "/mcp/pending" {
                let response = HTTPURLResponse(
                    url: url,
                    statusCode: 204,
                    httpVersion: nil,
                    headerFields: ["Content-Type": "application/json"]
                )!
                return (response, Data())
            }

            if path == "/state" {
                let response = HTTPURLResponse(
                    url: url,
                    statusCode: 200,
                    httpVersion: nil,
                    headerFields: ["Content-Type": "application/json"]
                )!
                return (response, Data("{}".utf8))
            }

            if path == "/feed" {
                let response = HTTPURLResponse(
                    url: url,
                    statusCode: 200,
                    httpVersion: nil,
                    headerFields: ["Content-Type": "application/json"]
                )!
                return (response, Data("[]".utf8))
            }

            if path == "/context-probes/requests" {
                let response = HTTPURLResponse(
                    url: url,
                    statusCode: 200,
                    httpVersion: nil,
                    headerFields: ["Content-Type": "application/json"]
                )!
                return (response, Data(#"{"requests":[],"debug":[],"count":0}"#.utf8))
            }

            XCTFail("Chemin inattendu: \\(path)")
            let response = HTTPURLResponse(
                url: url,
                statusCode: 404,
                httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!
            return (response, Data("{}".utf8))
        }

        let vm = PulseViewModel(bridge: DaemonBridge(base: "http://127.0.0.1:8765", session: session))
        var didReconnect = false
        vm.onDaemonReconnected = {
            didReconnect = true
        }

        vm.startMcpPolling()
        await waitUntil { didReconnect }
        vm.stopMcpPolling()

        XCTAssertTrue(didReconnect)
    }

    func testProposalRecordClarifiesBlockingVsAutomaticFlows() {
        let blocking = ProposalRecord(
            id: "proposal-1",
            type: "risky_command",
            title: "Supprime build",
            summary: "Supprime le dossier build.",
            rationale: "Commande destructive détectée.",
            status: "pending",
            command: nil,
            translated: nil,
            riskLevel: nil,
            riskScore: nil,
            createdAt: "2026-04-15T12:00:00",
            updatedAt: "2026-04-15T12:00:00",
            decidedAt: nil,
            evidence: nil
        )
        let automatic = ProposalRecord(
            id: "proposal-2",
            type: "context_injection",
            title: "Contexte de session prêt à être injecté",
            summary: "Le contexte local est jugé assez riche pour une réponse assistée.",
            rationale: "La session a accumulé assez de contexte local.",
            status: "executed",
            command: nil,
            translated: nil,
            riskLevel: nil,
            riskScore: nil,
            createdAt: "2026-04-15T12:00:00",
            updatedAt: "2026-04-15T12:01:00",
            decidedAt: "2026-04-15T12:01:00",
            evidence: nil
        )

        XCTAssertEqual(blocking.typeLabel, "Commande risquée")
        XCTAssertEqual(blocking.flowLabel, "validation requise")
        XCTAssertEqual(blocking.statusLabel, "À valider")
        XCTAssertTrue(blocking.detailText?.contains("attend votre choix") == true)

        XCTAssertEqual(automatic.typeLabel, "Contexte assistant")
        XCTAssertEqual(automatic.flowLabel, "Lab automatique")
        XCTAssertEqual(automatic.statusLabel, "Appliquée")
        XCTAssertTrue(automatic.detailText?.contains("hors Core contrôlé") == true)
    }

    func testProposalRecordDetailFallsBackToRationaleWithoutRepeatingTitle() {
        let proposal = ProposalRecord(
            id: "proposal-1",
            type: "context_injection",
            title: "Contexte prêt",
            summary: "Contexte prêt",
            rationale: "Le contexte de session est assez riche pour aider la prochaine réponse.",
            status: "executed",
            command: nil,
            translated: nil,
            riskLevel: nil,
            riskScore: nil,
            createdAt: "2026-04-15T12:00:00",
            updatedAt: "2026-04-15T12:01:00",
            decidedAt: "2026-04-15T12:01:00",
            evidence: nil
        )

        XCTAssertTrue(proposal.detailText?.contains("Pourquoi :") == true)
        XCTAssertFalse(proposal.detailText?.contains("Contexte prêt Contexte prêt") == true)
    }

    func testSignalsDataExpliqueQuandLaTacheEstAncreeDansLesFichiers() {
        let signals = SignalsData(
            activeProject: "Pulse",
            activeFile: "/tmp/main.py",
            probableTask: "coding",
            activityLevel: "editing",
            taskConfidence: 0.92,
            focusLevel: "normal",
            frictionScore: 0.2,
            sessionDurationMin: 42,
            recentApps: ["Notes", "Cursor"],
            clipboardContext: "text",
            editedFileCount10m: 5,
            fileTypeMix10m: ["source": 3, "test": 1, "docs": 1],
            renameDeleteRatio10m: 0.2,
            dominantFileMode: "multi_file",
            workPatternCandidate: "feature_candidate",
            lastSessionContext: nil
        )

        XCTAssertEqual(signals.taskLabel, "Développement")
        XCTAssertEqual(signals.taskEvidenceLabel, "Ancré")
        XCTAssertEqual(
            signals.fileActivitySummary,
            "5 fichier(s) touché(s) sur 10 min, surtout code source (3), tests (1), documentation (1)"
        )
        XCTAssertTrue(signals.taskEvidenceSummary.contains("5 fichier(s) touché(s) sur 10 min"))
        XCTAssertTrue(signals.taskEvidenceSummary.contains("ça ressemble à une évolution de fonctionnalité"))
    }

    func testSignalsDataRendExplorationDeManiereCohérente() {
        let signals = SignalsData(
            activeProject: nil,
            activeFile: nil,
            probableTask: "exploration",
            activityLevel: "reading",
            taskConfidence: 0.61,
            focusLevel: "normal",
            frictionScore: 0.0,
            sessionDurationMin: 6,
            recentApps: ["Google Chrome"],
            clipboardContext: "url",
            editedFileCount10m: 0,
            fileTypeMix10m: [:],
            renameDeleteRatio10m: 0.0,
            dominantFileMode: "none",
            workPatternCandidate: nil,
            lastSessionContext: nil
        )

        XCTAssertEqual(signals.taskLabel, "Exploration")
        XCTAssertEqual(signals.taskAccentHex, "#EF9F27")
    }

    func testSignalsDataMarqueUnContexteFaibleQuandLesIndicesRestentLegers() {
        let signals = SignalsData(
            activeProject: nil,
            activeFile: nil,
            probableTask: "writing",
            activityLevel: "reading",
            taskConfidence: 0.3,
            focusLevel: "normal",
            frictionScore: 0.0,
            sessionDurationMin: 4,
            recentApps: ["Notes"],
            clipboardContext: "text",
            editedFileCount10m: 0,
            fileTypeMix10m: [:],
            renameDeleteRatio10m: 0.0,
            dominantFileMode: "none",
            workPatternCandidate: nil,
            lastSessionContext: nil
        )

        XCTAssertEqual(signals.taskEvidenceLabel, "Faible")
        XCTAssertEqual(
            signals.taskEvidenceSummary,
            "Le libellé vient surtout de l’app récente (Notes) car l’activité fichiers reste faible."
        )
        XCTAssertNil(signals.fileActivitySummary)
    }

    func testWorkContextCardDecodeLesNouveauxChampsEvidenceProjet() throws {
        let payload = """
        {
          "card": {
            "project": "Pulse",
            "project_hint": null,
            "project_hint_confidence": 0.0,
            "project_hint_source": null,
            "project_confidence": 0.9,
            "project_source": "active_project",
            "project_evidence": ["Projet explicite détecté", "Apps IA utilisées comme support"],
            "project_warnings": ["Tâche précise encore prudente"],
            "support_apps": ["ChatGPT"],
            "activity_level": "executing",
            "probable_task": "general",
            "confidence": 0.48,
            "evidence": ["activité terminale récente"],
            "missing_context": [],
            "safe_next_probes": []
          }
        }
        """

        let response = try JSONDecoder().decode(WorkContextCardResponse.self, from: Data(payload.utf8))
        let card = response.card

        XCTAssertEqual(card.projectConfidence, 0.9)
        XCTAssertEqual(card.projectSource, "active_project")
        XCTAssertEqual(card.projectEvidence, ["Projet explicite détecté", "Apps IA utilisées comme support"])
        XCTAssertEqual(card.projectWarnings, ["Tâche précise encore prudente"])
        XCTAssertEqual(card.supportApps, ["ChatGPT"])
    }

    func testWorkContextCardNuanceProjetFortEtTacheGenerale() throws {
        let payload = """
        {
          "card": {
            "project": "Pulse",
            "project_confidence": 0.9,
            "support_apps": ["ChatGPT"],
            "activity_level": "executing",
            "probable_task": "general",
            "confidence": 0.48
          }
        }
        """

        let card = try JSONDecoder()
            .decode(WorkContextCardResponse.self, from: Data(payload.utf8))
            .card

        XCTAssertEqual(card.projectContextLabel, "Projet corroboré")
        XCTAssertTrue(card.projectContextSummary.contains("Projet corroboré, tâche précise encore prudente."))
        XCTAssertTrue(card.projectContextSummary.contains("Apps support détectées"))
        XCTAssertTrue(card.projectContextSummary.contains("non utilisées comme preuve projet principale"))
    }

    func testWorkContextCardGardeUnWordingPrudentQuandProjetFaible() throws {
        let payload = """
        {
          "card": {
            "project": null,
            "project_confidence": 0.2,
            "support_apps": ["ChatGPT"],
            "activity_level": "reading",
            "probable_task": "general",
            "confidence": 0.3
          }
        }
        """

        let card = try JSONDecoder()
            .decode(WorkContextCardResponse.self, from: Data(payload.utf8))
            .card

        XCTAssertEqual(card.projectContextLabel, "Contexte faible")
        XCTAssertTrue(card.projectContextSummary.contains("Contexte projet encore faible."))
        XCTAssertFalse(card.projectContextSummary.contains("Projet corroboré, tâche précise encore prudente."))
    }

    func testSignalsDataNExposePasOtherCommeLectureUtileQuandUnTypeConcretExiste() {
        let signals = SignalsData(
            activeProject: "Pulse",
            activeFile: "/tmp/main.py",
            probableTask: "coding",
            activityLevel: "editing",
            taskConfidence: 0.9,
            focusLevel: "normal",
            frictionScore: 0.2,
            sessionDurationMin: 12,
            recentApps: ["Cursor"],
            clipboardContext: nil,
            editedFileCount10m: 7,
            fileTypeMix10m: ["other": 5, "source": 2],
            renameDeleteRatio10m: 0.0,
            dominantFileMode: "few_files",
            workPatternCandidate: nil,
            lastSessionContext: nil
        )

        XCTAssertEqual(
            signals.fileActivitySummary,
            "7 fichier(s) touché(s) sur 10 min, surtout code source (2)"
        )
    }

    func testSignalsDataRetombeSurUnResumeSimpleQuandLeMixResteTropGenerique() {
        let signals = SignalsData(
            activeProject: "Pulse",
            activeFile: "/tmp/main.py",
            probableTask: "general",
            activityLevel: "editing",
            taskConfidence: 0.22,
            focusLevel: "normal",
            frictionScore: 0.0,
            sessionDurationMin: 8,
            recentApps: ["Cursor"],
            clipboardContext: nil,
            editedFileCount10m: 13,
            fileTypeMix10m: ["other": 13],
            renameDeleteRatio10m: 0.0,
            dominantFileMode: "multi_file",
            workPatternCandidate: nil,
            lastSessionContext: nil
        )

        XCTAssertEqual(signals.fileActivitySummary, "13 fichier(s) touché(s) sur 10 min")
    }

    func testUpdateSelectedModelUsesSelectedModelAsPrimaryResponseField() async {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)

        MockURLProtocol.handler = { request in
            if request.url?.path == "/feed" {
                let response = HTTPURLResponse(
                    url: try XCTUnwrap(request.url),
                    statusCode: 200,
                    httpVersion: nil,
                    headerFields: ["Content-Type": "application/json"]
                )!
                return (response, Data("[]".utf8))
            }
            if request.url?.path == "/context-probes/requests" {
                let response = HTTPURLResponse(
                    url: try XCTUnwrap(request.url),
                    statusCode: 200,
                    httpVersion: nil,
                    headerFields: ["Content-Type": "application/json"]
                )!
                return (response, Data(#"{"requests":[],"debug":[],"count":0}"#.utf8))
            }
            XCTAssertEqual(request.url?.path, "/llm/model")
            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 200,
                httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!
            let json = """
            {
              "ok": true,
              "selected_model": "mistral",
              "selected_command_model": "mistral",
              "selected_summary_model": "mistral"
            }
            """
            return (response, Data(json.utf8))
        }

        let vm = PulseViewModel(bridge: DaemonBridge(base: "http://127.0.0.1:8765", session: session))
        vm.selectedModel = "llama3"
        vm.selectedCommandModel = "llama3"
        vm.selectedSummaryModel = "llama3"

        vm.updateSelectedModel("mistral")
        await waitUntil { !vm.isUpdatingModel }

        XCTAssertEqual(vm.selectedModel, "mistral")
        XCTAssertEqual(vm.selectedCommandModel, "mistral")
        XCTAssertEqual(vm.selectedSummaryModel, "mistral")
    }

    func testStateResponseDecodesPresentAndCurrentContext() throws {
        let json = """
        {
          "active_app": "Xcode",
          "active_file": "/tmp/legacy.swift",
          "active_project": "LegacyProject",
          "session_duration_min": 42,
          "runtime_paused": false,
          "present": {
            "session_status": "active",
            "awake": true,
            "locked": false,
            "active_file": "/tmp/live.swift",
            "active_project": "Pulse",
            "probable_task": "debug",
            "activity_level": "executing",
            "focus_level": "deep",
            "friction_score": 0.18,
            "clipboard_context": "code",
            "session_duration_min": 33,
            "updated_at": "2026-04-23T12:00:00"
          },
          "current_episode": {
            "id": "ep-1",
            "session_id": "session-1",
            "started_at": "2026-04-23T11:50:00",
            "ended_at": null,
            "boundary_reason": null,
            "duration_sec": null,
            "active_project": "Pulse",
            "probable_task": "coding",
            "activity_level": "editing",
            "task_confidence": 0.86
          },
          "current_context": {
            "id": "ctx-1",
            "session_id": "session-1",
            "started_at": "2026-04-23T11:55:00",
            "ended_at": null,
            "boundary_reason": null,
            "duration_sec": null,
            "active_project": "Pulse",
            "probable_task": "debug",
            "activity_level": "executing",
            "task_confidence": 0.92
          },
          "recent_sessions": [
            {
              "id": "session-recent",
              "session_id": "session-0",
              "started_at": "2026-04-23T10:00:00",
              "ended_at": "2026-04-23T10:20:00",
              "boundary_reason": "session_end",
              "duration_sec": 1200,
              "active_project": "Pulse",
              "probable_task": "coding",
              "activity_level": null,
              "task_confidence": null
            }
          ],
          "signals": {
            "active_project": "SignalsProject",
            "active_file": "/tmp/signals.swift",
            "probable_task": "general",
            "activity_level": "reading",
            "task_confidence": 0.12,
            "focus_level": "scattered",
            "friction_score": 0.72,
            "session_duration_min": 12,
            "recent_apps": ["Chrome"],
            "clipboard_context": "text"
          }
        }
        """

        let state = try JSONDecoder().decode(StateResponse.self, from: Data(json.utf8))

        XCTAssertEqual(state.present?.activeProject, "Pulse")
        XCTAssertEqual(state.present?.probableTask, "debug")
        XCTAssertEqual(state.currentContext?.activeProject, "Pulse")
        XCTAssertEqual(state.currentContext?.probableTask, "debug")
        XCTAssertEqual(state.recentSessions?.first?.id, "session-recent")
        XCTAssertEqual(state.signals?.activeProject, "SignalsProject")
    }

    func testStateResponseDefaultsMissingOrNullSessionDurationToZero() throws {
        let missing = try JSONDecoder().decode(StateResponse.self, from: Data(#"{"current_context":null}"#.utf8))
        let nullValue = try JSONDecoder().decode(StateResponse.self, from: Data(#"{"session_duration_min":null}"#.utf8))

        XCTAssertEqual(missing.sessionDurationMin, 0)
        XCTAssertEqual(nullValue.sessionDurationMin, 0)
        XCTAssertNil(missing.currentContext)
    }

    func testRefreshStateBuildsProductStateFromCurrentContextBeforeLegacyAlias() async {
        let json = """
        {
          "active_app": "Xcode",
          "active_file": "/tmp/legacy.swift",
          "active_project": "LegacyProject",
          "session_duration_min": 42,
          "runtime_paused": false,
          "present": {
            "session_status": "active",
            "awake": true,
            "locked": false,
            "active_file": "/tmp/live.swift",
            "active_project": "Pulse",
            "probable_task": "debug",
            "activity_level": "executing",
            "focus_level": "deep",
            "friction_score": 0.18,
            "clipboard_context": "code",
            "session_duration_min": 33,
            "updated_at": "2026-04-23T12:00:00"
          },
          "current_episode": {
            "id": "ep-1",
            "session_id": "session-1",
            "started_at": "2026-04-23T11:50:00",
            "ended_at": null,
            "boundary_reason": null,
            "duration_sec": null,
            "active_project": "Pulse",
            "probable_task": "coding",
            "activity_level": "editing",
            "task_confidence": 0.86
          },
          "current_context": {
            "id": "ctx-1",
            "session_id": "session-1",
            "started_at": "2026-04-23T11:55:00",
            "ended_at": null,
            "boundary_reason": null,
            "duration_sec": null,
            "active_project": "Pulse",
            "probable_task": "debug",
            "activity_level": "executing",
            "task_confidence": 0.92
          },
          "signals": {
            "active_project": "SignalsProject",
            "active_file": "/tmp/signals.swift",
            "probable_task": "general",
            "activity_level": "reading",
            "task_confidence": 0.12,
            "focus_level": "scattered",
            "friction_score": 0.72,
            "session_duration_min": 12,
            "recent_apps": ["Chrome"],
            "clipboard_context": "text"
          }
        }
        """
        let vm = PulseViewModel(bridge: makeJSONBridge(json: json, path: "/state"))

        vm.refreshState()
        await waitUntil { vm.currentContext != nil && vm.currentPresent != nil }

        XCTAssertEqual(vm.currentContext?.activeProject, "Pulse")
        XCTAssertEqual(vm.currentContext?.probableTask, "debug")
        XCTAssertEqual(vm.currentPresent?.probableTask, "debug")
        XCTAssertEqual(vm.activeProject, "Pulse")
        XCTAssertEqual(vm.probableTask, "debug")
        XCTAssertEqual(vm.activeFile, "/tmp/live.swift")
        XCTAssertEqual(vm.sessionDuration, 33)
        XCTAssertEqual(vm.focusLevel, "deep")
        XCTAssertEqual(vm.frictionScore, 0.18, accuracy: 0.001)
        XCTAssertEqual(vm.recentApps, ["Chrome"])
    }

    func testTodaySummaryDecodesWorkBlocks() throws {
        let json = """
        {
          "date": "2026-04-29",
          "generated_at": "2026-04-29T17:20:00",
          "totals": {
            "worked_min": 42,
            "active_min": 42,
            "commit_count": 3,
            "window_count": 1,
            "project_count": 1
          },
          "projects": [
            {
              "name": "Pulse",
              "worked_min": 42,
              "active_min": 42,
              "commit_count": 3,
              "top_tasks": ["coding"]
            }
          ],
          "work_blocks": [
            {
              "id": "work-1",
              "started_at": "2026-04-29T16:38:00",
              "ended_at": "2026-04-29T17:20:00",
              "duration_min": 42,
              "event_count": 12,
              "project": "Pulse",
              "probable_task": "coding",
              "activity_level": "editing",
              "top_files": ["DashboardRootView.swift", "DaemonBridgeModels.swift"]
            }
          ],
          "timeline": {
            "first_activity_at": "2026-04-29T16:38:00",
            "last_activity_at": "2026-04-29T17:20:00"
          },
          "current_window": {
            "id": "work-1",
            "started_at": "2026-04-29T16:38:00",
            "updated_at": "2026-04-29T17:20:00",
            "project": "Pulse",
            "probable_task": "coding",
            "activity_level": "editing",
            "commit_count": 3
          }
        }
        """

        let summary = try JSONDecoder().decode(TodaySummaryResponse.self, from: Data(json.utf8))

        XCTAssertEqual(summary.workBlocks.count, 1)
        XCTAssertEqual(summary.workBlocks.first?.project, "Pulse")
        XCTAssertEqual(summary.workBlocks.first?.taskLabel, "Développement")
        XCTAssertEqual(summary.workBlocks.first?.activityLabel, "Édition")
        XCTAssertEqual(summary.workBlocks.first?.topFiles, ["DashboardRootView.swift", "DaemonBridgeModels.swift"])
        XCTAssertEqual(summary.currentWindow?.commitCount, 3)
    }

    func testDashboardRefreshFetchesExecutedContextProbeDetails() async {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        let listJSON = """
        {
          "requests": [
            {
              "request_id": "manual-1",
              "kind": "manual_context_note",
              "reason": "Need context",
              "policy": {
                "kind": "manual_context_note",
                "consent": "explicit_each_time",
                "privacy": "content_sensitive",
                "retention": "ephemeral",
                "allow_raw_value": false,
                "allow_persistent_storage": false,
                "requires_user_visible_reason": true,
                "max_chars": 2000
              },
              "status": "executed",
              "created_at": "2026-05-14T10:00:00",
              "expires_at": null,
              "decided_at": "2026-05-14T10:01:00",
              "executed_at": "2026-05-14T10:02:00",
              "decision_reason": "Approved",
              "metadata_keys": [],
              "is_terminal": true
            },
            {
              "request_id": "clipboard-1",
              "kind": "clipboard_sample",
              "reason": "Need context",
              "policy": {
                "kind": "clipboard_sample",
                "consent": "explicit_each_time",
                "privacy": "content_sensitive",
                "retention": "ephemeral",
                "allow_raw_value": false,
                "allow_persistent_storage": false,
                "requires_user_visible_reason": true,
                "max_chars": 4000
              },
              "status": "executed",
              "created_at": "2026-05-14T10:00:00",
              "expires_at": null,
              "decided_at": "2026-05-14T10:01:00",
              "executed_at": "2026-05-14T10:02:00",
              "decision_reason": "Approved",
              "metadata_keys": [],
              "is_terminal": true
            }
          ],
          "debug": [],
          "count": 2
        }
        """
        let manualDetailJSON = contextProbeDetailJSON(
            requestId: "manual-1",
            kind: "manual_context_note",
            source: "manual_context_note",
            redactedValue: "note [REDACTED_TOKEN]",
            charCount: 42
        )
        let clipboardDetailJSON = contextProbeDetailJSON(
            requestId: "clipboard-1",
            kind: "clipboard_sample",
            source: "next_clipboard_text",
            redactedValue: "copied [REDACTED_TOKEN]",
            charCount: 84
        )

        MockURLProtocol.handler = { request in
            let path = try XCTUnwrap(request.url?.path)
            let body: String
            switch path {
            case "/context-probes/requests":
                body = listJSON
            case "/context-probes/requests/manual-1":
                body = manualDetailJSON
            case "/context-probes/requests/clipboard-1":
                body = clipboardDetailJSON
            default:
                XCTFail("Unexpected path \(path)")
                body = "{}"
            }
            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 200,
                httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!
            return (response, Data(body.utf8))
        }
        let bridge = DaemonBridge(base: "http://127.0.0.1:8765", session: session)
        let vm = DashboardViewModel(bridge: bridge)

        await vm.refreshContextProbeRequests()

        XCTAssertEqual(vm.contextProbeRequests.count, 2)
        XCTAssertEqual(vm.contextProbeResults["manual-1"]?.data["source"]?.displayValue, "manual_context_note")
        XCTAssertEqual(vm.contextProbeResults["manual-1"]?.data["char_count"]?.displayValue, "42")
        XCTAssertEqual(vm.contextProbeResults["manual-1"]?.data["redacted_value"]?.displayValue, "note [REDACTED_TOKEN]")
        XCTAssertEqual(vm.contextProbeResults["clipboard-1"]?.data["source"]?.displayValue, "next_clipboard_text")
        XCTAssertEqual(vm.contextProbeResults["clipboard-1"]?.data["char_count"]?.displayValue, "84")
        XCTAssertEqual(vm.contextProbeResults["clipboard-1"]?.data["redacted_value"]?.displayValue, "copied [REDACTED_TOKEN]")
    }

    func testDashboardHandlesNotchSubmittedManualContextResultNotification() async {
        let bridge = makeContextProbeNotificationBridge(
            requestId: "manual-1",
            kind: "manual_context_note",
            source: "manual_context_note",
            redactedValue: "latest note [REDACTED_TOKEN]",
            charCount: 33
        )
        let vm = DashboardViewModel(bridge: bridge)

        NotificationCenter.default.post(name: .contextProbeResultSubmitted, object: "manual-1")
        await waitUntil { vm.contextProbeResults["manual-1"] != nil }

        XCTAssertEqual(vm.contextProbeRequests.first?.status, "executed")
        XCTAssertEqual(vm.contextProbeResults["manual-1"]?.data["source"]?.displayValue, "manual_context_note")
        XCTAssertEqual(vm.contextProbeResults["manual-1"]?.data["redacted_value"]?.displayValue, "latest note [REDACTED_TOKEN]")
    }

    func testDashboardHandlesNotchSubmittedClipboardResultNotification() async {
        let bridge = makeContextProbeNotificationBridge(
            requestId: "clipboard-1",
            kind: "clipboard_sample",
            source: "next_clipboard_text",
            redactedValue: "latest clipboard [REDACTED_TOKEN]",
            charCount: 64
        )
        let vm = DashboardViewModel(bridge: bridge)

        NotificationCenter.default.post(name: .contextProbeResultSubmitted, object: "clipboard-1")
        await waitUntil { vm.contextProbeResults["clipboard-1"] != nil }

        XCTAssertEqual(vm.contextProbeRequests.first?.status, "executed")
        XCTAssertEqual(vm.contextProbeResults["clipboard-1"]?.data["source"]?.displayValue, "next_clipboard_text")
        XCTAssertEqual(vm.contextProbeResults["clipboard-1"]?.data["char_count"]?.displayValue, "64")
        XCTAssertEqual(vm.contextProbeResults["clipboard-1"]?.data["redacted_value"]?.displayValue, "latest clipboard [REDACTED_TOKEN]")
    }

    func testWorkIntentCandidateModelDecodesDashboardFields() throws {
        let payload = try JSONDecoder().decode(
            WorkIntentCandidateListResponse.self,
            from: Data(workIntentCandidatesJSON(status: "candidate").utf8)
        )

        let candidate = try XCTUnwrap(payload.candidates.first)
        XCTAssertEqual(payload.count, 1)
        XCTAssertEqual(candidate.candidateId, "candidate-1")
        XCTAssertEqual(candidate.summary, "Réduire les coûts cachés du modèle local")
        XCTAssertEqual(candidate.source, "manual_context_note")
        XCTAssertEqual(candidate.sourceLabel, "Note rapide")
        XCTAssertEqual(candidate.project, "Pulse")
        XCTAssertEqual(candidate.confidence, 0.9)
        XCTAssertEqual(candidate.confidenceLabel, "90 %")
        XCTAssertEqual(candidate.evidenceRefs, ["context_probe:manual-1"])
        XCTAssertEqual(candidate.status, "candidate")
        XCTAssertTrue(candidate.canAcceptOrRefuse)
    }

    func testDashboardRefreshLoadsWorkIntentCandidates() async {
        let bridge = makeWorkIntentCandidateBridge()
        let vm = DashboardViewModel(bridge: bridge)

        await vm.refreshWorkIntentCandidates()

        XCTAssertEqual(vm.workIntentCandidates.count, 1)
        XCTAssertEqual(vm.workIntentCandidates.first?.summary, "Réduire les coûts cachés du modèle local")
        XCTAssertEqual(vm.workIntentCandidates.first?.project, "Pulse")
    }

    func testDashboardAcceptsWorkIntentCandidateAndRefreshesContext() async throws {
        let recorder = RequestCallRecorder()
        let bridge = makeWorkIntentCandidateBridge { request in
            recorder.record(request)
        }
        let vm = DashboardViewModel(bridge: bridge)
        let candidate = try XCTUnwrap(
            try JSONDecoder()
                .decode(WorkIntentCandidateListResponse.self, from: Data(workIntentCandidatesJSON(status: "candidate").utf8))
                .candidates
                .first
        )

        await vm.acceptWorkIntentCandidate(candidate)

        let recordedCalls = recorder.snapshot
        XCTAssertTrue(recordedCalls.contains("POST /work-intent/candidates/candidate-1/accept"))
        XCTAssertTrue(recordedCalls.contains("GET /work-intent/candidates"))
        XCTAssertTrue(recordedCalls.contains("GET /work-context"))
        XCTAssertTrue(recordedCalls.contains("GET /state"))
        XCTAssertEqual(vm.workContextCard?.project, "Pulse")
        XCTAssertEqual(vm.state?.present?.workIntent?.summary, "Réduire les coûts cachés du modèle local")
    }

    func testDashboardRefusesWorkIntentCandidateAndRefreshesCandidates() async throws {
        let recorder = RequestCallRecorder()
        let bridge = makeWorkIntentCandidateBridge { request in
            recorder.record(request)
        }
        let vm = DashboardViewModel(bridge: bridge)
        let candidate = try XCTUnwrap(
            try JSONDecoder()
                .decode(WorkIntentCandidateListResponse.self, from: Data(workIntentCandidatesJSON(status: "candidate").utf8))
                .candidates
                .first
        )

        await vm.refuseWorkIntentCandidate(candidate)

        let recordedCalls = recorder.snapshot
        XCTAssertTrue(recordedCalls.contains("POST /work-intent/candidates/candidate-1/refuse"))
        XCTAssertTrue(recordedCalls.contains("GET /work-intent/candidates"))
        XCTAssertFalse(recordedCalls.contains("POST /work-intent/candidates/candidate-1/accept"))
    }

    func testContextProbeQuickNoteChoiceSwitchesNotchStateWithoutCapture() {
        let vm = PulseViewModel()
        vm.pendingContextProbe = contextProbeRequest(kind: "focused_element_text", status: "pending")

        vm.showManualContextNoteInput()

        XCTAssertEqual(vm.contextInputMode, .manualNote)
        XCTAssertEqual(vm.contextManualNoteText, "")
        XCTAssertNotNil(vm.pendingContextProbe)
    }

    func testClipboardContextArmedStateHasNoVisibleCountdown() async {
        let bridge = makeClipboardChoiceBridge()
        let vm = PulseViewModel(bridge: bridge)
        vm.pendingContextProbe = contextProbeRequest(kind: "focused_element_text", status: "pending")

        await vm.chooseNextClipboardContext()

        XCTAssertEqual(vm.contextInputMode, .clipboardArmed)
        XCTAssertEqual(vm.contextInputStatusText, "En attente du prochain texte copié...")
        XCTAssertFalse((vm.contextInputStatusText ?? "").contains("60"))
        XCTAssertFalse((vm.contextInputStatusText ?? "").localizedCaseInsensitiveContains("délai"))
    }

    func testClipboardContextCreateIncludesActiveProjectMetadata() async {
        var createBody: [String: Any] = [:]
        let bridge = makeClipboardChoiceBridge { request in
            if request.httpMethod == "POST", request.url?.path == "/context-probes/requests" {
                createBody = Self.jsonBody(from: request)
            }
        }
        let vm = PulseViewModel(bridge: bridge)
        vm.activeProject = "Pulse"
        vm.pendingContextProbe = contextProbeRequest(kind: "focused_element_text", status: "pending")

        await vm.chooseNextClipboardContext()

        let metadata = try? XCTUnwrap(createBody["metadata"] as? [String: Any])
        XCTAssertEqual(metadata?["source"] as? String, "notch_next_clipboard")
        XCTAssertEqual(metadata?["project"] as? String, "Pulse")
    }

    func testManualContextCreateIncludesActiveProjectMetadata() async {
        var createBody: [String: Any] = [:]
        let bridge = makeManualNoteSubmitBridge { request in
            if request.httpMethod == "POST", request.url?.path == "/context-probes/requests" {
                createBody = Self.jsonBody(from: request)
            }
        }
        let vm = PulseViewModel(bridge: bridge)
        vm.activeProject = "Pulse"
        vm.pendingContextProbe = contextProbeRequest(kind: "focused_element_text", status: "pending")
        vm.contextManualNoteText = "objectif de travail"

        await vm.submitManualContextNote()

        let metadata = try? XCTUnwrap(createBody["metadata"] as? [String: Any])
        XCTAssertEqual(metadata?["source"] as? String, "notch_manual_note")
        XCTAssertEqual(metadata?["project"] as? String, "Pulse")
    }

    func testContextProbeCreateOmitsBlankProjectMetadata() async {
        var createBody: [String: Any] = [:]
        let bridge = makeClipboardChoiceBridge { request in
            if request.httpMethod == "POST", request.url?.path == "/context-probes/requests" {
                createBody = Self.jsonBody(from: request)
            }
        }
        let vm = PulseViewModel(bridge: bridge)
        vm.activeProject = "   "
        vm.pendingContextProbe = contextProbeRequest(kind: "focused_element_text", status: "pending")

        await vm.chooseNextClipboardContext()

        let metadata = try? XCTUnwrap(createBody["metadata"] as? [String: Any])
        XCTAssertEqual(metadata?["source"] as? String, "notch_next_clipboard")
        XCTAssertNil(metadata?["project"])
    }

    func testClipboardContextCancelClosesAndResetsState() async {
        let vm = PulseViewModel()
        vm.pendingContextProbe = contextProbeRequest(kind: "clipboard_sample", status: "approved")
        vm.contextInputMode = .clipboardArmed
        vm.contextInputStatusText = "En attente du prochain texte copié..."
        vm.isExpanded = true

        await vm.ignorePendingContextInput()

        XCTAssertNil(vm.pendingContextProbe)
        XCTAssertFalse(vm.isExpanded)
        XCTAssertEqual(vm.contextInputMode, .choosing)
        XCTAssertNil(vm.contextInputStatusText)
    }

    func testClipboardContextCancelAbortsConcreteClipboardRequest() async {
        var calls: [String] = []
        let bridge = makeClipboardCancelBridge { method, path in
            calls.append("\(method) \(path)")
        }
        let vm = PulseViewModel(bridge: bridge)
        vm.pendingContextProbe = contextProbeRequest(kind: "focused_element_text", status: "pending")
        vm.isExpanded = true

        await vm.chooseNextClipboardContext()
        await vm.ignorePendingContextInput()

        XCTAssertTrue(calls.contains("POST /context-probes/requests/clipboard-created/abort"))
        XCTAssertNil(vm.pendingContextProbe)
        XCTAssertFalse(vm.isExpanded)
        XCTAssertEqual(vm.contextInputMode, .choosing)
    }

    func testClipboardContextCancelResetsEvenWhenAbortFails() async {
        let bridge = makeClipboardCancelBridge(abortStatusCode: 503) { _, _ in }
        let vm = PulseViewModel(bridge: bridge)
        vm.pendingContextProbe = contextProbeRequest(kind: "focused_element_text", status: "pending")
        vm.isExpanded = true

        await vm.chooseNextClipboardContext()
        await vm.ignorePendingContextInput()

        XCTAssertNil(vm.pendingContextProbe)
        XCTAssertFalse(vm.isExpanded)
        XCTAssertEqual(vm.contextInputMode, .choosing)
    }

    func testClipboardContextSuccessfulSubmitClosesAndResetsNotch() async {
        let bridge = makeSubmitContextProbeResultBridge(
            requestId: "clipboard-1",
            kind: "clipboard_sample",
            source: "next_clipboard_text"
        )
        let vm = PulseViewModel(bridge: bridge)
        vm.pendingContextProbe = contextProbeRequest(kind: "clipboard_sample", status: "approved")
        vm.contextInputMode = .clipboardArmed
        vm.contextInputStatusText = "En attente du prochain texte copié..."
        vm.isExpanded = true

        await vm.submitContextTextProbeResult(
            requestId: "clipboard-1",
            capture: .nextClipboardText("fresh context")
        )

        XCTAssertNil(vm.pendingContextProbe)
        XCTAssertFalse(vm.isExpanded)
        XCTAssertEqual(vm.contextInputMode, .submitted)
        XCTAssertEqual(vm.contextInputStatusText, "Contexte envoyé.")
    }

    func testClipboardContextSuccessfulSubmitDoesNotAbortExecutedRequest() async {
        var calls: [String] = []
        let bridge = makeSubmitContextProbeResultBridge(
            requestId: "clipboard-1",
            kind: "clipboard_sample",
            source: "next_clipboard_text",
            record: { method, path in calls.append("\(method) \(path)") }
        )
        let vm = PulseViewModel(bridge: bridge)
        vm.pendingContextProbe = contextProbeRequest(kind: "clipboard_sample", status: "approved")
        vm.contextInputMode = .clipboardArmed

        await vm.submitContextTextProbeResult(
            requestId: "clipboard-1",
            capture: .nextClipboardText("fresh context")
        )

        XCTAssertEqual(calls, ["POST /context-probes/requests/clipboard-1/result"])
    }

    func testContextProbeInitialPendingCancelStillRefuses() async {
        var calls: [String] = []
        let bridge = makePendingContextProbeRefuseBridge { method, path in
            calls.append("\(method) \(path)")
        }
        let vm = PulseViewModel(bridge: bridge)
        vm.pendingContextProbe = contextProbeRequest(kind: "focused_element_text", status: "pending")

        await vm.ignorePendingContextInput()

        XCTAssertEqual(calls, ["POST /context-probes/requests/focused_element_text-pending/refuse"])
        XCTAssertNil(vm.pendingContextProbe)
    }

    func testTimelineLabelsExposeGitDeliveryAsPhase() {
        XCTAssertEqual(
            episodeScopeLabel(scope: "git", task: "terminal_execution"),
            "Phase Git / livraison"
        )
        XCTAssertEqual(
            episodeScopeLabel(scope: "memory", task: "coding"),
            "Mémoire"
        )
    }

    func testDashboardSectionLabelsUseProductNavigation() {
        XCTAssertEqual(DashboardSection.session.rawValue, "Aujourd’hui")
        XCTAssertEqual(DashboardSection.notifications.rawValue, "Notifications")
        XCTAssertEqual(DashboardSection.episodes.rawValue, "Séquences debug")
        XCTAssertEqual(DashboardSection.memory.rawValue, "Mémoire (Lab)")
        XCTAssertEqual(DashboardSection.daydream.rawValue, "DayDream (Lab)")
        XCTAssertEqual(DashboardSection.contextProbes.rawValue, "Contexte (Lab)")
    }

    func testDashboardSurfacesExposeProductAndDebugLabSections() {
        XCTAssertEqual(DashboardSurface.product.rawValue, "Produit")
        XCTAssertEqual(DashboardSurface.debugLab.rawValue, "Debug / Lab")

        XCTAssertEqual(DashboardSurface.product.defaultSection, .session)
        XCTAssertEqual(DashboardSurface.product.sections, [
            .session,
            .notifications,
        ])

        XCTAssertEqual(DashboardSurface.debugLab.defaultSection, .episodes)
        XCTAssertEqual(DashboardSurface.debugLab.sections, [
            .episodes,
            .observation,
            .events,
            .mcp,
            .system,
            .memory,
            .daydream,
            .contextProbes,
        ])

        XCTAssertTrue(DashboardSurface.product.contains(.session))
        XCTAssertFalse(DashboardSurface.product.contains(.episodes))
        XCTAssertTrue(DashboardSurface.debugLab.contains(.contextProbes))
        XCTAssertFalse(DashboardSurface.debugLab.contains(.notifications))
    }

    func testTimelineCommitEvidenceLabelsAreUserFacing() {
        XCTAssertEqual(evidenceLabel("file_scope"), "Rattaché par fichiers")
        XCTAssertEqual(evidenceLabel("temporal_only"), "Lien temporel à vérifier")
        XCTAssertEqual(flagLabel("linked_by_journal_file_window"), "Fenêtre confirmée par le journal")
        XCTAssertEqual(flagLabel("work_episode_link"), "Commit rattaché au travail")
        XCTAssertEqual(flagLabel("delayed_delivery"), "Livré après le travail")
    }

    func testDebugCommitEpisodeLinkDecodesEvidenceFields() throws {
        let json = """
        {
          "id": "commit-link-1",
          "entry_id": "entry-1",
          "commit_subject": "fix(dashboard): simplify dashboard navigation",
          "delivered_at": "2026-05-16T18:57:57",
          "journal_started_at": "2026-05-16T15:50:11",
          "journal_ended_at": "2026-05-16T16:25:23",
          "episode_id": "work-episode-2026-05-16T16:24:29",
          "candidate_id": "journal-file-window-entry-1",
          "episode_started_at": "2026-05-16T16:24:29",
          "episode_ended_at": "2026-05-16T16:58:00",
          "evidence_candidate_id": "journal-file-window-entry-1",
          "evidence_episode_id": "journal-file-window-entry-1",
          "evidence_started_at": "2026-05-16T15:50:11",
          "evidence_ended_at": "2026-05-16T16:25:23",
          "evidence_source": "journal_file_window",
          "confidence": 0.93,
          "status": "linked",
          "link_reason": "linked_by_journal_file_window",
          "flags": ["work_episode_link"],
          "evidence_level": "file_scope"
        }
        """

        let link = try JSONDecoder().decode(DebugCommitEpisodeLink.self, from: Data(json.utf8))

        XCTAssertEqual(link.episodeId, "work-episode-2026-05-16T16:24:29")
        XCTAssertEqual(link.evidenceCandidateId, "journal-file-window-entry-1")
        XCTAssertEqual(link.evidenceEpisodeId, "journal-file-window-entry-1")
        XCTAssertEqual(link.evidenceStartedAt, "2026-05-16T15:50:11")
        XCTAssertEqual(link.evidenceEndedAt, "2026-05-16T16:25:23")
        XCTAssertEqual(link.evidenceSource, "journal_file_window")
    }

    func testDebugCommitEpisodeLinkDecodesWithoutEvidenceFields() throws {
        let json = """
        {
          "id": "commit-link-1",
          "entry_id": "entry-1",
          "episode_id": "work-episode-1",
          "episode_started_at": "2026-05-16T16:24:29",
          "episode_ended_at": "2026-05-16T16:58:00",
          "status": "linked"
        }
        """

        let link = try JSONDecoder().decode(DebugCommitEpisodeLink.self, from: Data(json.utf8))

        XCTAssertEqual(link.episodeId, "work-episode-1")
        XCTAssertNil(link.evidenceCandidateId)
        XCTAssertNil(link.evidenceStartedAt)
        XCTAssertNil(link.evidenceSource)
    }

    func testCommitLinkWindowLabelsSeparateDisplayEvidenceAndJournal() throws {
        let json = """
        {
          "id": "commit-link-1",
          "entry_id": "entry-1",
          "journal_started_at": "2026-05-16T15:50:11",
          "journal_ended_at": "2026-05-16T16:25:23",
          "episode_id": "work-episode-1",
          "episode_started_at": "2026-05-16T16:24:29",
          "episode_ended_at": "2026-05-16T16:58:00",
          "evidence_started_at": "2026-05-16T15:50:11",
          "evidence_ended_at": "2026-05-16T16:25:23",
          "evidence_source": "journal_file_window",
          "status": "linked"
        }
        """
        let link = try JSONDecoder().decode(DebugCommitEpisodeLink.self, from: Data(json.utf8))

        XCTAssertTrue(commitLinkDisplayEpisodeWindowLabel(link)?.contains("Épisode affiché") == true)
        XCTAssertTrue(commitLinkEvidenceWindowLabel(link)?.contains("Preuve de rattachement (journal_file_window)") == true)
        XCTAssertTrue(commitLinkJournalWindowLabel(link)?.contains("Fenêtre journal") == true)
    }

    func testTimelineImportantFlagsHideRawNoFileDebugFlag() {
        let flags = importantFlags([
            "no_file_scope_match",
            "linked_by_journal_file_window",
            "work_episode_link",
            "delayed_delivery",
            "temporal_only_link",
        ])

        XCTAssertEqual(flags, [
            "linked_by_journal_file_window",
            "work_episode_link",
            "delayed_delivery",
            "temporal_only_link",
        ])
    }

    func testTimelineDeliveredAtLabelUsesDeliveryWording() {
        XCTAssertEqual(deliveredAtLabel("2026-05-16T14:34:24"), "Livré à 14:34")
        XCTAssertNil(deliveredAtLabel(nil))
    }

    func testWorkTimelineCreatesSyntheticJournalWindowItem() throws {
        let link = try decodeCommitEpisodeLink("""
        {
          "id": "commit-link-1",
          "entry_id": "entry-1",
          "commit_subject": "fix(memory): simplify Apple commit summary prompt",
          "episode_id": "journal-file-window-entry-1",
          "episode_started_at": "2026-05-17T14:13:44",
          "episode_ended_at": "2026-05-17T14:48:41",
          "project": "Pulse",
          "status": "linked",
          "flags": ["display_uses_journal_window", "visible_episode_coverage_low", "linked_by_journal_file_window"],
          "evidence_level": "file_scope"
        }
        """)

        let items = buildWorkTimelineItems(episodes: [], commitLinks: [link])

        XCTAssertEqual(items.count, 1)
        XCTAssertTrue(items[0].isSyntheticJournalWindow)
        XCTAssertEqual(items[0].id, "journal-file-window-entry-1")
        XCTAssertEqual(items[0].episode.startedAt, "2026-05-17T14:13:44")
        XCTAssertEqual(items[0].episode.endedAt, "2026-05-17T14:48:41")
        XCTAssertEqual(items[0].episode.project, "Pulse")
        XCTAssertEqual(items[0].linkedCommits.map(\.id), ["commit-link-1"])
    }

    func testWorkTimelineCreatesSyntheticItemFromDisplayFlag() throws {
        let link = try decodeCommitEpisodeLink("""
        {
          "id": "commit-link-1",
          "entry_id": "entry-1",
          "commit_subject": "fix(memory): simplify Apple commit summary prompt",
          "episode_id": "journal-window-custom",
          "episode_started_at": "2026-05-17T14:13:44",
          "episode_ended_at": "2026-05-17T14:48:41",
          "project": "Pulse",
          "status": "linked",
          "flags": ["display_uses_journal_window"]
        }
        """)

        let items = buildWorkTimelineItems(episodes: [], commitLinks: [link])

        XCTAssertEqual(items.count, 1)
        XCTAssertTrue(items[0].isSyntheticJournalWindow)
        XCTAssertEqual(items[0].id, "journal-window-custom")
    }

    func testWorkTimelineKeepsRealEpisodesAndDoesNotDuplicateSyntheticCommit() throws {
        let realEpisode = debugWorkEpisode(
            id: "work-episode-1",
            startedAt: "2026-05-17T14:10:35",
            endedAt: "2026-05-17T14:24:26"
        )
        let realLink = try decodeCommitEpisodeLink("""
        {
          "id": "commit-link-real",
          "entry_id": "entry-real",
          "commit_subject": "fix(memory): real work episode",
          "episode_id": "work-episode-1",
          "status": "linked"
        }
        """)
        let syntheticLink = try decodeCommitEpisodeLink("""
        {
          "id": "commit-link-synthetic",
          "entry_id": "entry-synthetic",
          "commit_subject": "fix(memory): journal window",
          "episode_id": "journal-file-window-entry-synthetic",
          "episode_started_at": "2026-05-17T14:13:44",
          "episode_ended_at": "2026-05-17T14:48:41",
          "status": "linked",
          "flags": ["display_uses_journal_window"]
        }
        """)

        let items = buildWorkTimelineItems(episodes: [realEpisode], commitLinks: [realLink, syntheticLink])

        XCTAssertEqual(items.count, 2)
        let realItem = try XCTUnwrap(items.first { $0.id == "work-episode-1" })
        let syntheticItem = try XCTUnwrap(items.first { $0.id == "journal-file-window-entry-synthetic" })
        XCTAssertFalse(realItem.isSyntheticJournalWindow)
        XCTAssertTrue(syntheticItem.isSyntheticJournalWindow)
        XCTAssertEqual(realItem.linkedCommits.map(\.id), ["commit-link-real"])
        XCTAssertEqual(syntheticItem.linkedCommits.map(\.id), ["commit-link-synthetic"])
    }

    func testWorkTimelineSortsRealAndSyntheticItemsByStartDescending() throws {
        let morningEpisode = debugWorkEpisode(
            id: "work-episode-morning",
            startedAt: "2026-05-17T13:32:00",
            endedAt: "2026-05-17T13:55:00"
        )
        let syntheticLink = try decodeCommitEpisodeLink("""
        {
          "id": "commit-link-synthetic",
          "entry_id": "entry-synthetic",
          "commit_subject": "fix(memory): journal window",
          "episode_id": "journal-file-window-entry-synthetic",
          "episode_started_at": "2026-05-17T14:13:44",
          "episode_ended_at": "2026-05-17T14:48:41",
          "status": "linked",
          "flags": ["display_uses_journal_window"]
        }
        """)

        let items = buildWorkTimelineItems(episodes: [morningEpisode], commitLinks: [syntheticLink])

        XCTAssertEqual(items.map(\.id), ["journal-file-window-entry-synthetic", "work-episode-morning"])
    }

    private func contextProbeRequest(kind: String, status: String) -> ContextProbeRequestPayload {
        ContextProbeRequestPayload(
            requestId: "\(kind)-\(status)",
            kind: kind,
            reason: "Need context",
            policy: ContextProbePolicyPayload(
                kind: kind,
                consent: "explicit_each_time",
                privacy: "content_sensitive",
                retention: "ephemeral",
                allowRawValue: false,
                allowPersistentStorage: false,
                requiresUserVisibleReason: true,
                maxChars: 2000
            ),
            status: status,
            createdAt: "2026-05-14T10:00:00",
            expiresAt: nil,
            decidedAt: nil,
            executedAt: nil,
            decisionReason: nil,
            metadataKeys: [],
            isTerminal: false
        )
    }

    private func decodeCommitEpisodeLink(_ json: String) throws -> DebugCommitEpisodeLink {
        try JSONDecoder().decode(DebugCommitEpisodeLink.self, from: Data(json.utf8))
    }

    private func debugWorkEpisode(id: String, startedAt: String, endedAt: String) -> DebugWorkEpisode {
        DebugWorkEpisode(
            id: id,
            project: "Pulse",
            probableTask: "coding",
            activityLevel: "editing",
            startedAt: startedAt,
            endedAt: endedAt,
            durationMin: 10,
            evidenceCount: 2,
            confidence: 0.8,
            boundaryReason: "end_of_events",
            uncertaintyFlags: [],
            dominantScope: "memory",
            previousScope: nil,
            nextScope: nil,
            strongEventCount: 2,
            weakEventCount: 0,
            boundaryEventType: nil,
            boundaryEventAt: nil,
            debugReason: nil
        )
    }

    private func contextProbeDetailJSON(
        requestId: String,
        kind: String,
        source: String,
        redactedValue: String,
        charCount: Int
    ) -> String {
        """
        {
          "request": {
            "request_id": "\(requestId)",
            "kind": "\(kind)",
            "reason": "Need context",
            "policy": {
              "kind": "\(kind)",
              "consent": "explicit_each_time",
              "privacy": "content_sensitive",
              "retention": "ephemeral",
              "allow_raw_value": false,
              "allow_persistent_storage": false,
              "requires_user_visible_reason": true,
              "max_chars": 2000
            },
            "status": "executed",
            "created_at": "2026-05-14T10:00:00",
            "expires_at": null,
            "decided_at": "2026-05-14T10:01:00",
            "executed_at": "2026-05-14T10:02:00",
            "decision_reason": "Approved",
            "metadata_keys": [],
            "is_terminal": true
          },
          "debug": {
            "request_id": "\(requestId)",
            "kind": "\(kind)",
            "status": "executed",
            "reason": "Need context",
            "policy": {
              "kind": "\(kind)",
              "consent": "explicit_each_time",
              "privacy": "content_sensitive",
              "retention": "ephemeral",
              "allow_raw_value": false,
              "allow_persistent_storage": false,
              "requires_user_visible_reason": true,
              "max_chars": 2000
            },
            "labels": {
              "kind": "Context",
              "consent": "Explicit",
              "privacy": "Sensitive",
              "retention": "Ephemeral",
              "risk": "Sensitive",
              "risk_accent_hex": "#ff453a"
            },
            "created_at": "2026-05-14T10:00:00",
            "expires_at": null,
            "decided_at": "2026-05-14T10:01:00",
            "executed_at": "2026-05-14T10:02:00",
            "decision_reason": "Approved",
            "metadata_keys": [],
            "is_expired": false,
            "is_terminal": true
          },
          "result": {
            "request_id": "\(requestId)",
            "kind": "\(kind)",
            "captured": true,
            "data": {
              "source": "\(source)",
              "char_count": \(charCount),
              "redacted_value": "\(redactedValue)",
              "redaction_flags": ["token"],
              "original_length": \(charCount),
              "redacted_length": \(redactedValue.count),
              "was_redacted": true
            },
            "privacy": "content_sensitive",
            "retention": "ephemeral",
            "captured_at": "2026-05-14T10:02:00",
            "blocked_reason": null
          }
        }
        """
    }

    private func makeContextProbeNotificationBridge(
        requestId: String,
        kind: String,
        source: String,
        redactedValue: String,
        charCount: Int
    ) -> DaemonBridge {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        let listJSON = contextProbeListJSON(requestId: requestId, kind: kind)
        let detailJSON = contextProbeDetailJSON(
            requestId: requestId,
            kind: kind,
            source: source,
            redactedValue: redactedValue,
            charCount: charCount
        )

        MockURLProtocol.handler = { request in
            let path = try XCTUnwrap(request.url?.path)
            let body: String
            switch path {
            case "/context-probes/requests":
                body = listJSON
            case "/context-probes/requests/\(requestId)":
                body = detailJSON
            default:
                XCTFail("Unexpected path \(path)")
                body = "{}"
            }
            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 200,
                httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!
            return (response, Data(body.utf8))
        }

        return DaemonBridge(base: "http://127.0.0.1:8765", session: session)
    }

    private func makeWorkIntentCandidateBridge(
        record: ((URLRequest) -> Void)? = nil
    ) -> DaemonBridge {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)

        MockURLProtocol.handler = { request in
            record?(request)
            let path = try XCTUnwrap(request.url?.path)
            let method = request.httpMethod ?? "GET"
            let body: String
            switch (method, path) {
            case ("GET", "/work-intent/candidates"):
                body = self.workIntentCandidatesJSON(status: "candidate")
            case ("POST", "/work-intent/candidates/candidate-1/accept"):
                body = self.workIntentCandidateAcceptJSON()
            case ("POST", "/work-intent/candidates/candidate-1/refuse"):
                body = self.workIntentCandidateActionJSON(status: "refused")
            case ("GET", "/work-context"):
                body = self.workContextJSON()
            case ("GET", "/state"):
                body = self.stateWithWorkIntentJSON()
            default:
                XCTFail("Unexpected \(method) \(path)")
                body = "{}"
            }
            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 200,
                httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!
            return (response, Data(body.utf8))
        }

        return DaemonBridge(base: "http://127.0.0.1:8765", session: session)
    }

    private func workIntentCandidatesJSON(status: String) -> String {
        """
        {
          "candidates": [
            \(workIntentCandidateJSON(status: status))
          ],
          "count": 1
        }
        """
    }

    private func workIntentCandidateActionJSON(status: String) -> String {
        """
        {
          "candidate": \(workIntentCandidateJSON(status: status))
        }
        """
    }

    private func workIntentCandidateAcceptJSON() -> String {
        """
        {
          "candidate": \(workIntentCandidateJSON(status: "accepted")),
          "work_intent": \(workIntentJSON())
        }
        """
    }

    private func workIntentCandidateJSON(status: String) -> String {
        let isActive = status == "candidate" ? "true" : "false"
        return """
        {
          "candidate_id": "candidate-1",
          "summary": "Réduire les coûts cachés du modèle local",
          "source": "manual_context_note",
          "confidence": 0.9,
          "project": "Pulse",
          "created_at": "2026-05-15T10:00:00",
          "expires_at": "2026-05-15T12:00:00",
          "evidence_refs": ["context_probe:manual-1"],
          "status": "\(status)",
          "is_active": \(isActive)
        }
        """
    }

    private func workIntentJSON() -> String {
        """
        {
          "summary": "Réduire les coûts cachés du modèle local",
          "source": "manual_context_note",
          "confidence": 0.9,
          "project": "Pulse",
          "created_at": "2026-05-15T10:00:00",
          "expires_at": "2026-05-15T12:00:00",
          "evidence_refs": ["context_probe:manual-1"]
        }
        """
    }

    private func workContextJSON() -> String {
        """
        {
          "card": {
            "project": "Pulse",
            "project_hint": null,
            "project_hint_confidence": 0.0,
            "project_hint_source": null,
            "activity_level": "editing",
            "probable_task": "coding",
            "confidence": 0.8,
            "evidence": ["active_project"],
            "missing_context": [],
            "safe_next_probes": []
          }
        }
        """
    }

    private func stateWithWorkIntentJSON() -> String {
        """
        {
          "active_app": "Xcode",
          "active_project": "Pulse",
          "session_duration_min": 12,
          "present": {
            "session_status": "active",
            "awake": true,
            "locked": false,
            "active_file": null,
            "active_project": "Pulse",
            "probable_task": "coding",
            "activity_level": "editing",
            "focus_level": "normal",
            "friction_score": 0.1,
            "clipboard_context": null,
            "session_duration_min": 12,
            "work_intent": \(workIntentJSON()),
            "updated_at": "2026-05-15T10:00:00"
          }
        }
        """
    }

    private func contextProbeListJSON(requestId: String, kind: String) -> String {
        """
        {
          "requests": [
            {
              "request_id": "\(requestId)",
              "kind": "\(kind)",
              "reason": "Need context",
              "policy": {
                "kind": "\(kind)",
                "consent": "explicit_each_time",
                "privacy": "content_sensitive",
                "retention": "ephemeral",
                "allow_raw_value": false,
                "allow_persistent_storage": false,
                "requires_user_visible_reason": true,
                "max_chars": 2000
              },
              "status": "executed",
              "created_at": "2026-05-14T10:00:00",
              "expires_at": null,
              "decided_at": "2026-05-14T10:01:00",
              "executed_at": "2026-05-14T10:02:00",
              "decision_reason": "Approved",
              "metadata_keys": [],
              "is_terminal": true
            }
          ],
          "debug": [],
          "count": 1
        }
        """
    }

    private func makeClipboardChoiceBridge(
        record: ((URLRequest) -> Void)? = nil
    ) -> DaemonBridge {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        let createJSON = contextProbeActionJSON(
            requestId: "clipboard-created",
            kind: "clipboard_sample",
            status: "pending"
        )
        let approveJSON = contextProbeActionJSON(
            requestId: "clipboard-created",
            kind: "clipboard_sample",
            status: "approved"
        )
        let refuseJSON = contextProbeActionJSON(
            requestId: "focused_element_text-pending",
            kind: "focused_element_text",
            status: "refused"
        )

        MockURLProtocol.handler = { request in
            record?(request)
            let path = try XCTUnwrap(request.url?.path)
            let method = request.httpMethod ?? "GET"
            let body: String
            switch (method, path) {
            case ("POST", "/context-probes/requests"):
                body = createJSON
            case ("POST", "/context-probes/requests/clipboard-created/approve"):
                body = approveJSON
            case ("POST", "/context-probes/requests/focused_element_text-pending/refuse"):
                body = refuseJSON
            default:
                XCTFail("Unexpected \(method) \(path)")
                body = "{}"
            }
            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 200,
                httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!
            return (response, Data(body.utf8))
        }

        return DaemonBridge(base: "http://127.0.0.1:8765", session: session)
    }

    private func makeManualNoteSubmitBridge(
        record: ((URLRequest) -> Void)? = nil
    ) -> DaemonBridge {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        let createJSON = contextProbeActionJSON(
            requestId: "manual-created",
            kind: "manual_context_note",
            status: "pending"
        )
        let approveJSON = contextProbeActionJSON(
            requestId: "manual-created",
            kind: "manual_context_note",
            status: "approved"
        )
        let refuseJSON = contextProbeActionJSON(
            requestId: "focused_element_text-pending",
            kind: "focused_element_text",
            status: "refused"
        )
        let resultJSON = contextProbeDetailJSON(
            requestId: "manual-created",
            kind: "manual_context_note",
            source: "manual_context_note",
            redactedValue: "objectif de travail",
            charCount: 19
        )

        MockURLProtocol.handler = { request in
            record?(request)
            let path = try XCTUnwrap(request.url?.path)
            let method = request.httpMethod ?? "GET"
            let body: String
            switch (method, path) {
            case ("POST", "/context-probes/requests"):
                body = createJSON
            case ("POST", "/context-probes/requests/manual-created/approve"):
                body = approveJSON
            case ("POST", "/context-probes/requests/focused_element_text-pending/refuse"):
                body = refuseJSON
            case ("POST", "/context-probes/requests/manual-created/result"):
                body = resultJSON
            default:
                XCTFail("Unexpected \(method) \(path)")
                body = "{}"
            }
            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 200,
                httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!
            return (response, Data(body.utf8))
        }

        return DaemonBridge(base: "http://127.0.0.1:8765", session: session)
    }

    private func makeClipboardCancelBridge(
        abortStatusCode: Int = 200,
        record: @escaping (String, String) -> Void
    ) -> DaemonBridge {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        let createJSON = contextProbeActionJSON(
            requestId: "clipboard-created",
            kind: "clipboard_sample",
            status: "pending"
        )
        let approveJSON = contextProbeActionJSON(
            requestId: "clipboard-created",
            kind: "clipboard_sample",
            status: "approved"
        )
        let refuseOriginalJSON = contextProbeActionJSON(
            requestId: "focused_element_text-pending",
            kind: "focused_element_text",
            status: "refused"
        )
        let abortClipboardJSON = contextProbeActionJSON(
            requestId: "clipboard-created",
            kind: "clipboard_sample",
            status: "aborted"
        )

        MockURLProtocol.handler = { request in
            let path = try XCTUnwrap(request.url?.path)
            let method = request.httpMethod ?? "GET"
            record(method, path)
            let body: String
            let statusCode: Int
            switch (method, path) {
            case ("POST", "/context-probes/requests"):
                body = createJSON
                statusCode = 200
            case ("POST", "/context-probes/requests/clipboard-created/approve"):
                body = approveJSON
                statusCode = 200
            case ("POST", "/context-probes/requests/focused_element_text-pending/refuse"):
                body = refuseOriginalJSON
                statusCode = 200
            case ("POST", "/context-probes/requests/clipboard-created/abort"):
                body = abortClipboardJSON
                statusCode = abortStatusCode
            default:
                XCTFail("Unexpected \(method) \(path)")
                body = "{}"
                statusCode = 404
            }
            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: statusCode,
                httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!
            return (response, Data(body.utf8))
        }

        return DaemonBridge(base: "http://127.0.0.1:8765", session: session)
    }

    private func makePendingContextProbeRefuseBridge(
        record: @escaping (String, String) -> Void
    ) -> DaemonBridge {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        let refuseJSON = contextProbeActionJSON(
            requestId: "focused_element_text-pending",
            kind: "focused_element_text",
            status: "refused"
        )

        MockURLProtocol.handler = { request in
            let path = try XCTUnwrap(request.url?.path)
            let method = request.httpMethod ?? "GET"
            record(method, path)
            XCTAssertEqual(method, "POST")
            XCTAssertEqual(path, "/context-probes/requests/focused_element_text-pending/refuse")
            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 200,
                httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!
            return (response, Data(refuseJSON.utf8))
        }

        return DaemonBridge(base: "http://127.0.0.1:8765", session: session)
    }

    private func makeSubmitContextProbeResultBridge(
        requestId: String,
        kind: String,
        source: String,
        record: ((String, String) -> Void)? = nil
    ) -> DaemonBridge {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        let responseJSON = contextProbeDetailJSON(
            requestId: requestId,
            kind: kind,
            source: source,
            redactedValue: "fresh context",
            charCount: 13
        )

        MockURLProtocol.handler = { request in
            let method = request.httpMethod ?? "GET"
            let path = try XCTUnwrap(request.url?.path)
            record?(method, path)
            XCTAssertEqual(method, "POST")
            XCTAssertEqual(path, "/context-probes/requests/\(requestId)/result")
            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 200,
                httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!
            return (response, Data(responseJSON.utf8))
        }

        return DaemonBridge(base: "http://127.0.0.1:8765", session: session)
    }

    private func contextProbeActionJSON(requestId: String, kind: String, status: String) -> String {
        """
        {
          "request": {
            "request_id": "\(requestId)",
            "kind": "\(kind)",
            "reason": "Need context",
            "policy": {
              "kind": "\(kind)",
              "consent": "explicit_each_time",
              "privacy": "content_sensitive",
              "retention": "ephemeral",
              "allow_raw_value": false,
              "allow_persistent_storage": false,
              "requires_user_visible_reason": true,
              "max_chars": 4000
            },
            "status": "\(status)",
            "created_at": "2026-05-14T10:00:00",
            "expires_at": null,
            "decided_at": "2026-05-14T10:01:00",
            "executed_at": null,
            "decision_reason": "Approved",
            "metadata_keys": [],
            "is_terminal": false
          },
          "debug": {
            "request_id": "\(requestId)",
            "kind": "\(kind)",
            "status": "\(status)",
            "reason": "Need context",
            "policy": {
              "kind": "\(kind)",
              "consent": "explicit_each_time",
              "privacy": "content_sensitive",
              "retention": "ephemeral",
              "allow_raw_value": false,
              "allow_persistent_storage": false,
              "requires_user_visible_reason": true,
              "max_chars": 4000
            },
            "labels": {
              "kind": "Context",
              "consent": "Explicit",
              "privacy": "Sensitive",
              "retention": "Ephemeral",
              "risk": "Sensitive",
              "risk_accent_hex": "#ff453a"
            },
            "created_at": "2026-05-14T10:00:00",
            "expires_at": null,
            "decided_at": "2026-05-14T10:01:00",
            "executed_at": null,
            "decision_reason": "Approved",
            "metadata_keys": [],
            "is_expired": false,
            "is_terminal": false
          }
        }
        """
    }

    private static func jsonBody(from request: URLRequest) -> [String: Any] {
        let data = request.httpBody ?? data(from: request.httpBodyStream)
        guard let data,
              let body = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return [:]
        }
        return body
    }

    private static func data(from stream: InputStream?) -> Data? {
        guard let stream else { return nil }
        stream.open()
        defer { stream.close() }
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 1024)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            if count < 0 { return nil }
            if count == 0 { break }
            data.append(buffer, count: count)
        }
        return data
    }
}
