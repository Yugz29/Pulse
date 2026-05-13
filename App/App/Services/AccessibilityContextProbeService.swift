import AppKit
import ApplicationServices
import Foundation

struct AccessibilityTextProbeCapture: Encodable {
    let appName: String
    let bundleId: String
    let role: String
    let source: String
    let charCount: Int
    let truncated: Bool
    let text: String

    enum CodingKeys: String, CodingKey {
        case appName = "app_name"
        case bundleId = "bundle_id"
        case role
        case source
        case charCount = "char_count"
        case truncated
        case text
    }
}

enum AccessibilityContextProbeError: Error {
    case accessibilityUnavailable
    case noFrontmostApplication
    case missingApplicationIdentity
    case missingFocusedElement
    case missingRole
    case forbiddenRole(String)
    case unsupportedRole(String)
    case missingText
}

struct AccessibilityContextProbeService {
    static let maxChars = 2_000
    static let allowedRoles: Set<String> = ["AXTextArea", "AXTextField", "AXComboBox"]
    static let forbiddenRoles: Set<String> = ["AXSecureTextField", "AXWebArea"]

    func captureFocusedText() throws -> AccessibilityTextProbeCapture {
        guard AXIsProcessTrusted() else {
            throw AccessibilityContextProbeError.accessibilityUnavailable
        }
        guard let app = NSWorkspace.shared.frontmostApplication else {
            throw AccessibilityContextProbeError.noFrontmostApplication
        }
        guard let appName = app.localizedName,
              let bundleId = app.bundleIdentifier else {
            throw AccessibilityContextProbeError.missingApplicationIdentity
        }

        let appElement = AXUIElementCreateApplication(app.processIdentifier)
        guard let focused = axElementAttribute(appElement, kAXFocusedUIElementAttribute as CFString) else {
            throw AccessibilityContextProbeError.missingFocusedElement
        }
        guard let role = axStringAttribute(focused, kAXRoleAttribute as CFString) else {
            throw AccessibilityContextProbeError.missingRole
        }
        if Self.forbiddenRoles.contains(role) {
            throw AccessibilityContextProbeError.forbiddenRole(role)
        }
        guard Self.allowedRoles.contains(role) else {
            throw AccessibilityContextProbeError.unsupportedRole(role)
        }

        if let selected = axStringAttribute(focused, kAXSelectedTextAttribute as CFString)?
            .trimmingCharacters(in: .whitespacesAndNewlines),
           !selected.isEmpty {
            return Self.capture(
                appName: appName,
                bundleId: bundleId,
                role: role,
                source: "selected_text",
                rawText: selected
            )
        }

        guard let value = axStringAttribute(focused, kAXValueAttribute as CFString)?
            .trimmingCharacters(in: .whitespacesAndNewlines),
              !value.isEmpty else {
            throw AccessibilityContextProbeError.missingText
        }
        return Self.capture(
            appName: appName,
            bundleId: bundleId,
            role: role,
            source: "focused_element_text",
            rawText: value
        )
    }

    static func capture(
        appName: String,
        bundleId: String,
        role: String,
        source: String,
        rawText: String,
        maxChars: Int = maxChars
    ) -> AccessibilityTextProbeCapture {
        let charCount = rawText.count
        let truncated = charCount > maxChars
        let text = truncated ? String(rawText.prefix(maxChars)) : rawText
        return AccessibilityTextProbeCapture(
            appName: appName,
            bundleId: bundleId,
            role: role,
            source: source,
            charCount: charCount,
            truncated: truncated,
            text: text
        )
    }

    static func isAllowedRole(_ role: String) -> Bool {
        allowedRoles.contains(role) && !forbiddenRoles.contains(role)
    }

    private func axElementAttribute(
        _ element: AXUIElement,
        _ attribute: CFString
    ) -> AXUIElement? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute, &value) == .success,
              let value else { return nil }
        return (value as! AXUIElement)
    }

    private func axStringAttribute(
        _ element: AXUIElement,
        _ attribute: CFString
    ) -> String? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute, &value) == .success else {
            return nil
        }
        return value as? String
    }
}
