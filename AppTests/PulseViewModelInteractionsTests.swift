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

    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
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

    func testRefreshStateUsesSessionDurationFromSignalsInsteadOfLegacyTopLevelField() async {
        let json = """
        {
          "active_app": "Xcode",
          "active_project": "Pulse",
          "active_file": "/tmp/runtime_orchestrator.py",
          "session_duration_min": 240,
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
        await waitUntil { vm.sessionDuration == 45 }

        XCTAssertEqual(vm.sessionDuration, 45)
    }

    func testRefreshStateShowsZeroWhenSignalsAreMissingEvenIfLegacyDurationIsHigh() async {
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
        await waitUntil { vm.sessionDuration == 0 }

        XCTAssertEqual(vm.sessionDuration, 0)
    }

    func testRefreshStateKeepsZeroWhenSignalsSessionDurationIsZero() async {
        let json = """
        {
          "active_app": "Xcode",
          "active_project": "Pulse",
          "session_duration_min": 90,
          "signals": {
            "probable_task": "coding",
            "focus_level": "normal",
            "friction_score": 0.2,
            "session_duration_min": 0,
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
            createdAt: "2026-04-15T12:00:00",
            updatedAt: "2026-04-15T12:00:00",
            decidedAt: nil
        )
        let automatic = ProposalRecord(
            id: "proposal-2",
            type: "context_injection",
            title: "Contexte de session prêt à être injecté",
            summary: "Le contexte local est jugé assez riche pour une réponse assistée.",
            rationale: "La session a accumulé assez de contexte local.",
            status: "executed",
            createdAt: "2026-04-15T12:00:00",
            updatedAt: "2026-04-15T12:01:00",
            decidedAt: "2026-04-15T12:01:00"
        )

        XCTAssertEqual(blocking.typeLabel, "Commande risquée")
        XCTAssertEqual(blocking.flowLabel, "validation requise")
        XCTAssertEqual(blocking.statusLabel, "À valider")
        XCTAssertTrue(blocking.detailText?.contains("attend votre choix") == true)

        XCTAssertEqual(automatic.typeLabel, "Contexte assistant")
        XCTAssertEqual(automatic.flowLabel, "application automatique")
        XCTAssertEqual(automatic.statusLabel, "Appliquée")
        XCTAssertTrue(automatic.detailText?.contains("automatiquement") == true)
    }

    func testProposalRecordDetailFallsBackToRationaleWithoutRepeatingTitle() {
        let proposal = ProposalRecord(
            id: "proposal-1",
            type: "context_injection",
            title: "Contexte prêt",
            summary: "Contexte prêt",
            rationale: "Le contexte de session est assez riche pour aider la prochaine réponse.",
            status: "executed",
            createdAt: "2026-04-15T12:00:00",
            updatedAt: "2026-04-15T12:01:00",
            decidedAt: "2026-04-15T12:01:00"
        )

        XCTAssertTrue(proposal.detailText?.contains("Pourquoi :") == true)
        XCTAssertFalse(proposal.detailText?.contains("Contexte prêt Contexte prêt") == true)
    }

    func testSignalsDataExpliqueQuandLaTacheEstAncreeDansLesFichiers() {
        let signals = SignalsData(
            activeProject: "Pulse",
            activeFile: "/tmp/main.py",
            probableTask: "coding",
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
        XCTAssertEqual(signals.taskEvidenceLabel, "ancré dans les fichiers")
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

        XCTAssertEqual(signals.taskEvidenceLabel, "contexte léger")
        XCTAssertEqual(
            signals.taskEvidenceSummary,
            "Le libellé vient surtout de l’app récente (Notes) car l’activité fichiers reste faible."
        )
        XCTAssertNil(signals.fileActivitySummary)
    }

    func testSignalsDataNExposePasOtherCommeLectureUtileQuandUnTypeConcretExiste() {
        let signals = SignalsData(
            activeProject: "Pulse",
            activeFile: "/tmp/main.py",
            probableTask: "coding",
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
}
