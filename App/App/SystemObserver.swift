import AppKit
import CoreGraphics
import Foundation

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - SystemObserver
// Observe le système macOS et envoie des events au daemon Python.
// Trois sources : NSWorkspace (apps), FSEvents (fichiers), Pasteboard (clipboard)
// ─────────────────────────────────────────────────────────────────────────────

class SystemObserver {

    // MARK: - Dépendances

    private let bridge: DaemonBridge

    // MARK: - État interne

    private var fsEventStream: FSEventStreamRef?
    private var clipboardTimer: Timer?
    private var idleTimer: Timer?
    private var lastClipboardContent: String = ""
    private var recentFileEvents: [String: Date] = [:]
    private var isUserIdle = false
    private var lastMeaningfulFilePath: String?
    private let filesystemQueue = DispatchQueue(label: "pulse.systemobserver.filesystem", qos: .utility)

    private let idleThresholdSeconds: TimeInterval = 900  // 15 min — 5 min était trop court (pause café = idle)
    private let idlePollInterval: TimeInterval = 15

    // Chemins surveillés par FSEvents (ajuster selon le projet)
    private let watchedPaths: [String] = [
        NSHomeDirectory() + "/Desktop",
        NSHomeDirectory() + "/Documents",
        NSHomeDirectory() + "/Developer",
        NSHomeDirectory() + "/Projects",
        NSHomeDirectory() + "/Projets"
    ]

    // MARK: - Init

    init(bridge: DaemonBridge = DaemonBridge()) {
        self.bridge = bridge
    }

    // MARK: - Lifecycle

    func startObserving() {
        observeActiveApp()
        observeFilesystem()
        observeClipboard()
        observeUserIdle()
        observeScreenLock()
        refreshCurrentContext()
    }

    func stopObserving() {
        // NSWorkspace notifications — auto-removed à la deallociation
        NotificationCenter.default.removeObserver(self)
        NSWorkspace.shared.notificationCenter.removeObserver(self)

        // FSEvents
        if let stream = fsEventStream {
            FSEventStreamStop(stream)
            FSEventStreamInvalidate(stream)
            FSEventStreamRelease(stream)
            fsEventStream = nil
        }

        // Clipboard polling
        clipboardTimer?.invalidate()
        clipboardTimer = nil

        // Idle polling
        idleTimer?.invalidate()
        idleTimer = nil
    }

    deinit { stopObserving() }

    // ─────────────────────────────────────────────────────────────────────────
    // MARK: - 1. App active (NSWorkspace)
    // ─────────────────────────────────────────────────────────────────────────

    private func observeActiveApp() {
        NSWorkspace.shared.notificationCenter.addObserver(
            self,
            selector: #selector(handleAppActivated(_:)),
            name: NSWorkspace.didActivateApplicationNotification,
            object: nil
        )
        NSWorkspace.shared.notificationCenter.addObserver(
            self,
            selector: #selector(handleAppLaunched(_:)),
            name: NSWorkspace.didLaunchApplicationNotification,
            object: nil
        )
        NSWorkspace.shared.notificationCenter.addObserver(
            self,
            selector: #selector(handleAppTerminated(_:)),
            name: NSWorkspace.didTerminateApplicationNotification,
            object: nil
        )
    }

    @objc private func handleAppActivated(_ notification: Notification) {
        guard let app = notification.userInfo?[NSWorkspace.applicationUserInfoKey]
                as? NSRunningApplication,
              let name = app.localizedName,
              let bundleId = app.bundleIdentifier
        else { return }

        guard shouldTrackApp(bundleId: bundleId) else { return }

        sendEvent([
            "type": "app_activated",
            "app_name": name,
            "bundle_id": bundleId,
            "timestamp": ISO8601DateFormatter().string(from: Date())
        ])
    }

    @objc private func handleAppLaunched(_ notification: Notification) {
        guard let app = notification.userInfo?[NSWorkspace.applicationUserInfoKey]
                as? NSRunningApplication,
              let name = app.localizedName
        else { return }

        sendEvent([
            "type": "app_launched",
            "app_name": name,
            "timestamp": ISO8601DateFormatter().string(from: Date())
        ])
    }

    @objc private func handleAppTerminated(_ notification: Notification) {
        guard let app = notification.userInfo?[NSWorkspace.applicationUserInfoKey]
                as? NSRunningApplication,
              let name = app.localizedName
        else { return }

        sendEvent([
            "type": "app_terminated",
            "app_name": name,
            "timestamp": ISO8601DateFormatter().string(from: Date())
        ])
    }

    // ─────────────────────────────────────────────────────────────────────────
    // MARK: - 2. Filesystem (FSEvents)
    // ─────────────────────────────────────────────────────────────────────────

