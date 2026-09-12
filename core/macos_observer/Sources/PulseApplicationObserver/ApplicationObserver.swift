import AppKit
import ApplicationObserverCore
import Foundation

// NSWorkspace delivers the registered callback on the main queue, and the
// executable also owns/stops this observer from that queue.
final class ApplicationObserver: @unchecked Sendable {
    private let notificationCenter = NSWorkspace.shared.notificationCenter
    private let activationFilter = ApplicationActivationFilter()
    private var recorder: ApplicationEventRecorder
    private let windowObserver: WindowObserver
    private var activationToken: NSObjectProtocol?

    /// `pythonExecutable` : point d'injection des tests (pont lent, sans
    /// Core) ; `nil` en production, le pont choisit le Python du dépôt.
    init(
        repositoryRoot: URL,
        windowObserver: WindowObserver,
        pythonExecutable: URL? = nil
    ) throws {
        let bridge = OutboxBridge(
            repositoryRoot: repositoryRoot,
            pythonExecutable: pythonExecutable
        )
        self.recorder = try ApplicationEventRecorder(
            builder: CanonicalEventBuilder(instanceID: bridge.instanceID()),
            enqueue: bridge.enqueue
        )
        self.windowObserver = windowObserver
    }

    func start() {
        activationToken = notificationCenter.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification,
            object: nil,
            queue: .main
        ) { [weak self] notification in
            guard let notifiedApplication = notification.userInfo?[
                NSWorkspace.applicationUserInfoKey
            ] as? NSRunningApplication,
            let frontmostApplication = NSWorkspace.shared.frontmostApplication,
            self?.activationFilter.isFrontmostActivation(
                notifiedProcessID: notifiedApplication.processIdentifier,
                frontmostProcessID: frontmostApplication.processIdentifier
            ) == true else {
                return
            }
            self?.observe(frontmostApplication)
        }

        if let current = NSWorkspace.shared.frontmostApplication {
            observe(current)
        }
    }

    func stop() {
        if let activationToken {
            notificationCenter.removeObserver(activationToken)
            self.activationToken = nil
        }
    }

    // Interne, pas privé : les tests de réentrance l'appellent directement.
    func observe(_ application: NSRunningApplication) {
        guard let context = ApplicationContext(
            name: application.localizedName,
            bundleID: application.bundleIdentifier
        ) else {
            return
        }
        do {
            try recorder.record(context)
        } catch {
            ObserverLog.write("Pulse ApplicationObserver: \(error)")
        }
        // La fenêtre est suivie même quand l'activation est un doublon
        // (même app, autre fenêtre) : c'est le contexte de fenêtre qui change.
        windowObserver.track(application, context: context)
    }

    deinit {
        stop()
    }
}
