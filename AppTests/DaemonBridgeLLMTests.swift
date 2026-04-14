import XCTest
@testable import App

@MainActor
final class DaemonBridgeLLMTests: XCTestCase {
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

    private func collect(stream: AsyncThrowingStream<String, Error>) async throws -> [String] {
        var tokens: [String] = []
        for try await token in stream {
            tokens.append(token)
        }
        return tokens
    }

    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    func testAskStreamNormalResponseKeepsBehavior() async throws {
        let body = """
        data: {"token":"Bonjour ","done":false}

        data: {"token":"monde","done":false}

        data: {"token":"","done":true,"model":"mistral"}

        """
        let bridge = makeBridge(body: body)

        let tokens = try await collect(stream: bridge.askStream("Salut"))

        XCTAssertEqual(tokens, ["Bonjour ", "monde"])
    }

    func testAskStreamInvalidStateThrowsExplicitError() async {
        let body = """
        data: {"state":"invalid","error":"Réponse finale invalide.","code":"invalid_response"}

        """
        let bridge = makeBridge(body: body)

        do {
            _ = try await collect(stream: bridge.askStream("Salut"))
            XCTFail("Une erreur explicite était attendue")
        } catch let error as DaemonError {
            guard case .llm(let message) = error else {
                return XCTFail("DaemonError.llm attendu")
            }
            XCTAssertEqual(message, "Réponse finale invalide.")
        } catch {
            XCTFail("Type d'erreur inattendu: \(error)")
        }
    }

    func testAskStreamDegradedAfterTokensDoesNotSilentlySucceed() async {
        let body = """
        data: {"token":"Réponse ","done":false}

        data: {"state":"degraded","error":"Réponse incomplète.","code":"degraded_response"}

        """
        let bridge = makeBridge(body: body)
        var collected: [String] = []

        do {
            for try await token in bridge.askStream("Salut") {
                collected.append(token)
            }
            XCTFail("Une terminaison dégradée était attendue")
        } catch let error as DaemonError {
            XCTAssertEqual(collected, ["Réponse "])
            guard case .llm(let message) = error else {
                return XCTFail("DaemonError.llm attendu")
            }
            XCTAssertEqual(message, "Réponse incomplète.")
        } catch {
            XCTFail("Type d'erreur inattendu: \(error)")
        }
    }

    func testAskStreamToolCallIsNotExposedAsVisibleToken() async throws {
        let body = """
        data: {"status":"thinking"}

        data: {"tool_call":"score_project","status":"running"}

        data: {"token":"Réponse finale","done":false}

        data: {"token":"","done":true,"model":"mistral"}

        """
        let bridge = makeBridge(body: body)

        let tokens = try await collect(stream: bridge.askStream("Salut"))

        XCTAssertEqual(tokens, ["Réponse finale"])
    }

    func testAskStreamMultipleToolSignalsDoNotPolluteVisibleResponse() async throws {
        let body = """
        data: {"status":"thinking"}

        data: {"tool_call":"score_project","status":"running"}

        data: {"tool_call":"score_file","status":"running"}

        data: {"token":"Réponse ","done":false}

        data: {"token":"finale","done":false}

        data: {"token":"","done":true,"model":"mistral"}

        """
        let bridge = makeBridge(body: body)

        let tokens = try await collect(stream: bridge.askStream("Salut"))

        XCTAssertEqual(tokens, ["Réponse ", "finale"])
    }
}
