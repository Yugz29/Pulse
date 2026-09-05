import Foundation
import AppKit
import Testing
@testable import ApplicationObserverCore

@Test
func contextRequiresReadableApplicationName() {
    #expect(ApplicationContext(name: nil, bundleID: "com.example.App") == nil)
    #expect(ApplicationContext(name: "  ", bundleID: "com.example.App") == nil)
}

@Test
func contextNormalizesOptionalBundleIdentifier() {
    let withoutBundle = ApplicationContext(name: "Terminal", bundleID: " ")
    let withBundle = ApplicationContext(
        name: "Visual Studio Code",
        bundleID: "com.microsoft.VSCode"
    )

    #expect(withoutBundle?.app == "Terminal")
    #expect(withoutBundle?.bundleID == nil)
    #expect(withBundle?.bundleID == "com.microsoft.VSCode")
}

@Test
func deduplicationPrefersBundleIdentifier() {
    var deduplicator = ApplicationDeduplicator()
    let first = ApplicationContext(name: "Code", bundleID: "com.microsoft.VSCode")!
    let renamed = ApplicationContext(
        name: "Visual Studio Code",
        bundleID: "com.microsoft.VSCode"
    )!

    #expect(!deduplicator.isDuplicate(first))
    deduplicator.record(first)
    #expect(deduplicator.isDuplicate(renamed))
}

@Test
func deduplicationFallsBackToApplicationName() {
    var deduplicator = ApplicationDeduplicator()
    let first = ApplicationContext(name: "Terminal", bundleID: nil)!
    let repeated = ApplicationContext(name: "Terminal", bundleID: nil)!
    let changed = ApplicationContext(name: "Safari", bundleID: nil)!

    deduplicator.record(first)
    #expect(deduplicator.isDuplicate(repeated))
    #expect(!deduplicator.isDuplicate(changed))
}

@Test
func initialApplicationIsRecordedAndFirstNotificationIsDeduplicated() {
    var deduplicator = ApplicationDeduplicator()
    let initial = ApplicationContext(
        name: "Terminal",
        bundleID: "com.apple.Terminal"
    )!

    #expect(!deduplicator.isDuplicate(initial))
    deduplicator.record(initial)
    #expect(deduplicator.isDuplicate(initial))
}

@Test
func failedApplicationEnqueueDoesNotPoisonDeduplication() throws {
    enum EnqueueFailure: Error {
        case simulated
    }

    final class FailingBridge: @unchecked Sendable {
        var attempts = 0

        func enqueue(_ payload: Data) throws {
            attempts += 1
            if attempts == 1 {
                throw EnqueueFailure.simulated
            }
        }
    }

    let bridge = FailingBridge()
    var recorder = try ApplicationEventRecorder(
        builder: CanonicalEventBuilder(instanceID: "stable-instance"),
        enqueue: bridge.enqueue
    )
    let context = ApplicationContext(
        name: "Terminal",
        bundleID: "com.apple.Terminal"
    )!

    #expect(throws: EnqueueFailure.simulated) {
        try recorder.record(context)
    }
    #expect(try recorder.record(context))
    #expect(bridge.attempts == 2)
}

@Test
func outboxBridgeDrainsLargeChildOutputWithoutDeadlocking() throws {
    let fileManager = FileManager.default
    let temporaryDirectory = fileManager.temporaryDirectory.appendingPathComponent(
        "pulse-outbox-bridge-\(UUID().uuidString)",
        isDirectory: true
    )
    try fileManager.createDirectory(
        at: temporaryDirectory,
        withIntermediateDirectories: true
    )
    defer { try? fileManager.removeItem(at: temporaryDirectory) }

    let executable = temporaryDirectory.appendingPathComponent("large-output.sh")
    let script = """
        #!/bin/sh
        yes x | head -c 1048576
        yes e | head -c 1048576 >&2
        printf stable-instance
        """
    try Data(script.utf8).write(to: executable)
    try fileManager.setAttributes(
        [.posixPermissions: 0o700],
        ofItemAtPath: executable.path
    )

    let bridge = OutboxBridge(
        repositoryRoot: temporaryDirectory,
        pythonExecutable: executable
    )
    let startedAt = Date()
    let instanceID = try bridge.instanceID()

    #expect(Date().timeIntervalSince(startedAt) < 5)
    #expect(instanceID.hasSuffix("stable-instance"))
    #expect(instanceID.utf8.count >= 1_048_576)
}

