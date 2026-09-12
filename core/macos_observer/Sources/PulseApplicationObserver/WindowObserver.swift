import AppKit
import ApplicationObserverCore
import ApplicationServices
import Foundation

/// Lit la fenêtre au premier plan de l'application active via Accessibility,
/// à chaque activation d'application et à chaque changement de fenêtre ou de
/// titre signalé par l'application. Aucune interrogation périodique : un
/// `AXObserver` est attaché au processus actif et retiré quand l'application
/// change. Les notifications rapprochées (chargement d'une page qui change
/// plusieurs fois de titre) sont regroupées, puis une seule lecture est faite.
///
/// Ce qui est lu : `AXTitle`, `AXDocument` et, pour un navigateur, l'`AXURL`
/// de la zone web. Jamais le contenu de la fenêtre, jamais de capture.
/// Un seul mécanisme pour toutes les applications ; le cas navigateur ajoute
/// la lecture de l'URL et rien d'autre.
///
/// Sans autorisation Accessibilité (Réglages Système › Confidentialité et
/// sécurité › Accessibilité), l'observateur continue de produire
/// `app_activated` et journalise une fois que le contexte de fenêtre est
/// indisponible.
final class WindowObserver: @unchecked Sendable {
    static let coalescingDelay: TimeInterval = 0.35
    private static let messagingTimeout: Float = 1.0
    private static let searchNodeBudget = 600
    private static let searchDepthLimit = 12
    private static let browserBundleIDs: Set<String> = [
        "com.apple.Safari",
        "com.apple.SafariTechnologyPreview",
        "com.google.Chrome",
        "com.google.Chrome.beta",
        "com.google.Chrome.canary",
        "org.chromium.Chromium",
        "com.brave.Browser",
        "com.microsoft.edgemac",
        "com.vivaldi.Vivaldi",
        "com.operasoftware.Opera",
        "company.thebrowser.Browser",
        "company.thebrowser.dia",
        "org.mozilla.firefox",
    ]
    // Sous-arbres qui ne contiennent jamais la zone web : on ne les parcourt
    // pas, le budget de nœuds reste pour les groupes et zones de défilement.
    private static let opaqueRoles: Set<String> = [
        "AXToolbar", "AXMenuBar", "AXMenu", "AXButton", "AXStaticText",
        "AXTextField", "AXImage", "AXPopUpButton", "AXCheckBox", "AXRadioButton",
        "AXSlider", "AXLink", "AXHeading", "AXList", "AXTable", "AXOutline",
    ]
    private static let observedNotifications: [String] = [
        kAXFocusedWindowChangedNotification,
        kAXMainWindowChangedNotification,
        kAXTitleChangedNotification,
    ]

    private var recorder: WindowEventRecorder
    private let ignoredApplications: IgnoredApplications
    private var axObserver: AXObserver?
    private var applicationElement: AXUIElement?
    private var observedApplication: ApplicationContext?
    private var observedProcessID: pid_t = 0
    private var pendingRead: DispatchWorkItem?
    private var accessibilityTrusted = false
    private var accessibilityWarned = false

    init(repositoryRoot: URL, ignoredApplicationsURL: URL) throws {
        let bridge = OutboxBridge(repositoryRoot: repositoryRoot)
        self.recorder = try WindowEventRecorder(
            builder: CanonicalEventBuilder(instanceID: bridge.instanceID()),
            enqueue: bridge.enqueue
        )
        self.ignoredApplications = IgnoredApplications.load(from: ignoredApplicationsURL)
    }

    func start() {
        _ = accessibilityAvailable()
    }

    func stop() {
        pendingRead?.cancel()
        pendingRead = nil
        detach()
    }

    /// Appelé sur le thread principal par `ApplicationObserver` à chaque
    /// activation retenue. Attache l'observateur au nouveau processus et
    /// programme une première lecture de sa fenêtre.
    func track(_ application: NSRunningApplication, context: ApplicationContext) {
        detach()
        guard accessibilityAvailable() else { return }
        guard !ignoredApplications.contains(context) else {
            // Rien n'est émis pour cette application ; le retour vers la
            // fenêtre précédente doit de nouveau produire un événement.
            recorder.forget()
            return
        }
        observedApplication = context
        observedProcessID = application.processIdentifier
        attach(processID: application.processIdentifier)
        scheduleRead()
    }

    // MARK: - Accessibility

    private func accessibilityAvailable() -> Bool {
        let trusted = AXIsProcessTrusted()
        if trusted != accessibilityTrusted || !accessibilityWarned {
            accessibilityWarned = true
            accessibilityTrusted = trusted
            ObserverLog.write(
                trusted
                    ? "[macos-observer] accessibility granted: window context enabled"
                    : "[macos-observer] accessibility not granted: window context disabled "
                        + "(grant PulseApplicationObserver in System Settings › Privacy & Security › Accessibility)"
            )
        }
        return trusted
    }