    private func observeFilesystem() {
        guard !watchedPaths.isEmpty else { return }

        var ctx = FSEventStreamContext(
            version: 0,
            info: Unmanaged.passUnretained(self).toOpaque(),
            retain: nil,
            release: nil,
            copyDescription: nil
        )

        let callback: FSEventStreamCallback = { _, info, count, pathsRef, flags, _ in
            guard let info else { return }
            let observer = Unmanaged<SystemObserver>
                .fromOpaque(info).takeUnretainedValue()
            let paths = unsafeBitCast(pathsRef, to: NSArray.self)
            let flagsBuffer = UnsafeBufferPointer(
                start: flags, count: count
            )

            for i in 0..<count {
                guard let path = paths[i] as? String else { continue }
                let flag = flagsBuffer[i]
                let changeType = SystemObserver.changeType(from: flag)
                observer.handleFileChange(path: path, changeType: changeType)
            }
        }

        fsEventStream = FSEventStreamCreate(
            kCFAllocatorDefault,
            callback,
            &ctx,
            watchedPaths as CFArray,
            FSEventStreamEventId(kFSEventStreamEventIdSinceNow),
            0.8,   // latence en secondes (batching)
            FSEventStreamCreateFlags(kFSEventStreamCreateFlagFileEvents |
                                     kFSEventStreamCreateFlagUseCFTypes)
        )

        guard let stream = fsEventStream else { return }
        FSEventStreamSetDispatchQueue(stream, filesystemQueue)
        FSEventStreamStart(stream)
    }

    private func handleFileChange(path: String, changeType: String) {
        // Ignore les fichiers système / cachés / temporaires
        let name = (path as NSString).lastPathComponent
        // COMMIT_EDITMSG : laissé passer uniquement si c'est dans .git/
        // Le daemon gère la logique de déclenchement de rapport.
        // Tous les autres fichiers internes git sont filtrés.
        let isCommitMsg = name == "COMMIT_EDITMSG" && path.contains("/.git/")

        guard isCommitMsg || (
              !name.hasPrefix(".") &&
              !name.hasSuffix(".DS_Store") &&
              !name.hasSuffix("~") &&
              !name.hasSuffix(".xcuserstate") &&
              !name.contains(".sb-") &&
              !path.contains("/.git/") &&
              !path.contains("/node_modules/") &&
              !path.contains("/__pycache__/") &&
              !path.contains("/xcuserdata/") &&
              !path.contains("/DerivedData/")
        ) else { return }

        let dedupeKey = "\(changeType):\(path)"
        let now = Date()
        if let lastSeen = recentFileEvents[dedupeKey],
           now.timeIntervalSince(lastSeen) < 0.8 {
            return
        }
        recentFileEvents[dedupeKey] = now
        recentFileEvents = recentFileEvents.filter {
            now.timeIntervalSince($0.value) < 5
        }
        lastMeaningfulFilePath = path

        sendEvent([
            "type": "file_\(changeType)",
            "path": path,
            "extension": (path as NSString).pathExtension,
            "timestamp": ISO8601DateFormatter().string(from: Date())
        ])
    }

    private static func changeType(from flags: FSEventStreamEventFlags) -> String {
        // "modified" testé avant "renamed" : les écritures atomiques (Xcode, etc.)
        // lèvent kFSEventStreamEventFlagItemRenamed | kFSEventStreamEventFlagItemModified
        // ensemble. On préfère "modified" dans ce cas — un vrai renommage n'a
        // généralement pas le flag ItemModified en même temps.
        let isModified = flags & UInt32(kFSEventStreamEventFlagItemModified) != 0
        let isCreated  = flags & UInt32(kFSEventStreamEventFlagItemCreated)  != 0
        let isRemoved  = flags & UInt32(kFSEventStreamEventFlagItemRemoved)  != 0
        let isRenamed  = flags & UInt32(kFSEventStreamEventFlagItemRenamed)  != 0

        if isCreated && !isModified && !isRenamed { return "created" }
        if isRemoved && !isModified && !isRenamed { return "deleted" }
        if isRenamed && !isModified               { return "renamed" }
        return "modified"
    }

    // ─────────────────────────────────────────────────────────────────────────
    // MARK: - 3. Clipboard (polling NSPasteboard)
    // ─────────────────────────────────────────────────────────────────────────
    // NSPasteboard n'a pas de notification native → polling à 1 Hz.
    // changeCount permet de détecter un changement sans lire le contenu inutilement.

    private var lastChangeCount: Int = NSPasteboard.general.changeCount

