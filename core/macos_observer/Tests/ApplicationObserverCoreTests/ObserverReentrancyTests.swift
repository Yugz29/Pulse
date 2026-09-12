import AppKit
import Foundation
import Testing
@testable import ApplicationObserverCore
@testable import PulseApplicationObserver

/// Réentrance de `observe(_:)` pendant que `OutboxBridge.run` attend son
/// processus (TODOS « Réentrance fatale de PulseApplicationObserver »,
/// 4 traces « Fatal access conflict detected » le 2026-09-05).
///
/// Scénario reproduit : un bloc est en attente sur la run loop du thread qui
/// appelle `observe`, comme une notification AppKit livrée sur `.main`. Si
/// le pont fait tourner cette run loop pendant l'attente (`waitUntilExit`),
/// le bloc s'exécute **à l'intérieur** du premier `observe` : sur
/// `ApplicationObserver`, l'accès exclusif à `recorder` est violé et le
/// processus est abattu ; sur `SystemObserver`, le second événement est
/// enfilé avant le premier. Avec le pont corrigé (sémaphore), le bloc ne
/// s'exécute qu'après, et les deux événements sortent dans l'ordre.
private struct SlowBridgeFixture {
    let directory: URL
    let python: URL
    let log: URL

    init() throws {
        let fileManager = FileManager.default
        directory = fileManager.temporaryDirectory.appendingPathComponent(
            "pulse-observer-reentrancy-\(UUID().uuidString)",
            isDirectory: true
        )
        try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        log = directory.appendingPathComponent("enqueued.jsonl")
        python = directory.appendingPathComponent("slow-python.sh")
        // $1 = -m, $2 = daemon_v2.producer_outbox, $3 = commande.
        let script = """
            #!/bin/sh
            case "$3" in
              instance-id) printf stable-instance ;;
              enqueue-json) sleep 0.4; cat >> "\(log.path)"; printf '\\n' >> "\(log.path)" ;;
              *) echo "unexpected command: $3" >&2; exit 2 ;;
            esac
            """
        try Data(script.utf8).write(to: python)
        try fileManager.setAttributes([.posixPermissions: 0o700], ofItemAtPath: python.path)
    }

    func remove() {
        try? FileManager.default.removeItem(at: directory)
    }

    /// Les événements enfilés, dans l'ordre : (type, app).
    func enqueued() throws -> [(type: String, app: String?)] {
        guard let data = FileManager.default.contents(atPath: log.path) else { return [] }
        return try String(decoding: data, as: UTF8.self)
            .split(separator: "\n")
            .map { line in
                let object = try JSONSerialization.jsonObject(with: Data(line.utf8)) as! [String: Any]
                let details = object["details"] as? [String: Any]
                return (object["type"] as! String, details?["app"] as? String)
            }
    }
}

/// Fait exécuter `block` par la run loop courante, comme le ferait une
/// notification AppKit livrée sur le thread principal pendant l'enqueue.
private func enqueueOnCurrentRunLoop(_ block: @escaping @Sendable () -> Void) {
    CFRunLoopPerformBlock(CFRunLoopGetCurrent(), CFRunLoopMode.defaultMode.rawValue, block)
}

private func drainCurrentRunLoop() {
    // Assez pour livrer le bloc en attente ; sort dès qu'il n'y a plus rien.
    _ = CFRunLoopRunInMode(.defaultMode, 1.0, false)
}

private func twoDistinctRunningApplications() -> (NSRunningApplication, NSRunningApplication)? {
    let usable = NSWorkspace.shared.runningApplications.filter {
        $0.bundleIdentifier != nil && !($0.localizedName ?? "").isEmpty
    }
    var seen: [String: NSRunningApplication] = [:]
    for application in usable {
        seen[application.bundleIdentifier!] = seen[application.bundleIdentifier!] ?? application
        if seen.count == 2 { break }
    }
    guard seen.count == 2 else { return nil }
    let pair = Array(seen.values)
    return (pair[0], pair[1])
}

@Test
func applicationObserverIsNotReenteredWhileTheBridgeWaits() throws {
    let fixture = try SlowBridgeFixture()
    defer { fixture.remove() }
    let applications = try #require(twoDistinctRunningApplications())

    let windowObserver = try WindowObserver(
        repositoryRoot: fixture.directory,
        ignoredApplicationsURL: fixture.directory.appendingPathComponent("absent"),
        pythonExecutable: fixture.python
    )
    let observer = try ApplicationObserver(
        repositoryRoot: fixture.directory,
        windowObserver: windowObserver,
        pythonExecutable: fixture.python
    )

    // La seconde activation attend sur la run loop pendant que la première
    // bloque dans le pont. Avec `waitUntilExit`, elle s'exécutait ici même,
    // dans `observe`, et violait l'accès exclusif à `recorder`.
    enqueueOnCurrentRunLoop { observer.observe(applications.1) }
    observer.observe(applications.0)
    #expect(try fixture.enqueued().count == 1)
    drainCurrentRunLoop()

    let enqueued = try fixture.enqueued()
    #expect(enqueued.map(\.type) == ["app_activated", "app_activated"])
    #expect(enqueued.map(\.app) == [applications.0.localizedName, applications.1.localizedName])
}

@Test
func systemObserverKeepsEventOrderWhileTheBridgeWaits() throws {
    let fixture = try SlowBridgeFixture()
    defer { fixture.remove() }
    let observer = try SystemObserver(
        repositoryRoot: fixture.directory,
        pythonExecutable: fixture.python
    )

    enqueueOnCurrentRunLoop { observer.observe(NSWorkspace.didWakeNotification) }
    observer.observe(NSWorkspace.willSleepNotification)
    #expect(try fixture.enqueued().map(\.type) == ["system_sleep"])
    drainCurrentRunLoop()

    #expect(try fixture.enqueued().map(\.type) == ["system_sleep", "system_wake"])
}
