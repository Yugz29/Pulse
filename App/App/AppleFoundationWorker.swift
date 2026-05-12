import Foundation

final class AppleFoundationWorker {
    private let bridge: DaemonBridge
    private let service: AppleFoundationService
    private let pollInterval: Duration
    private var task: Task<Void, Never>?

    init(
        bridge: DaemonBridge = DaemonBridge(),
        service: AppleFoundationService = AppleFoundationService(),
        pollInterval: Duration = .seconds(2)
    ) {
        self.bridge = bridge
        self.service = service
        self.pollInterval = pollInterval
    }

    func start() {
        guard task == nil else { return }
        task = Task(priority: .utility) { [bridge, service, pollInterval] in
            while !Task.isCancelled {
                do {
                    if let request = try await bridge.fetchLightweightLLMRequest() {
                        let completion = await service.complete(
                            prompt: request.prompt,
                            maxTokens: request.maxTokens
                        )
                        try await bridge.sendLightweightLLMResult(
                            LightweightLLMResult(
                                id: request.id,
                                status: completion.status,
                                text: completion.text,
                                error: completion.error
                            )
                        )
                    }
                    try await Task.sleep(for: pollInterval)
                } catch is CancellationError {
                    return
                } catch {
                    try? await Task.sleep(for: pollInterval)
                }
            }
        }
    }

    func stop() {
        task?.cancel()
        task = nil
    }

    var isRunning: Bool {
        task != nil && task?.isCancelled == false
    }

    func status() async -> AppleFoundationLocalStatus {
        AppleFoundationLocalStatus(
            available: await service.isAvailable(),
            workerRunning: isRunning
        )
    }
}
