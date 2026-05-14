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

struct AccessibilityTextProbeDiagnostic: Equatable {
    let appName: String
    let bundleId: String
    let pid: Int32
    let axTrusted: Bool
    let focusedElementStatus: String
    let focusedRole: String?
    let focusedSubrole: String?
    let focusedRoleDescription: String?
    let canReadSelectedText: Bool
    let selectedTextLength: Int?
    let canReadValue: Bool
    let valueLength: Int?
    let focusedWindowStatus: String
    let focusedWindowRole: String?
    let focusedWindowTitleAvailable: Bool
    let rejectionReason: String
    let isSecureField: Bool
    let isWebArea: Bool
    let treeSummary: AccessibilityTreeDiagnosticSummary?

    var isAllowed: Bool {
        rejectionReason == "allowed"
    }

    var roleDescription: String? {
        focusedRoleDescription
    }
}

struct AccessibilityTreeDiagnosticSummary: Equatable {
    let treeInspected: Bool
    let treeDepthLimit: Int
    let treeNodeLimit: Int
    let treeTruncated: Bool
    let totalNodesSeen: Int
    let rolesCount: [String: Int]
    let editableCandidateCount: Int
    let textAreaCount: Int
    let textFieldCount: Int
    let comboBoxCount: Int
    let searchFieldCount: Int
    let webAreaCount: Int
    let secureTextFieldCount: Int
    let unknownRoleCount: Int
    let candidateRolesFound: [String]
    let firstCandidatePathRoles: [String]
    let rejectionSummary: String?
}

struct AccessibilityTreeDiagnosticNode {
    let role: String?
    let children: [AccessibilityTreeDiagnosticNode]
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
    static let treeDepthLimit = 4
    static let treeNodeLimit = 200
    static let allowedRoles: Set<String> = ["AXTextArea", "AXTextField", "AXComboBox"]
    static let forbiddenRoles: Set<String> = ["AXSecureTextField", "AXWebArea"]
    static let diagnosticCandidateRoles: Set<String> = [
        "AXTextArea",
        "AXTextField",
        "AXComboBox",
        "AXSearchField",
        "AXSecureTextField",
        "AXWebArea"
    ]

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

