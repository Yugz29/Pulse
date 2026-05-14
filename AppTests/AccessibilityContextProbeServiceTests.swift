import XCTest
@testable import App

final class AccessibilityContextProbeServiceTests: XCTestCase {
    func testOneShotClipboardIgnoresStaleClipboard() {
        let service = OneShotClipboardContextService()
        let now = Date()
        service.arm(baselineChangeCount: 10, now: now, ttl: 60)

        let capture = service.captureIfChanged(
            changeCount: 10,
            text: "old text",
            now: now.addingTimeInterval(1)
        )

        XCTAssertNil(capture)
        XCTAssertTrue(service.isArmed)
    }

    func testOneShotClipboardCapturesOnlyAfterChangeCountAdvances() {
        let service = OneShotClipboardContextService()
        let now = Date()
        service.arm(baselineChangeCount: 10, now: now, ttl: 60)

        let capture = service.captureIfChanged(
            changeCount: 11,
            text: "fresh context",
            now: now.addingTimeInterval(1)
        )

        XCTAssertEqual(capture?.changeCount, 11)
        XCTAssertEqual(capture?.capture.source, "next_clipboard_text")
        XCTAssertEqual(capture?.capture.text, "fresh context")
        XCTAssertFalse(service.isArmed)
    }

    func testOneShotClipboardIgnoresNonTextChangeAndStaysArmed() {
        let service = OneShotClipboardContextService()
        let now = Date()
        service.arm(baselineChangeCount: 10, now: now, ttl: 60)

        let first = service.captureIfChanged(
            changeCount: 11,
            text: nil,
            now: now.addingTimeInterval(1)
        )
        let second = service.captureIfChanged(
            changeCount: 12,
            text: "text after image",
            now: now.addingTimeInterval(2)
        )

        XCTAssertNil(first)
        XCTAssertEqual(second?.capture.text, "text after image")
        XCTAssertFalse(service.isArmed)
    }

    func testOneShotClipboardTimeoutDisarms() {
        let service = OneShotClipboardContextService()
        let now = Date()
        service.arm(baselineChangeCount: 10, now: now, ttl: 1)

        let capture = service.captureIfChanged(
            changeCount: 11,
            text: "late context",
            now: now.addingTimeInterval(2)
        )

        XCTAssertNil(capture)
        XCTAssertFalse(service.isArmed)
    }

    func testManualContextNoteTruncatesLocally() {
        let raw = String(repeating: "n", count: 2_050)

        let capture = ContextTextProbeCapture.manualContextNote(raw)

        XCTAssertEqual(capture.source, "manual_context_note")
        XCTAssertEqual(capture.charCount, 2_050)
        XCTAssertTrue(capture.truncated)
        XCTAssertEqual(capture.text.count, 2_000)
    }

    func testAllowedRolesStayNarrow() {
        XCTAssertTrue(AccessibilityContextProbeService.isAllowedRole("AXTextArea"))
        XCTAssertTrue(AccessibilityContextProbeService.isAllowedRole("AXTextField"))
        XCTAssertTrue(AccessibilityContextProbeService.isAllowedRole("AXComboBox"))
        XCTAssertFalse(AccessibilityContextProbeService.isAllowedRole("AXSecureTextField"))
        XCTAssertFalse(AccessibilityContextProbeService.isAllowedRole("AXWebArea"))
        XCTAssertFalse(AccessibilityContextProbeService.isAllowedRole("AXGroup"))
    }

    func testCaptureTruncatesLocallyAndKeepsOriginalLength() {
        let raw = String(repeating: "x", count: 2_050)

        let capture = AccessibilityContextProbeService.capture(
            appName: "Code",
            bundleId: "com.example.code",
            role: "AXTextArea",
            source: "focused_element_text",
            rawText: raw
        )

        XCTAssertEqual(capture.charCount, 2_050)
        XCTAssertTrue(capture.truncated)
        XCTAssertEqual(capture.text.count, 2_000)
        XCTAssertEqual(capture.source, "focused_element_text")
    }

    func testShortcutHandlerDoesNothingWithoutApprovedFocusedElementRequest() {
        let requests = [
            contextProbeRequest(kind: "focused_element_text", status: "pending"),
            contextProbeRequest(kind: "window_title", status: "approved"),
            contextProbeRequest(kind: "focused_element_text", status: "executed")
        ]

        XCTAssertNil(AccessibilityContextProbeShortcutHandler.approvedFocusedElementTextRequest(from: requests))
    }

