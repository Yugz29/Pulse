import XCTest
@testable import App

@MainActor
final class DaemonControllerTests: XCTestCase {
    private final class RequestPathRecorder: @unchecked Sendable {
        private let lock = NSLock()
        private var paths: [String] = []

        func record(_ request: URLRequest) {
            lock.lock()
            paths.append(request.url?.path ?? "")
            lock.unlock()
        }

        var snapshot: [String] {
            lock.lock()
            let value = paths
            lock.unlock()
            return value
        }
    }

    private func makeSession(handler: @escaping (URLRequest) throws -> (HTTPURLResponse, Data)) -> URLSession {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        MockURLProtocol.handler = handler
        return URLSession(configuration: config)
    }

    private func makeResponse(for request: URLRequest, statusCode: Int = 200) throws -> HTTPURLResponse {
        HTTPURLResponse(
            url: try XCTUnwrap(request.url),
            statusCode: statusCode,
            httpVersion: nil,
            headerFields: ["Content-Type": "application/json"]
        )!
    }

    private func waitUntil(_ condition: @escaping @MainActor () -> Bool, timeout: TimeInterval = 1.0) async {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if condition() { return }
            try? await Task.sleep(nanoseconds: 10_000_000)
        }
    }

    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    func testStopMarksStoppedWhenPingStopsResponding() async {
        let session = makeSession { request in
            if request.url?.path == "/daemon/shutdown" {
                return (try self.makeResponse(for: request), Data("{}".utf8))
            }
            return (try self.makeResponse(for: request, statusCode: 503), Data("{}".utf8))
        }
        let controller = DaemonController(
            session: session,
            launchAgentInstalled: false,
            directStopTimeout: 0.05,
            stopPollIntervalNanoseconds: 1_000_000
        )
        controller.state = .running

        controller.stop()
        await waitUntil { controller.state == .stopped }

        XCTAssertEqual(controller.state, .stopped)
        XCTAssertNil(controller.lastError)
    }

    func testStopKeepsRunningWhenPingStillRespondsAfterTimeout() async {
        let session = makeSession { request in
            (try self.makeResponse(for: request), Data("{}".utf8))
        }
        let controller = DaemonController(
            session: session,
            launchAgentInstalled: false,
            directStopTimeout: 0.02,
            stopPollIntervalNanoseconds: 1_000_000
        )
        controller.state = .running

        controller.stop()
        await waitUntil { controller.lastError != nil }

        XCTAssertEqual(controller.state, .running)
        XCTAssertEqual(controller.lastError, "Daemon still responds on :8765 after stop timeout")
    }

    func testRestartDoesNotStartAgainWhenStopIsNotConfirmed() async {
        let recorder = RequestPathRecorder()
        let session = makeSession { request in
            recorder.record(request)
            return (try self.makeResponse(for: request), Data("{}".utf8))
        }
        let controller = DaemonController(
            session: session,
            launchAgentInstalled: false,
            directRestartStopTimeout: 0.02,
            stopPollIntervalNanoseconds: 1_000_000
        )
        controller.state = .running

        controller.restart()
        await waitUntil { controller.lastError != nil }

        let paths = recorder.snapshot

        XCTAssertEqual(controller.state, .running)
        XCTAssertEqual(controller.lastError, "Daemon still responds on :8765 after stop timeout")
        XCTAssertTrue(paths.contains("/daemon/shutdown"))
        XCTAssertFalse(controller.state == .starting)
    }
}