@Test
func onlyTheActuallyFrontmostActivationIsAccepted() {
    let filter = ApplicationActivationFilter()

    #expect(
        filter.isFrontmostActivation(
            notifiedProcessID: 42,
            frontmostProcessID: 42
        )
    )
    #expect(
        !filter.isFrontmostActivation(
            notifiedProcessID: 41,
            frontmostProcessID: 42
        )
    )
}

@Test
func canonicalPayloadContainsOnlyAllowedApplicationDetails() throws {
    let context = ApplicationContext(
        name: "Visual Studio Code",
        bundleID: "com.microsoft.VSCode"
    )!
    let builder = try CanonicalEventBuilder(instanceID: "stable-instance")
    let date = Date(timeIntervalSince1970: 1_700_000_000)
    let eventID = UUID(uuidString: "019C0000-0000-7000-8000-000000000001")!

    let data = try builder.build(
        context: context,
        occurredAt: date,
        eventID: eventID
    )
    let payload = try #require(
        JSONSerialization.jsonObject(with: data) as? [String: Any]
    )
    let producer = try #require(payload["producer"] as? [String: Any])
    let details = try #require(payload["details"] as? [String: Any])

    #expect(payload["event_id"] as? String == eventID.uuidString.lowercased())
    #expect(payload["schema_version"] as? Int == 1)
    #expect(payload["type"] as? String == "app_activated")
    #expect((payload["occurred_at"] as? String)?.hasSuffix("Z") == true)
    #expect(producer["name"] as? String == "pulse-macos-application-observer")
    #expect(producer["version"] as? String == "1")
    #expect(producer["instance_id"] as? String == "stable-instance")
    #expect(details["app"] as? String == "Visual Studio Code")
    #expect(details["bundle_id"] as? String == "com.microsoft.VSCode")
    #expect(Set(details.keys) == ["app", "bundle_id"])
}

@Test
func payloadOmitsUnavailableBundleIdentifier() throws {
    let context = ApplicationContext(name: "Terminal", bundleID: nil)!
    let builder = try CanonicalEventBuilder(instanceID: "stable-instance")
    let data = try builder.build(context: context)
    let payload = try #require(
        JSONSerialization.jsonObject(with: data) as? [String: Any]
    )
    let details = try #require(payload["details"] as? [String: Any])

    #expect(details["app"] as? String == "Terminal")
    #expect(details["bundle_id"] == nil)
}

@Test(
    arguments: [
        (NSWorkspace.willSleepNotification, SystemEvent.systemSleep),
        (NSWorkspace.didWakeNotification, SystemEvent.systemWake),
        (
            SystemNotificationProjector.screenLockedNotification,
            SystemEvent.screenLocked
        ),
        (
            SystemNotificationProjector.screenUnlockedNotification,
            SystemEvent.screenUnlocked
        ),
    ]
)
func systemNotificationsProjectToCanonicalEvents(
    notificationName: Notification.Name,
    expected: SystemEvent
) {
    let projector = SystemNotificationProjector()

    #expect(projector.event(for: notificationName) == expected)
}

@Test
func lockNotificationsUseTheDistributedNotificationCenterNames() {
    #expect(
        SystemNotificationProjector.distributedNotificationNames == [
            Notification.Name("com.apple.screenIsLocked"),
            Notification.Name("com.apple.screenIsUnlocked"),
        ]
    )
    #expect(
        !SystemNotificationProjector.workspaceNotificationNames.contains(
            NSWorkspace.sessionDidResignActiveNotification
        )
    )
    #expect(
        !SystemNotificationProjector.workspaceNotificationNames.contains(
            NSWorkspace.sessionDidBecomeActiveNotification
        )
    )
}