    func testShortcutHandlerTargetsOnlyApprovedFocusedElementTextRequests() {
        let selectedText = contextProbeRequest(kind: "selected_text", status: "approved")
        let focusedText = contextProbeRequest(kind: "focused_element_text", status: "approved")

        let request = AccessibilityContextProbeShortcutHandler.approvedFocusedElementTextRequest(
            from: [selectedText, focusedText]
        )

        XCTAssertEqual(request?.requestId, focusedText.requestId)
        XCTAssertEqual(request?.kind, "focused_element_text")
    }

    func testDiagnosticNeverIncludesRawSelectedTextOrValue() {
        let diagnostic = AccessibilityContextProbeService.diagnostic(
            appName: "Code",
            bundleId: "com.microsoft.VSCode",
            focusedRole: "AXTextArea",
            focusedSubrole: nil,
            roleDescription: "text area",
            selectedText: "SECRET_SELECTED_TEXT",
            value: "SECRET_VALUE_TEXT"
        )

        XCTAssertEqual(diagnostic.selectedTextLength, "SECRET_SELECTED_TEXT".count)
        XCTAssertEqual(diagnostic.valueLength, "SECRET_VALUE_TEXT".count)
        XCTAssertFalse(String(describing: diagnostic).contains("SECRET_SELECTED_TEXT"))
        XCTAssertFalse(String(describing: diagnostic).contains("SECRET_VALUE_TEXT"))
    }

    func testDiagnosticReportsSecureFieldRejected() {
        let diagnostic = AccessibilityContextProbeService.diagnostic(
            appName: "App",
            bundleId: "com.example.app",
            focusedRole: "AXSecureTextField",
            focusedSubrole: nil,
            roleDescription: nil,
            selectedText: nil,
            value: "secret"
        )

        XCTAssertTrue(diagnostic.isSecureField)
        XCTAssertEqual(diagnostic.rejectionReason, "secure_field")
    }

    func testDiagnosticReportsWebAreaRejected() {
        let diagnostic = AccessibilityContextProbeService.diagnostic(
            appName: "App",
            bundleId: "com.example.app",
            focusedRole: "AXWebArea",
            focusedSubrole: nil,
            roleDescription: nil,
            selectedText: nil,
            value: nil
        )

        XCTAssertTrue(diagnostic.isWebArea)
        XCTAssertEqual(diagnostic.rejectionReason, "web_area")
    }

    func testDiagnosticReportsAllowedRole() {
        let diagnostic = AccessibilityContextProbeService.diagnostic(
            appName: "App",
            bundleId: "com.example.app",
            focusedRole: "AXTextField",
            focusedSubrole: nil,
            roleDescription: nil,
            selectedText: nil,
            value: "hello"
        )

        XCTAssertTrue(diagnostic.isAllowed)
        XCTAssertEqual(diagnostic.rejectionReason, "allowed")
        XCTAssertEqual(diagnostic.valueLength, 5)
    }

    func testDiagnosticReportsUnknownRoleNotAllowed() {
        let diagnostic = AccessibilityContextProbeService.diagnostic(
            appName: "App",
            bundleId: "com.example.app",
            focusedRole: "AXGroup",
            focusedSubrole: nil,
            roleDescription: nil,
            selectedText: nil,
            value: nil
        )

        XCTAssertFalse(diagnostic.isAllowed)
        XCTAssertEqual(diagnostic.rejectionReason, "role_not_allowed")
    }

    func testDiagnosticMissingFocusedElementKeepsWindowMetadata() {
        let diagnostic = AccessibilityContextProbeService.diagnostic(
            appName: "VS Code",
            bundleId: "com.microsoft.VSCode",
            pid: 42,
            axTrusted: true,
            focusedElementStatus: "missing:-25205",
            focusedRole: nil,
            focusedSubrole: nil,
            selectedText: nil,
            value: nil,
            focusedWindowStatus: "available",
            focusedWindowRole: "AXWindow",
            focusedWindowTitle: "Secret project title"
        )

        XCTAssertEqual(diagnostic.pid, 42)
        XCTAssertEqual(diagnostic.focusedElementStatus, "missing:-25205")
        XCTAssertEqual(diagnostic.focusedWindowStatus, "available")
        XCTAssertEqual(diagnostic.focusedWindowRole, "AXWindow")
        XCTAssertTrue(diagnostic.focusedWindowTitleAvailable)
        XCTAssertFalse(String(describing: diagnostic).contains("Secret project title"))
    }

    func testDiagnosticStoreUpdatesLatestDiagnosticWithoutDaemon() {
        let store = AccessibilityContextProbeDiagnosticStore()
        let diagnostic = AccessibilityContextProbeService.diagnostic(
            appName: "Codex",
            bundleId: "com.openai.codex",
            pid: 123,
            focusedRole: "AXTextArea",
            focusedSubrole: nil,
            selectedText: nil,
            value: "hello"
        )

        store.record(diagnostic)

        XCTAssertEqual(store.latestDiagnostic, diagnostic)
        XCTAssertEqual(store.latestDiagnostic?.appName, "Codex")
    }