    private func observeClipboard() {
        clipboardTimer = Timer.scheduledTimer(
            withTimeInterval: 1.0,
            repeats: true
        ) { [weak self] _ in
            self?.checkClipboard()
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // MARK: - 4. User idle / active
    // ─────────────────────────────────────────────────────────────────────────

    private func observeUserIdle() {
        idleTimer = Timer.scheduledTimer(
            withTimeInterval: idlePollInterval,
            repeats: true
        ) { [weak self] _ in
            self?.checkUserIdle()
        }
    }

    private func checkUserIdle() {
        let idleSeconds = CGEventSource.secondsSinceLastEventType(
            .combinedSessionState,
            eventType: .null
        )

        if idleSeconds >= idleThresholdSeconds {
            guard !isUserIdle else { return }
            isUserIdle = true
            sendEvent([
                "type": "user_idle",
                "seconds": String(Int(idleSeconds.rounded())),
                "timestamp": ISO8601DateFormatter().string(from: Date())
            ])
            return
        }

        guard isUserIdle else { return }
        isUserIdle = false
        sendEvent([
            "type": "user_active",
            "seconds": String(Int(idleSeconds.rounded())),
            "timestamp": ISO8601DateFormatter().string(from: Date())
        ])
    }

    private func checkClipboard() {
        let pb = NSPasteboard.general
        guard pb.changeCount != lastChangeCount else { return }
        lastChangeCount = pb.changeCount

        guard let content = pb.string(forType: .string),
              !content.isEmpty,
              content != lastClipboardContent
        else { return }

        lastClipboardContent = content
        let kind = clipboardContentKind(content)

        // Tronque avant d'envoyer au daemon (évite les gros payloads)
        let preview = String(content.prefix(500))

        sendEvent([
            "type": "clipboard_updated",
            "content": preview,
            "content_kind": kind,
            "char_count": "\(content.count)",
            "timestamp": ISO8601DateFormatter().string(from: Date())
        ])
    }

    private func clipboardContentKind(_ text: String) -> String {
        // Détection simple — le daemon peut affiner
        if text.hasPrefix("http://") || text.hasPrefix("https://") { return "url" }
        if text.contains("\n") && (
            text.contains("func ") ||
            text.contains("def ") ||
            text.contains("const ") ||
            text.contains("class ") ||
            text.contains("import ")
        ) { return "code" }
        if text.contains("Error:") || text.contains("Traceback") ||
           text.contains("at line") || text.contains("stack trace") {
            return "stacktrace"
        }
        return "text"
    }

    // ─────────────────────────────────────────────────────────────────────────
    // MARK: - 5. Screen lock / unlock
    // ─────────────────────────────────────────────────────────────────────────

    private func observeScreenLock() {
        NSWorkspace.shared.notificationCenter.addObserver(
            self,
            selector: #selector(handleScreenLocked),
            name: NSWorkspace.screensDidSleepNotification,
            object: nil
        )
        NSWorkspace.shared.notificationCenter.addObserver(
            self,
            selector: #selector(handleScreenUnlocked),
            name: NSWorkspace.screensDidWakeNotification,
            object: nil
        )
    }

    @objc private func handleScreenLocked() {
        isUserIdle = true
        sendEvent(["type": "screen_locked",
                   "timestamp": ISO8601DateFormatter().string(from: Date())])
    }

    @objc private func handleScreenUnlocked() {
        isUserIdle = false
        sendEvent(["type": "screen_unlocked",
                   "timestamp": ISO8601DateFormatter().string(from: Date())])
    }

    // ─────────────────────────────────────────────────────────────────────────
    // MARK: - Envoi au daemon
    // ─────────────────────────────────────────────────────────────────────────

    private func sendEvent(_ payload: [String: String]) {
        Task(priority: .utility) {
            try? await bridge.sendEvent(payload)
        }
    }

    func refreshCurrentContext() {
        if let app = NSWorkspace.shared.frontmostApplication,
           let name = app.localizedName,
           let bundleId = app.bundleIdentifier,
           shouldTrackApp(bundleId: bundleId) {
            sendEvent([
                "type": "app_activated",
                "app_name": name,
                "bundle_id": bundleId,
                "timestamp": ISO8601DateFormatter().string(from: Date())
            ])
        }

        if let path = lastMeaningfulFilePath, !path.isEmpty {
            sendEvent([
                "type": "file_modified",
                "path": path,
                "extension": (path as NSString).pathExtension,
                "timestamp": ISO8601DateFormatter().string(from: Date())
            ])
        }
    }

    private func shouldTrackApp(bundleId: String) -> Bool {
        bundleId != "com.apple.finder" && !bundleId.contains("pulse")
    }
}
