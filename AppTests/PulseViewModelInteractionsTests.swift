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