@Test(arguments: SystemEvent.allCases)
func systemEventPayloadHasEmptyDetails(event: SystemEvent) throws {
    let builder = try CanonicalEventBuilder(instanceID: "stable-instance")
    let eventID = UUID(uuidString: "019C0000-0000-7000-8000-000000000002")!
    let data = try builder.build(
        systemEvent: event,
        occurredAt: Date(timeIntervalSince1970: 1_700_000_000),
        eventID: eventID
    )
    let payload = try #require(
        JSONSerialization.jsonObject(with: data) as? [String: Any]
    )
    let details = try #require(payload["details"] as? [String: Any])

    #expect(payload["type"] as? String == event.rawValue)
    #expect(payload["event_id"] as? String == eventID.uuidString.lowercased())
    #expect(payload["schema_version"] as? Int == 1)
    #expect(details.isEmpty)
}

@Test
func repeatedSystemNotificationsAreSafelyDeduplicated() {
    var deduplicator = SystemEventDeduplicator()

    for event in SystemEvent.allCases {
        #expect(!deduplicator.isDuplicate(event))
        deduplicator.record(event)
        #expect(deduplicator.isDuplicate(event))
        #expect(deduplicator.isDuplicate(event))
    }
}

// MARK: - Réentrance du pont (hardening 0.5.6)

/// Boîte mutable partagée avec un bloc de run loop exécuté sur le même thread.
private final class ReentrancyFlag: @unchecked Sendable {
    var didRun = false
}

@Test
func outboxBridgeDoesNotPumpTheRunLoopWhileWaiting() throws {
    // `waitUntilExit` fait tourner la run loop du thread appelant. Sur le
    // thread principal de l'observateur, elle redélivrait
    // `didActivateApplicationNotification` pendant l'enqueue : `observe(_:)`
    // était ré-entré, l'accès exclusif à `recorder` violé, le processus abattu
    // (« Fatal access conflict detected », 4 fois le 2026-09-05).
    let fileManager = FileManager.default
    let temporaryDirectory = fileManager.temporaryDirectory.appendingPathComponent(
        "pulse-outbox-reentrancy-\(UUID().uuidString)",
        isDirectory: true
    )
    try fileManager.createDirectory(
        at: temporaryDirectory,
        withIntermediateDirectories: true
    )
    defer { try? fileManager.removeItem(at: temporaryDirectory) }

    let executable = temporaryDirectory.appendingPathComponent("slow.sh")
    let script = """
        #!/bin/sh
        sleep 0.5
        printf stable-instance
        """
    try Data(script.utf8).write(to: executable)
    try fileManager.setAttributes(
        [.posixPermissions: 0o700],
        ofItemAtPath: executable.path
    )

    let bridge = OutboxBridge(
        repositoryRoot: temporaryDirectory,
        pythonExecutable: executable
    )

    // Un bloc en attente sur la run loop du thread courant : il ne doit
    // s'exécuter que si quelqu'un fait tourner cette run loop.
    let flag = ReentrancyFlag()
    let runLoop = CFRunLoopGetCurrent()
    CFRunLoopPerformBlock(runLoop, CFRunLoopMode.defaultMode.rawValue) {
        flag.didRun = true
    }
    CFRunLoopWakeUp(runLoop)

    _ = try bridge.instanceID()

    #expect(
        flag.didRun == false,
        "le pont a fait tourner la run loop pendant l'attente du processus"
    )

    // Sans cette seconde attente, le test passerait aussi si le bloc n'avait
    // jamais pu s'exécuter : on vérifie qu'il était bien en attente.
    CFRunLoopRunInMode(.defaultMode, 0.5, false)
    #expect(flag.didRun == true, "le bloc n'était pas réellement en attente")
}
