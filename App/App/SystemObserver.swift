import AppKit
import ApplicationServices
import CoreGraphics
import Foundation

actor EventDeliveryQueue {
    private let bridge: DaemonBridge

    init(bridge: DaemonBridge) {
        self.bridge = bridge
    }

    func send(_ payload: [String: String]) async {
        try? await bridge.sendEvent(payload)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MARK: - SystemObserver
// Observe le système macOS et envoie des events au daemon Python.
// Sources : NSWorkspace (apps), FSEvents (fichiers), Pasteboard (clipboard),
//           Accessibility API (titre de fenêtre active)
// ─────────────────────────────────────────────────────────────────────────────

class SystemObserver {

    // MARK: - Dépendances

    private let bridge: DaemonBridge
    private let eventDeliveryQueue: EventDeliveryQueue

    // MARK: - État interne

    private var fsEventStream: FSEventStreamRef?
    private var clipboardTimer: Timer?
    private var idleTimer: Timer?
    private var lastClipboardContent: String = ""
    private var recentFileEvents: [String: Date] = [:]
    private var isUserIdle = false
    private var lastMeaningfulFilePath: String?
    private let filesystemQueue = DispatchQueue(label: "pulse.systemobserver.filesystem", qos: .utility)

    // Déduplication des titres de fenêtres — on n'émet pas si le titre
    // n'a pas changé depuis le dernier event window_title.
    private var lastWindowTitle: String = ""
    private var lastWindowTitleApp: String = ""

    private let idleThresholdSeconds: TimeInterval = 900  // 15 min
    private let idlePollInterval: TimeInterval = 15

    private let watchedPaths: [String] = [NSHomeDirectory()]

    // MARK: - Init

    init(bridge: DaemonBridge = DaemonBridge()) {
        self.bridge = bridge
        self.eventDeliveryQueue = EventDeliveryQueue(bridge: bridge)
    }

    // MARK: - Lifecycle

    func startObserving() {
        observeActiveApp()
        observeFilesystem()
        observeClipboard()
        observeUserIdle()
        observeScreenLock()
        refreshCurrentContext()

        // Log si la permission Accessibility n'est pas encore accordée.
        // Pulse fonctionne sans, mais window_title ne sera pas capturé.
        if !AXIsProcessTrusted() {
            print("[Pulse] Permission Accessibility non accordée — window_title désactivé. Accorder dans Préférences Système → Confidentialité → Accessibilité.")
        }
    }

    func stopObserving() {
        NotificationCenter.default.removeObserver(self)
        NSWorkspace.shared.notificationCenter.removeObserver(self)
        DistributedNotificationCenter.default().removeObserver(self)

        if let stream = fsEventStream {
            FSEventStreamStop(stream)
            FSEventStreamInvalidate(stream)
            FSEventStreamRelease(stream)
            fsEventStream = nil
        }

        clipboardTimer?.invalidate()
        clipboardTimer = nil

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

        if bundleId == "com.apple.finder" {
            sendLocalExplorationEvent(appName: name, bundleId: bundleId)
            return
        }

        guard shouldTrackApp(bundleId: bundleId) else { return }

        sendEvent([
            "type": "app_activated",
            "app_name": name,
            "bundle_id": bundleId,
            "timestamp": ISO8601DateFormatter().string(from: Date())
        ])

        // Lecture du titre de fenêtre via Accessibility API.
        // Non-bloquant : lancé en arrière-plan, résultat envoyé si pertinent.
        let pid = app.processIdentifier
        DispatchQueue.global(qos: .utility).async { [weak self] in
            self?.readAndSendWindowTitle(appName: name, pid: pid)
        }
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
    // MARK: - 6. Titre de fenêtre (Accessibility API)
    // ─────────────────────────────────────────────────────────────────────────
    // Lit le titre de la fenêtre frontale d'une app via AXUIElement.
    // Niveau 1 : AXTitle uniquement — une seule requête, quasi gratuit.
    // Ne fonctionne que si la permission Accessibility est accordée.
    // Progression future : lire le contenu visible (Niveau 2) sur apps ciblées.

    private func readAndSendWindowTitle(appName: String, pid: pid_t) {
        guard AXIsProcessTrusted() else { return }

        let appElement = AXUIElementCreateApplication(pid)

        // Récupère la fenêtre frontale
        var frontWindowRef: CFTypeRef?
        guard AXUIElementCopyAttributeValue(
            appElement,
            kAXFocusedWindowAttribute as CFString,
            &frontWindowRef
        ) == .success,
              let frontWindow = frontWindowRef else { return }

        // Lit le titre (AXTitle)
        var titleRef: CFTypeRef?
        guard AXUIElementCopyAttributeValue(
            frontWindow as! AXUIElement,
            kAXTitleAttribute as CFString,
            &titleRef
        ) == .success,
              let title = titleRef as? String,
              !title.isEmpty else { return }

        // Déduplication — on n'émet pas si le titre + app n'ont pas changé
        let dedupeKey = "\(appName):\(title)"
        guard dedupeKey != "\(lastWindowTitleApp):\(lastWindowTitle)" else { return }

        lastWindowTitle = title
        lastWindowTitleApp = appName

        // Filtre les titres non informatifs
        guard !isTrivialWindowTitle(title, appName: appName) else { return }

        sendEvent([
            "type": "window_title",
            "app_name": appName,
            "title": title,
            "timestamp": ISO8601DateFormatter().string(from: Date())
        ])
    }

    private func isTrivialWindowTitle(_ title: String, appName: String) -> Bool {
        // Titre identique au nom de l'app — pas d'information supplémentaire
        if title == appName { return true }
        // Titres génériques fréquents
        let trivial: Set<String> = [
            "Untitled", "Sans titre", "New Tab", "Nouvel onglet",
            "New Window", "Nouvelle fenêtre", ""
        ]
        return trivial.contains(title)
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
            let flagsBuffer = UnsafeBufferPointer(start: flags, count: count)

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
            0.8,
            FSEventStreamCreateFlags(kFSEventStreamCreateFlagFileEvents |
                                     kFSEventStreamCreateFlagUseCFTypes)
        )

        guard let stream = fsEventStream else { return }
        FSEventStreamSetDispatchQueue(stream, filesystemQueue)
        FSEventStreamStart(stream)
    }

    private func handleFileChange(path: String, changeType: String) {
        let name = (path as NSString).lastPathComponent
        let isCommitMsg = name == "COMMIT_EDITMSG" && path.contains("/.git/")

        guard !isPulseInternalPath(path) else { return }

        guard isCommitMsg || (
              !name.hasPrefix(".") &&
              !name.hasSuffix(".DS_Store") &&
              !name.hasSuffix("~") &&
              !name.hasSuffix(".xcuserstate") &&
              !name.contains(".sb-") &&
              !path.contains("/.git/") &&
              !path.contains("/node_modules/") &&
              !path.contains("/__pycache__/") &&
              !path.contains("/Library/") &&
              !path.contains("/.Trash/") &&
              !path.contains("/xcuserdata/") &&
              !path.contains("/DerivedData/")
        ) else { return }

        let dedupeKey = "\(changeType):\(path)"
        let now = Date()
        if let lastSeen = recentFileEvents[dedupeKey],
           now.timeIntervalSince(lastSeen) < 0.8 { return }
        recentFileEvents[dedupeKey] = now
        recentFileEvents = recentFileEvents.filter { now.timeIntervalSince($0.value) < 5 }

        if changeType != "deleted" && !isCommitMsg {
            lastMeaningfulFilePath = path
        }

        sendEvent([
            "type": "file_\(changeType)",
            "path": path,
            "extension": (path as NSString).pathExtension,
            "timestamp": ISO8601DateFormatter().string(from: Date())
        ])
    }

    private static func changeType(from flags: FSEventStreamEventFlags) -> String {
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

    private var lastChangeCount: Int = NSPasteboard.general.changeCount

    private func observeClipboard() {
        clipboardTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            self?.checkClipboard()
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // MARK: - 4. User idle / active
    // ─────────────────────────────────────────────────────────────────────────

    private func observeUserIdle() {
        idleTimer = Timer.scheduledTimer(withTimeInterval: idlePollInterval, repeats: true) { [weak self] _ in
            self?.checkUserIdle()
        }
    }

    private func checkUserIdle() {
        let idleSeconds = CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .null)

        if idleSeconds >= idleThresholdSeconds {
            guard !isUserIdle else { return }
            isUserIdle = true
            sendEvent(["type": "user_idle", "seconds": String(Int(idleSeconds.rounded())), "timestamp": ISO8601DateFormatter().string(from: Date())])
            return
        }

        guard isUserIdle else { return }
        isUserIdle = false
        sendEvent(["type": "user_active", "seconds": String(Int(idleSeconds.rounded())), "timestamp": ISO8601DateFormatter().string(from: Date())])
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

        sendEvent([
            "type": "clipboard_updated",
            "content_kind": kind,
            "char_count": "\(content.count)",
            "timestamp": ISO8601DateFormatter().string(from: Date())
        ])
    }

    private func clipboardContentKind(_ text: String) -> String {
        if text.hasPrefix("http://") || text.hasPrefix("https://") { return "url" }
        if text.contains("\n") && (
            text.contains("func ") || text.contains("def ") ||
            text.contains("const ") || text.contains("class ") || text.contains("import ")
        ) { return "code" }
        if text.contains("Error:") || text.contains("Traceback") ||
           text.contains("at line") || text.contains("stack trace") { return "stacktrace" }
        return "text"
    }

    // ─────────────────────────────────────────────────────────────────────────
    // MARK: - 5. Screen lock / unlock
    // ─────────────────────────────────────────────────────────────────────────

    private func observeScreenLock() {
        DistributedNotificationCenter.default().addObserver(self, selector: #selector(handleScreenLocked), name: NSNotification.Name("com.apple.screenIsLocked"), object: nil)
        DistributedNotificationCenter.default().addObserver(self, selector: #selector(handleScreenUnlocked), name: NSNotification.Name("com.apple.screenIsUnlocked"), object: nil)
        NSWorkspace.shared.notificationCenter.addObserver(self, selector: #selector(handleScreenLocked), name: NSWorkspace.screensDidSleepNotification, object: nil)
        NSWorkspace.shared.notificationCenter.addObserver(self, selector: #selector(handleScreenUnlocked), name: NSWorkspace.screensDidWakeNotification, object: nil)
    }

    @objc private func handleScreenLocked() {
        isUserIdle = true
        sendEvent(["type": "screen_locked", "timestamp": ISO8601DateFormatter().string(from: Date())])
    }

    @objc private func handleScreenUnlocked() {
        isUserIdle = false
        sendEvent(["type": "screen_unlocked", "timestamp": ISO8601DateFormatter().string(from: Date())])
    }

    // ─────────────────────────────────────────────────────────────────────────
    // MARK: - Envoi au daemon
    // ─────────────────────────────────────────────────────────────────────────

    private func sendEvent(_ payload: [String: String]) {
        Task(priority: .utility) {
            await eventDeliveryQueue.send(payload)
        }
    }

    func refreshCurrentContext() {
        if let app = NSWorkspace.shared.frontmostApplication,
           let name = app.localizedName,
           let bundleId = app.bundleIdentifier {
            if bundleId == "com.apple.finder" {
                sendLocalExplorationEvent(appName: name, bundleId: bundleId)
            } else if shouldTrackApp(bundleId: bundleId) {
                sendEvent(["type": "app_activated", "app_name": name, "bundle_id": bundleId, "timestamp": ISO8601DateFormatter().string(from: Date())])
                let pid = app.processIdentifier
                DispatchQueue.global(qos: .utility).async { [weak self] in
                    self?.readAndSendWindowTitle(appName: name, pid: pid)
                }
            }
        }

        if let path = lastMeaningfulFilePath,
           !path.isEmpty,
           FileManager.default.fileExists(atPath: path) {
            sendEvent(["type": "file_modified", "path": path, "extension": (path as NSString).pathExtension, "timestamp": ISO8601DateFormatter().string(from: Date())])
        }
    }

    private func isPulseInternalPath(_ path: String) -> Bool {
        let pulseHome = NSHomeDirectory() + "/.pulse"
        return path == pulseHome || path.hasPrefix(pulseHome + "/")
    }

    private func sendLocalExplorationEvent(appName: String, bundleId: String) {
        sendEvent(["type": "local_exploration", "app_name": appName, "bundle_id": bundleId, "timestamp": ISO8601DateFormatter().string(from: Date())])
    }

    private func shouldTrackApp(bundleId: String) -> Bool {
        let blockedBundleIds: Set<String> = ["com.apple.finder", "com.apple.loginwindow"]
        return !blockedBundleIds.contains(bundleId) && !bundleId.contains("pulse")
    }
}