    private func attach(processID: pid_t) {
        var created: AXObserver?
        let status = AXObserverCreate(processID, Self.notificationCallback, &created)
        guard status == .success, let observer = created else {
            ObserverLog.write(
                "[macos-observer] AXObserverCreate failed for pid \(processID): \(status.rawValue)"
            )
            return
        }
        let element = AXUIElementCreateApplication(processID)
        AXUIElementSetMessagingTimeout(element, Self.messagingTimeout)
        let refcon = Unmanaged.passUnretained(self).toOpaque()
        for name in Self.observedNotifications {
            // Une notification non prise en charge par l'application n'empêche
            // pas les autres : on ignore le statut individuel.
            _ = AXObserverAddNotification(observer, element, name as CFString, refcon)
        }
        CFRunLoopAddSource(
            CFRunLoopGetMain(),
            AXObserverGetRunLoopSource(observer),
            .defaultMode
        )
        axObserver = observer
        applicationElement = element
    }

    private func detach() {
        pendingRead?.cancel()
        pendingRead = nil
        if let observer = axObserver {
            if let element = applicationElement {
                for name in Self.observedNotifications {
                    _ = AXObserverRemoveNotification(observer, element, name as CFString)
                }
            }
            CFRunLoopRemoveSource(
                CFRunLoopGetMain(),
                AXObserverGetRunLoopSource(observer),
                .defaultMode
            )
        }
        axObserver = nil
        applicationElement = nil
        observedApplication = nil
        observedProcessID = 0
    }

    private static let notificationCallback: AXObserverCallback = {
        _, _, _, refcon in
        guard let refcon else { return }
        Unmanaged<WindowObserver>.fromOpaque(refcon)
            .takeUnretainedValue()
            .scheduleRead()
    }

    // MARK: - Reading

    private func scheduleRead() {
        pendingRead?.cancel()
        let work = DispatchWorkItem { [weak self] in
            self?.readFocusedWindow()
        }
        pendingRead = work
        DispatchQueue.main.asyncAfter(
            deadline: .now() + Self.coalescingDelay,
            execute: work
        )
    }

    private func readFocusedWindow() {
        pendingRead = nil
        guard let application = observedApplication,
              let applicationElement,
              NSWorkspace.shared.frontmostApplication?.processIdentifier == observedProcessID
        else {
            return
        }
        guard let window = focusedWindow(of: applicationElement) else {
            recorder.forget()
            return
        }
        let title = stringAttribute(window, kAXTitleAttribute)
        let classified = WindowDocumentPolicy.classify(
            stringAttribute(window, kAXDocumentAttribute)
        )
        var url = classified.url
        if url == nil, let bundleID = application.bundleID,
           Self.browserBundleIDs.contains(bundleID) {
            url = webAreaURL(under: window)
        }
        let context = WindowContext(
            application: application,
            title: title,
            document: classified.document,
            url: url
        )
        guard context.hasWindowInformation else {
            recorder.forget()
            return
        }
        do {
            try recorder.record(context)
        } catch {
            ObserverLog.write("Pulse WindowObserver: \(error)")
        }
    }

    private func focusedWindow(of application: AXUIElement) -> AXUIElement? {
        for attribute in [kAXFocusedWindowAttribute, kAXMainWindowAttribute] {
            if let value = attributeValue(application, attribute),
               CFGetTypeID(value) == AXUIElementGetTypeID() {
                let window = value as! AXUIElement
                AXUIElementSetMessagingTimeout(window, Self.messagingTimeout)
                return window
            }
        }
        return nil
    }

    /// Recherche en largeur, bornée, de la première zone web sous la fenêtre.
    /// Safari et les navigateurs Chromium exposent l'URL de l'onglet actif
    /// sur `AXWebArea.AXURL` ; aucun script ni autorisation supplémentaire.
    private func webAreaURL(under window: AXUIElement) -> String? {
        var queue: [(AXUIElement, Int)] = [(window, 0)]
        var visited = 0
        while !queue.isEmpty, visited < Self.searchNodeBudget {
            let (element, depth) = queue.removeFirst()
            visited += 1
            let role = stringAttribute(element, kAXRoleAttribute)
            if role == "AXWebArea" {
                return stringAttribute(element, kAXURLAttribute)
            }
            if depth >= Self.searchDepthLimit || Self.opaqueRoles.contains(role ?? "") {
                continue
            }
            guard let children = attributeValue(element, kAXChildrenAttribute)
                as? [AXUIElement] else {
                continue
            }
            queue.append(contentsOf: children.map { ($0, depth + 1) })
        }
        return nil
    }

    private func attributeValue(_ element: AXUIElement, _ attribute: String) -> CFTypeRef? {
        var value: CFTypeRef?
        let status = AXUIElementCopyAttributeValue(element, attribute as CFString, &value)
        guard status == .success else { return nil }
        return value
    }

    private func stringAttribute(_ element: AXUIElement, _ attribute: String) -> String? {
        guard let value = attributeValue(element, attribute) else { return nil }
        if let text = value as? String {
            return text
        }
        if let url = value as? URL {
            return url.absoluteString
        }
        return nil
    }

    deinit {
        stop()
    }
}
