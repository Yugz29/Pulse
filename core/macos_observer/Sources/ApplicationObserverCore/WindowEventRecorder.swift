import Foundation

/// Un `window_focused` par changement de contexte de fenêtre : deux lectures
/// identiques consécutives (même app, même titre, même document, même URL)
/// ne produisent qu'un événement.
public struct WindowDeduplicator: Sendable {
    private var lastContext: WindowContext?

    public init() {}

    public func isDuplicate(_ context: WindowContext) -> Bool {
        lastContext == context
    }

    public mutating func record(_ context: WindowContext) {
        lastContext = context
    }

    /// Oublie la dernière fenêtre : la prochaine lecture identique est de
    /// nouveau un événement (retour depuis une application ignorée ou sans
    /// fenêtre).
    public mutating func forget() {
        lastContext = nil
    }
}

public struct WindowEventRecorder: Sendable {
    private let builder: CanonicalEventBuilder
    private let enqueue: @Sendable (Data) throws -> Void
    private var deduplicator = WindowDeduplicator()

    public init(
        builder: CanonicalEventBuilder,
        enqueue: @escaping @Sendable (Data) throws -> Void
    ) {
        self.builder = builder
        self.enqueue = enqueue
    }

    @discardableResult
    public mutating func record(_ context: WindowContext) throws -> Bool {
        guard !deduplicator.isDuplicate(context) else {
            return false
        }
        let payload = try builder.build(window: context)
        try enqueue(payload)
        deduplicator.record(context)
        return true
    }

    public mutating func forget() {
        deduplicator.forget()
    }
}