    func testTreeDiagnosticNeverIncludesRawValueSelectedOrTitleStrings() {
        let tree = AccessibilityContextProbeService.inspectAccessibilityTree(
            root: AccessibilityTreeDiagnosticNode(
                role: "AXWindow",
                children: [
                    AccessibilityTreeDiagnosticNode(
                        role: "AXTextArea",
                        children: []
                    )
                ]
            )
        )

        XCTAssertEqual(tree.firstCandidatePathRoles, ["AXWindow", "AXTextArea"])
        XCTAssertFalse(String(describing: tree).contains("SECRET_VALUE"))
        XCTAssertFalse(String(describing: tree).contains("SECRET_SELECTED"))
        XCTAssertFalse(String(describing: tree).contains("SECRET_TITLE"))
    }

    func testTreeDiagnosticStopsAtDepthLimit() {
        let tree = AccessibilityContextProbeService.inspectAccessibilityTree(
            root: AccessibilityTreeDiagnosticNode(
                role: "AXWindow",
                children: [
                    AccessibilityTreeDiagnosticNode(
                        role: "AXGroup",
                        children: [
                            AccessibilityTreeDiagnosticNode(
                                role: "AXGroup",
                                children: [
                                    AccessibilityTreeDiagnosticNode(role: "AXTextArea", children: [])
                                ]
                            )
                        ]
                    )
                ]
            ),
            depthLimit: 1,
            nodeLimit: 20
        )

        XCTAssertTrue(tree.treeTruncated)
        XCTAssertEqual(tree.textAreaCount, 0)
    }

    func testTreeDiagnosticStopsAtNodeLimitAndMarksTruncated() {
        let children = (0..<10).map { _ in
            AccessibilityTreeDiagnosticNode(role: "AXGroup", children: [])
        }
        let tree = AccessibilityContextProbeService.inspectAccessibilityTree(
            root: AccessibilityTreeDiagnosticNode(role: "AXWindow", children: children),
            depthLimit: 4,
            nodeLimit: 5
        )

        XCTAssertTrue(tree.treeTruncated)
        XCTAssertEqual(tree.totalNodesSeen, 5)
    }

    func testTreeDiagnosticAggregatesRoleCountsAndCandidatePath() {
        let tree = AccessibilityContextProbeService.inspectAccessibilityTree(
            root: AccessibilityTreeDiagnosticNode(
                role: "AXWindow",
                children: [
                    AccessibilityTreeDiagnosticNode(role: "AXTextField", children: []),
                    AccessibilityTreeDiagnosticNode(role: "AXComboBox", children: []),
                    AccessibilityTreeDiagnosticNode(role: "AXWebArea", children: []),
                    AccessibilityTreeDiagnosticNode(role: nil, children: [])
                ]
            )
        )

        XCTAssertEqual(tree.rolesCount["AXWindow"], 1)
        XCTAssertEqual(tree.rolesCount["AXTextField"], 1)
        XCTAssertEqual(tree.rolesCount["AXComboBox"], 1)
        XCTAssertEqual(tree.rolesCount["AXWebArea"], 1)
        XCTAssertEqual(tree.rolesCount["unknown"], 1)
        XCTAssertEqual(tree.editableCandidateCount, 2)
        XCTAssertEqual(tree.webAreaCount, 1)
        XCTAssertEqual(tree.unknownRoleCount, 1)
        XCTAssertEqual(tree.firstCandidatePathRoles, ["AXWindow", "AXTextField"])
    }

    func testTreeDiagnosticCountsSecureFieldsButDoesNotTreatThemAsReadable() {
        let tree = AccessibilityContextProbeService.inspectAccessibilityTree(
            root: AccessibilityTreeDiagnosticNode(
                role: "AXWindow",
                children: [
                    AccessibilityTreeDiagnosticNode(role: "AXSecureTextField", children: [])
                ]
            )
        )

        XCTAssertEqual(tree.secureTextFieldCount, 1)
        XCTAssertEqual(tree.editableCandidateCount, 0)
        XCTAssertEqual(tree.candidateRolesFound, ["AXSecureTextField"])
    }

    private func contextProbeRequest(
        kind: String,
        status: String,
        isTerminal: Bool = false
    ) -> ContextProbeRequestPayload {
        ContextProbeRequestPayload(
            requestId: "\(kind)-\(status)",
            kind: kind,
            reason: "Test",
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
            decidedAt: status == "approved" ? "2026-05-14T10:01:00" : nil,
            executedAt: status == "executed" ? "2026-05-14T10:02:00" : nil,
            decisionReason: nil,
            metadataKeys: [],
            isTerminal: isTerminal
        )
    }
}