    func diagnoseFocusedElement() throws -> AccessibilityTextProbeDiagnostic {
        guard let app = NSWorkspace.shared.frontmostApplication else {
            throw AccessibilityContextProbeError.noFrontmostApplication
        }
        guard let appName = app.localizedName,
              let bundleId = app.bundleIdentifier else {
            throw AccessibilityContextProbeError.missingApplicationIdentity
        }

        let axTrusted = AXIsProcessTrusted()
        let appElement = AXUIElementCreateApplication(app.processIdentifier)
        let focusedElementResult = axElementAttributeResult(appElement, kAXFocusedUIElementAttribute as CFString)
        let focusedWindowResult = axElementAttributeResult(appElement, kAXFocusedWindowAttribute as CFString)
        let focusedWindow = focusedWindowResult.element
        let focusedElementAttributes = focusedElementResult.element.map { axAttributeNames($0) } ?? []
        let treeSummary = focusedWindow.map { inspectAccessibilityTree(from: $0) }

        return Self.diagnostic(
            appName: appName,
            bundleId: bundleId,
            pid: app.processIdentifier,
            axTrusted: axTrusted,
            focusedElementStatus: focusedElementResult.status,
            focusedRole: focusedElementResult.element.flatMap { axStringAttribute($0, kAXRoleAttribute as CFString) },
            focusedSubrole: focusedElementResult.element.flatMap { axStringAttribute($0, kAXSubroleAttribute as CFString) },
            focusedRoleDescription: focusedElementResult.element.flatMap { axStringAttribute($0, kAXRoleDescriptionAttribute as CFString) },
            selectedText: nil,
            value: nil,
            canReadSelectedText: focusedElementAttributes.contains(kAXSelectedTextAttribute as String),
            selectedTextLength: nil,
            canReadValue: focusedElementAttributes.contains(kAXValueAttribute as String),
            valueLength: nil,
            focusedWindowStatus: focusedWindowResult.status,
            focusedWindowRole: focusedWindow.flatMap { axStringAttribute($0, kAXRoleAttribute as CFString) },
            focusedWindowTitleAvailable: focusedWindow.map { axAttributeNames($0).contains(kAXTitleAttribute as String) } ?? false,
            treeSummary: treeSummary
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

    static func diagnostic(
        appName: String,
        bundleId: String,
        pid: Int32 = 0,
        axTrusted: Bool = true,
        focusedElementStatus: String = "available",
        focusedRole: String?,
        focusedSubrole: String?,
        roleDescription: String? = nil,
        focusedRoleDescription: String? = nil,
        selectedText: String?,
        value: String?,
        canReadSelectedText: Bool? = nil,
        selectedTextLength explicitSelectedTextLength: Int? = nil,
        canReadValue: Bool? = nil,
        valueLength explicitValueLength: Int? = nil,
        focusedWindowStatus: String = "not_checked",
        focusedWindowRole: String? = nil,
        focusedWindowTitle: String? = nil,
        focusedWindowTitleAvailable explicitFocusedWindowTitleAvailable: Bool? = nil,
        treeSummary: AccessibilityTreeDiagnosticSummary? = nil
    ) -> AccessibilityTextProbeDiagnostic {
        let role = focusedRole?.trimmingCharacters(in: .whitespacesAndNewlines)
        let normalizedRole = role?.isEmpty == true ? nil : role
        let isSecureField = normalizedRole == "AXSecureTextField"
        let isWebArea = normalizedRole == "AXWebArea"
        let rejectionReason: String
        if isSecureField {
            rejectionReason = "secure_field"
        } else if isWebArea {
            rejectionReason = "web_area"
        } else if let normalizedRole, isAllowedRole(normalizedRole) {
            rejectionReason = "allowed"
        } else {
            rejectionReason = "role_not_allowed"
        }

        let selectedTextLength = explicitSelectedTextLength ?? textLength(selectedText)
        let valueLength = explicitValueLength ?? textLength(value)
        return AccessibilityTextProbeDiagnostic(
            appName: appName,
            bundleId: bundleId,
            pid: pid,
            axTrusted: axTrusted,
            focusedElementStatus: focusedElementStatus,
            focusedRole: normalizedRole,
            focusedSubrole: normalizedString(focusedSubrole),
            focusedRoleDescription: normalizedString(focusedRoleDescription ?? roleDescription),
            canReadSelectedText: canReadSelectedText ?? (selectedTextLength != nil),
            selectedTextLength: selectedTextLength,
            canReadValue: canReadValue ?? (valueLength != nil),
            valueLength: valueLength,
            focusedWindowStatus: focusedWindowStatus,
            focusedWindowRole: normalizedString(focusedWindowRole),
            focusedWindowTitleAvailable: explicitFocusedWindowTitleAvailable ?? (normalizedString(focusedWindowTitle) != nil),
            rejectionReason: rejectionReason,
            isSecureField: isSecureField,
            isWebArea: isWebArea,
            treeSummary: treeSummary
        )
    }

    func inspectAccessibilityTree(from root: AXUIElement) -> AccessibilityTreeDiagnosticSummary {
        Self.inspectAccessibilityTree(
            roleOf: { element in axStringAttribute(element, kAXRoleAttribute as CFString) },
            childrenOf: { element in axChildrenAttribute(element) },
            root: root,
            depthLimit: Self.treeDepthLimit,
            nodeLimit: Self.treeNodeLimit
        )
    }

    static func inspectAccessibilityTree(
        root: AccessibilityTreeDiagnosticNode,
        depthLimit: Int = treeDepthLimit,
        nodeLimit: Int = treeNodeLimit
    ) -> AccessibilityTreeDiagnosticSummary {
        inspectAccessibilityTree(
            roleOf: { $0.role },
            childrenOf: { $0.children },
            root: root,
            depthLimit: depthLimit,
            nodeLimit: nodeLimit
        )
    }

    private static func inspectAccessibilityTree<Node>(
        roleOf: (Node) -> String?,
        childrenOf: (Node) -> [Node],
        root: Node,
        depthLimit: Int,
        nodeLimit: Int
    ) -> AccessibilityTreeDiagnosticSummary {
        var rolesCount: [String: Int] = [:]
        var candidateRolesFound: [String] = []
        var firstCandidatePathRoles: [String] = []
        var totalNodesSeen = 0
        var treeTruncated = false

        func visit(_ node: Node, depth: Int, path: [String]) {
            guard totalNodesSeen < nodeLimit else {
                treeTruncated = true
                return
            }
            totalNodesSeen += 1

            let role = normalizedString(roleOf(node)) ?? "unknown"
            rolesCount[role, default: 0] += 1
            let nextPath = path + [role]
            if diagnosticCandidateRoles.contains(role) {
                if !candidateRolesFound.contains(role) {
                    candidateRolesFound.append(role)
                }
                if firstCandidatePathRoles.isEmpty {
                    firstCandidatePathRoles = nextPath
                }
            }

            guard depth < depthLimit else {
                if !childrenOf(node).isEmpty {
                    treeTruncated = true
                }
                return
            }
            for child in childrenOf(node) {
                visit(child, depth: depth + 1, path: nextPath)
                if totalNodesSeen >= nodeLimit {
                    treeTruncated = true
                    break
                }
            }
        }

        visit(root, depth: 0, path: [])

        let textAreaCount = rolesCount["AXTextArea", default: 0]
        let textFieldCount = rolesCount["AXTextField", default: 0]
        let comboBoxCount = rolesCount["AXComboBox", default: 0]
        let searchFieldCount = rolesCount["AXSearchField", default: 0]
        let secureTextFieldCount = rolesCount["AXSecureTextField", default: 0]
        let webAreaCount = rolesCount["AXWebArea", default: 0]
        let editableCandidateCount = textAreaCount + textFieldCount + comboBoxCount + searchFieldCount
        let knownRoles = Set(rolesCount.keys)
        let unknownRoleCount = rolesCount["unknown", default: 0]
        let rejectionSummary = candidateRolesFound.isEmpty
            ? "no_candidate_roles_found"
            : nil

        return AccessibilityTreeDiagnosticSummary(
            treeInspected: true,
            treeDepthLimit: depthLimit,
            treeNodeLimit: nodeLimit,
            treeTruncated: treeTruncated,
            totalNodesSeen: totalNodesSeen,
            rolesCount: rolesCount,
            editableCandidateCount: editableCandidateCount,
            textAreaCount: textAreaCount,
            textFieldCount: textFieldCount,
            comboBoxCount: comboBoxCount,
            searchFieldCount: searchFieldCount,
            webAreaCount: webAreaCount,
            secureTextFieldCount: secureTextFieldCount,
            unknownRoleCount: unknownRoleCount + (knownRoles.isEmpty ? 1 : 0),
            candidateRolesFound: candidateRolesFound,
            firstCandidatePathRoles: firstCandidatePathRoles,
            rejectionSummary: rejectionSummary
        )
    }

    private static func textLength(_ value: String?) -> Int? {
        guard let text = normalizedString(value) else { return nil }
        return text.count
    }

    private static func normalizedString(_ value: String?) -> String? {
        guard let value else { return nil }
        let text = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty ? nil : text
    }

    private func axElementAttribute(
        _ element: AXUIElement,
        _ attribute: CFString
    ) -> AXUIElement? {
        axElementAttributeResult(element, attribute).element
    }

    private func axElementAttributeResult(
        _ element: AXUIElement,
        _ attribute: CFString
    ) -> (element: AXUIElement?, status: String) {
        var value: CFTypeRef?
        let result = AXUIElementCopyAttributeValue(element, attribute, &value)
        guard result == .success, let value else {
            return (nil, "missing:\(result.rawValue)")
        }
        guard CFGetTypeID(value) == AXUIElementGetTypeID() else {
            return (nil, "unexpected_type")
        }
        return ((value as! AXUIElement), "available")
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

    private func axAttributeNames(_ element: AXUIElement) -> Set<String> {
        var names: CFArray?
        guard AXUIElementCopyAttributeNames(element, &names) == .success,
              let names else { return [] }
        return Set((names as NSArray).compactMap { $0 as? String })
    }

    private func axChildrenAttribute(_ element: AXUIElement) -> [AXUIElement] {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &value) == .success,
              let children = value as? [AXUIElement] else {
            return []
        }
        return children
    }
}
