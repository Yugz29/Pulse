import XCTest
@testable import App

final class AccessibilityContextProbeServiceTests: XCTestCase {
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
}
