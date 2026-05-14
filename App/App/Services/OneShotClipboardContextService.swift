import AppKit
import Foundation

struct ContextTextProbeCapture: Encodable, Equatable {
    let source: String
    let contentKind: String
    let charCount: Int
    let truncated: Bool
    let text: String

    enum CodingKeys: String, CodingKey {
        case source
        case contentKind = "content_kind"
        case charCount = "char_count"
        case truncated
        case text
    }

    static func nextClipboardText(_ text: String) -> ContextTextProbeCapture {
        bounded(source: "next_clipboard_text", contentKind: "text", text: text, maxChars: 4_000)
    }

    static func manualContextNote(_ text: String) -> ContextTextProbeCapture {
        bounded(source: "manual_context_note", contentKind: "text", text: text, maxChars: 2_000)
    }

    private static func bounded(
        source: String,
        contentKind: String,
        text: String,
        maxChars: Int
    ) -> ContextTextProbeCapture {
        let trimmed = String(text.prefix(maxChars))
        return ContextTextProbeCapture(
            source: source,
            contentKind: contentKind,
            charCount: text.count,
            truncated: text.count > maxChars,
            text: trimmed
        )
    }
}

struct OneShotClipboardCapture: Equatable {
    let changeCount: Int
    let capture: ContextTextProbeCapture
}

final class OneShotClipboardContextService {
    private(set) var isArmed = false
    private(set) var baselineChangeCount = 0
    private var expiresAt: Date?

    func arm(
        baselineChangeCount: Int,
        now: Date = Date(),
        ttl: TimeInterval = 3_600
    ) {
        self.baselineChangeCount = baselineChangeCount
        self.expiresAt = now.addingTimeInterval(ttl)
        self.isArmed = true
    }

    func disarm() {
        isArmed = false
        expiresAt = nil
    }

    func captureIfChanged(
        changeCount: Int,
        text: String?,
        now: Date = Date()
    ) -> OneShotClipboardCapture? {
        guard isArmed else { return nil }
        if let expiresAt, now >= expiresAt {
            disarm()
            return nil
        }
        guard changeCount > baselineChangeCount else { return nil }
        guard let text, !text.isEmpty else {
            baselineChangeCount = changeCount
            return nil
        }

        let capture = OneShotClipboardCapture(
            changeCount: changeCount,
            capture: .nextClipboardText(text)
        )
        disarm()
        return capture
    }
}
