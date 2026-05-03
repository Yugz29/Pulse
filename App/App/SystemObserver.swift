import AppKit
import ApplicationServices
import CoreGraphics
import Foundation
import IOKit

actor EventDeliveryQueue {
    private let bridge: DaemonBridge

    init(bridge: DaemonBridge) {
        self.bridge = bridge
    }

    func send(_ payload: [String: String]) async {
        do {
            try await bridge.sendEvent(payload)
        } catch {
            print("[Pulse] Échec envoi event \(payload["type"] ?? "unknown") : \(error)")
        }
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
    private var windowTitleTimer: Timer?
    private var lastPolledWindowTitle: String = ""
    private var lastClipboardContent: String = ""
    private var recentFileEvents: [String: Date] = [:]
    private var isUserIdle = false
    private var lastPresenceHeartbeatAt: Date?
    private var lastMeaningfulFilePath: String?
    private let filesystemQueue = DispatchQueue(label: "pulse.systemobserver.filesystem", qos: .utility)
    private let claudeSessionQueue = DispatchQueue(label: "pulse.systemobserver.claude-sessions", qos: .utility)

    // Déduplication des titres de fenêtres — supprimée : le titre est maintenant
    // intégré dans app_activated, la déduplication est gérée par le daemon.
    private let idleThresholdSeconds: TimeInterval = 900  // 15 min
    private let passivePresenceThresholdSeconds: TimeInterval = 60
    private let idlePollInterval: TimeInterval = 15
    private let presenceHeartbeatInterval: TimeInterval = 60

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
        observeWindowTitlePolling()
        observeClaudeDesktopSessions()
        refreshCurrentContext()

        if !AXIsProcessTrusted() {
            print("[Pulse] Permission Accessibility non accordée — window_title désactivé.")
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

        if let stream = claudeSessionStream {
            FSEventStreamStop(stream)
            FSEventStreamInvalidate(stream)
            FSEventStreamRelease(stream)
            claudeSessionStream = nil
        }

        clipboardTimer?.invalidate()
        clipboardTimer = nil

        idleTimer?.invalidate()
        idleTimer = nil

        windowTitleTimer?.invalidate()
        windowTitleTimer = nil

        unregisterAXObserver()
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

        let pid = app.processIdentifier

        // Lecture du titre de fenêtre en arrière-plan, puis envoi d'un seul
        // event app_activated enrichi. Si Accessibility n'est pas accordée
        // ou si la lecture échoue, l'event est envoyé sans le titre.
        DispatchQueue.global(qos: .utility).async { [weak self] in
            guard let self else { return }
            let title = self.readWindowTitle(pid: pid, appName: name)
            var payload: [String: String] = [
                "type": "app_activated",
                "app_name": name,
                "bundle_id": bundleId,
                "timestamp": ISO8601DateFormatter().string(from: Date())
            ]
            if let title {
                payload["window_title"] = title
            }
            self.sendEvent(payload)
        }

        // Enregistrer l'observateur AX sur la nouvelle app
        // pour capturer les changements de titre/onglet en temps réel.
        registerAXObserver(for: app)
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
    // Niveau 1 : AXTitle au changement d'app (dans handleAppActivated)
    // Niveau 2 : AXObserver + kAXTitleChangedNotification
    //            Callback instantané à chaque changement d'onglet/titre.
    //            Remplace le polling 60s — capture chaque navigation.

    // Observateur AX actif sur l'app frontale courante.
    private var axObserver: AXObserver?
    private var axObservedPid: pid_t = 0
    private var lastObservedTitle: String = ""

    // Callback C — appelé par le RunLoop principal à chaque changement de titre.
    // Utilise `info` (pointeur opaque) pour accéder à `self`.
    private static let axTitleChangedCallback: AXObserverCallbackWithInfo = {
        _, element, _, _, info in
        guard let info else { return }
        let observer = Unmanaged<SystemObserver>.fromOpaque(info).takeUnretainedValue()
        observer.handleAXTitleChanged(element: element)
    }

    private func handleAXTitleChanged(element: AXUIElement) {
        guard let app = NSWorkspace.shared.frontmostApplication,
              let appName = app.localizedName,
              let bundleId = app.bundleIdentifier,
              shouldTrackApp(bundleId: bundleId)
        else { return }

        // Lire le titre depuis l'élément qui a changé
        var titleRef: CFTypeRef?
        let result = AXUIElementCopyAttributeValue(
            element, kAXTitleAttribute as CFString, &titleRef
        )
        guard result == .success,
              let title = titleRef as? String,
              !title.isEmpty,
              !isTrivialWindowTitle(title, appName: appName)
        else { return }

        // Tronquer
        let maxLength = 120
        var finalTitle = title
        if finalTitle.count > maxLength {
            let truncated = String(finalTitle.prefix(maxLength))
            finalTitle = (truncated.lastIndex(of: " ").map { String(truncated[..<$0]) } ?? truncated) + "…"
        }

        // Déduplication
        guard finalTitle != lastObservedTitle else { return }
        lastObservedTitle = finalTitle

        sendEvent([
            "type": "window_title_poll",
            "app_name": appName,
            "bundle_id": bundleId,
            "title": finalTitle,
            "timestamp": ISO8601DateFormatter().string(from: Date())
        ])
    }

    // Enregistre l'observateur AX sur l'app frontale.
    // Appelé à chaque changement d'app active.
    private func registerAXObserver(for app: NSRunningApplication) {
        guard AXIsProcessTrusted() else { return }
        let pid = app.processIdentifier
        guard pid != axObservedPid else { return }

        // Désenregistrer l'ancien observateur
        unregisterAXObserver()

        var observer: AXObserver?
        let selfPtr = UnsafeMutableRawPointer(Unmanaged.passUnretained(self).toOpaque())
        guard AXObserverCreateWithInfoCallback(
            pid, Self.axTitleChangedCallback, &observer
        ) == .success, let observer else { return }

        let appElement = AXUIElementCreateApplication(pid)

        // Observer kAXTitleChangedNotification sur l'app et ses fenêtres
        AXObserverAddNotification(
            observer, appElement,
            kAXTitleChangedNotification as CFString, selfPtr
        )
        // Observer aussi kAXFocusedWindowChangedNotification
        // pour capter les changements de fenêtre dans la même app
        AXObserverAddNotification(
            observer, appElement,
            kAXFocusedWindowChangedNotification as CFString, selfPtr
        )

        CFRunLoopAddSource(
            CFRunLoopGetMain(),
            AXObserverGetRunLoopSource(observer),
            .defaultMode
        )

        self.axObserver = observer
        self.axObservedPid = pid
    }

    private func unregisterAXObserver() {
        guard let observer = axObserver else { return }
        CFRunLoopRemoveSource(
            CFRunLoopGetMain(),
            AXObserverGetRunLoopSource(observer),
            .defaultMode
        )
        axObserver = nil
        axObservedPid = 0
    }

    private func observeWindowTitlePolling() {
        // Le polling 60s reste en fallback pour les apps
        // qui ne remontent pas kAXTitleChangedNotification.
        windowTitleTimer = Timer.scheduledTimer(
            withTimeInterval: 60.0,
            repeats: true
        ) { [weak self] _ in
            self?.pollActiveWindowTitle()
        }
    }

    private func pollActiveWindowTitle() {
        guard AXIsProcessTrusted() else { return }
        guard !isUserIdle else { return }
        guard let app = NSWorkspace.shared.frontmostApplication,
              let appName = app.localizedName,
              let bundleId = app.bundleIdentifier,
              shouldTrackApp(bundleId: bundleId)
        else { return }

        let pid = app.processIdentifier
        DispatchQueue.global(qos: .utility).async { [weak self] in
            guard let self else { return }
            guard let title = self.readWindowTitle(pid: pid, appName: appName) else { return }
            guard title != self.lastPolledWindowTitle else { return }
            self.lastPolledWindowTitle = title
            // Si AXObserver est actif sur cette app, le poll ne fait que confirmer
            // Sinon c'est le fallback utile
            self.sendEvent([
                "type": "window_title_poll",
                "app_name": appName,
                "bundle_id": bundleId,
                "title": title,
                "timestamp": ISO8601DateFormatter().string(from: Date())
            ])
        }
    }
    // ─────────────────────────────────────────────────────────────────────────
    // Lit le titre de la fenêtre frontale d'une app via AXUIElement.
    // Niveau 1 : AXTitle uniquement — une seule requête, quasi gratuit.
    // Ne fonctionne que si la permission Accessibility est accordée.
    // Le titre est intégré directement dans app_activated — pas d'event séparé.

    private func readWindowTitle(pid: pid_t, appName: String) -> String? {
        guard AXIsProcessTrusted() else { return nil }

        let appElement = AXUIElementCreateApplication(pid)

        var frontWindowRef: CFTypeRef?
        guard AXUIElementCopyAttributeValue(
            appElement,
            kAXFocusedWindowAttribute as CFString,
            &frontWindowRef
        ) == .success,
              let frontWindow = frontWindowRef else { return nil }

        var titleRef: CFTypeRef?
        guard AXUIElementCopyAttributeValue(
            frontWindow as! AXUIElement,
            kAXTitleAttribute as CFString,
            &titleRef
        ) == .success,
              let title = titleRef as? String,
              !title.isEmpty else { return nil }

        guard !isTrivialWindowTitle(title, appName: appName) else { return nil }

        // Tronque les titres trop longs — 120 chars max.
        // Les titres GitHub/YouTube peuvent être très verbeux.
        let maxLength = 120
        if title.count > maxLength {
            let truncated = String(title.prefix(maxLength))
            // Coupe proprement au dernier espace pour ne pas trancher un mot.
            if let lastSpace = truncated.lastIndex(of: " ") {
                return String(truncated[..<lastSpace]) + "…"
            }
            return truncated + "…"
        }
        return title
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
              !path.contains("/.codex/") &&
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

    private func readSystemIdleSeconds() -> TimeInterval {
        let service = IOServiceGetMatchingService(
            kIOMainPortDefault,
            IOServiceMatching("IOHIDSystem")
        )
        guard service != 0 else {
            return CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .null)
        }
        defer { IOObjectRelease(service) }

        var properties: Unmanaged<CFMutableDictionary>?
        let result = IORegistryEntryCreateCFProperties(
            service,
            &properties,
            kCFAllocatorDefault,
            0
        )
        guard result == KERN_SUCCESS,
              let values = properties?.takeRetainedValue() as? [String: Any],
              let idleTime = values["HIDIdleTime"] as? NSNumber
        else {
            return CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: .null)
        }

        // HIDIdleTime is expressed in nanoseconds since the last keyboard/mouse input.
        return TimeInterval(idleTime.uint64Value) / 1_000_000_000
    }

    private func checkUserIdle() {
        let idleSeconds = readSystemIdleSeconds()
        let now = Date()
        let roundedIdleSeconds = Int(idleSeconds.rounded())

        sendUserPresenceHeartbeatIfNeeded(
            idleSeconds: roundedIdleSeconds,
            now: now
        )

        if idleSeconds >= idleThresholdSeconds {
            guard !isUserIdle else { return }
            isUserIdle = true
            sendEvent([
                "type": "user_idle",
                "seconds": String(roundedIdleSeconds),
                "timestamp": ISO8601DateFormatter().string(from: now)
            ])
            return
        }

        guard isUserIdle else { return }
        isUserIdle = false
        sendEvent([
            "type": "user_active",
            "seconds": String(roundedIdleSeconds),
            "timestamp": ISO8601DateFormatter().string(from: now)
        ])
    }

    private func sendUserPresenceHeartbeatIfNeeded(idleSeconds: Int, now: Date) {
        if let lastHeartbeat = lastPresenceHeartbeatAt,
           now.timeIntervalSince(lastHeartbeat) < presenceHeartbeatInterval {
            return
        }
        lastPresenceHeartbeatAt = now

        let presenceState: String
        if TimeInterval(idleSeconds) >= idleThresholdSeconds {
            presenceState = "idle"
        } else if TimeInterval(idleSeconds) >= passivePresenceThresholdSeconds {
            presenceState = "passive"
        } else {
            presenceState = "active"
        }

        sendEvent([
            "type": "user_presence",
            "idle_seconds": String(idleSeconds),
            "presence_state": presenceState,
            "timestamp": ISO8601DateFormatter().string(from: now)
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
        NSWorkspace.shared.notificationCenter.addObserver(self, selector: #selector(handleScreenDidWake), name: NSWorkspace.screensDidWakeNotification, object: nil)
    }

    @objc private func handleScreenLocked() {
        isUserIdle = true
        lastPresenceHeartbeatAt = nil
        sendEvent(["type": "screen_locked", "timestamp": ISO8601DateFormatter().string(from: Date())])
    }

    @objc private func handleScreenUnlocked() {
        isUserIdle = false
        lastPresenceHeartbeatAt = nil
        sendEvent(["type": "screen_unlocked", "timestamp": ISO8601DateFormatter().string(from: Date())])
    }

    @objc private func handleScreenDidWake() {
        // Un simple wake écran n'implique pas que la session utilisateur soit
        // déverrouillée. On ne publie donc aucun screen_unlocked ici.
    }

    // ─────────────────────────────────────────────────────────────────────────
    // MARK: - Envoi au daemon
    // ─────────────────────────────────────────────────────────────────────────

    // MARK: - 7. Sessions Claude Desktop
    //
    // Observe ~/Library/Application Support/Claude/claude-code-sessions/
    // et local-agent-mode-sessions/ via FSEvents.
    // Quand Claude Desktop crée ou met à jour une session, Pulse lit
    // le titre + répertoire de travail depuis le JSON et les publie.
    //
    // Entièrement autonome : pas de BLE, pas de prompt, pas de dépendance.

    private var claudeSessionStream: FSEventStreamRef?
    private var lastSeenSessionFiles: [String: String] = [:] // path → lastActivityAt

    private func observeClaudeDesktopSessions() {
        let base = NSString(string: "~/Library/Application Support/Claude").expandingTildeInPath
        let paths = [
            "\(base)/claude-code-sessions",
            "\(base)/local-agent-mode-sessions",
        ] as CFArray

        var ctx = FSEventStreamContext(
            version: 0,
            info: Unmanaged.passUnretained(self).toOpaque(),
            retain: nil, release: nil, copyDescription: nil
        )

        let callback: FSEventStreamCallback = { _, ctx, count, paths, _, _ in
            guard let ctx else { return }
            let obs = Unmanaged<SystemObserver>.fromOpaque(ctx).takeUnretainedValue()
            let pathArray = unsafeBitCast(paths, to: NSArray.self) as! [String]
            for path in pathArray.prefix(Int(count)) {
                obs.handleClaudeSessionPath(path)
            }
        }

        guard let stream = FSEventStreamCreate(
            nil, callback, &ctx,
            paths,
            FSEventStreamEventId(kFSEventStreamEventIdSinceNow),
            0.5,
            FSEventStreamCreateFlags(kFSEventStreamCreateFlagFileEvents | kFSEventStreamCreateFlagUseCFTypes)
        ) else { return }

        FSEventStreamSetDispatchQueue(stream, claudeSessionQueue)
        FSEventStreamStart(stream)
        claudeSessionStream = stream
    }

    private func handleClaudeSessionPath(_ path: String) {
        // On s'intéresse uniquement aux fichiers JSON de session
        guard path.hasSuffix(".json") else { return }

        DispatchQueue.global(qos: .utility).async { [weak self] in
            guard let self else { return }
            guard let data = try? Data(contentsOf: URL(fileURLWithPath: path)),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            else { return }

            let title    = json["title"] as? String ?? ""
            let cwd      = json["cwd"] as? String ?? ""
            let activity = json["lastActivityAt"] as? Int64 ?? 0
            let turns    = json["completedTurns"] as? Int ?? 0
            let archived = json["isArchived"] as? Bool ?? false

            // Ignorer les sessions archivées ou sans titre
            guard !archived, !title.isEmpty, !title.hasPrefix("Nouvelle session") else { return }

            // Déduplication : n'émettre que si lastActivityAt a changé
            let key = path
            let activityStr = String(activity)
            guard self.lastSeenSessionFiles[key] != activityStr else { return }
            self.lastSeenSessionFiles[key] = activityStr

            self.sendEvent([
                "type":       "claude_desktop_session",
                "title":      title,
                "cwd":        cwd,
                "turns":      String(turns),
                "timestamp":  ISO8601DateFormatter().string(from: Date()),
            ])
        }
    }

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
                let pid = app.processIdentifier
                DispatchQueue.global(qos: .utility).async { [weak self] in
                    guard let self else { return }
                    let title = self.readWindowTitle(pid: pid, appName: name)
                    var payload: [String: String] = [
                        "type": "app_activated",
                        "app_name": name,
                        "bundle_id": bundleId,
                        "timestamp": ISO8601DateFormatter().string(from: Date())
                    ]
                    if let title { payload["window_title"] = title }
                    self.sendEvent(payload)
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
