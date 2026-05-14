import Foundation

enum AccessibilityContextProbeShortcutHandler {
    static func approvedFocusedElementTextRequest(
        from requests: [ContextProbeRequestPayload]
    ) -> ContextProbeRequestPayload? {
        requests.first { request in
            request.canCaptureFromAccessibility && !request.isTerminal
        }
    }
}

final class AccessibilityContextProbeDiagnosticStore {
    private(set) var latestDiagnostic: AccessibilityTextProbeDiagnostic?

    func record(_ diagnostic: AccessibilityTextProbeDiagnostic) {
        latestDiagnostic = diagnostic
    }
}
