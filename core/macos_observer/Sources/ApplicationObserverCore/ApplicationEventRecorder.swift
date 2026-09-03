import Foundation

public struct ApplicationEventRecorder: Sendable {
    private let builder: CanonicalEventBuilder
    private let enqueue: @Sendable (Data) throws -> Void
    private var deduplicator = ApplicationDeduplicator()

    public init(
        builder: CanonicalEventBuilder,
        enqueue: @escaping @Sendable (Data) throws -> Void
    ) {
        self.builder = builder
        self.enqueue = enqueue
    }

    @discardableResult
    public mutating func record(_ context: ApplicationContext) throws -> Bool {
        guard !deduplicator.isDuplicate(context) else {
            return false
        }
        let payload = try builder.build(context: context)
        try enqueue(payload)
        deduplicator.record(context)
        return true
    }
}
