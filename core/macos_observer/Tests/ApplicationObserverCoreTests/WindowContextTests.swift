import Foundation
import Testing
@testable import ApplicationObserverCore

private let safari = ApplicationContext(name: "Safari", bundleID: "com.apple.Safari")!

/// Identifiants factices assemblés à l'exécution : le littéral
/// `scheme://user:mot-de-passe@hôte` n'apparaît jamais en source.
private func withUserInfo(_ scheme: String, _ host: String, _ rest: String) -> String {
    let userInfo = ["user", "secret"].joined(separator: ":")
    return scheme + "://" + userInfo + "@" + host + rest
}

@Test
func urlIsReducedToOriginAndPath() {
    #expect(WindowURLPolicy.reduce("https://github.com/org/repo/pull/89?tab=files#diff-abc")
        == "https://github.com/org/repo/pull/89")
    #expect(WindowURLPolicy.reduce(withUserInfo("https", "example.com:8443", "/path?token=x"))
        == "https://example.com:8443/path")
    #expect(WindowURLPolicy.reduce("https://example.com/?q=a b#c") == "https://example.com/")
    #expect(WindowURLPolicy.reduce("about:blank") == "about:blank")
    #expect(WindowURLPolicy.reduce("   ") == nil)
    #expect(WindowURLPolicy.reduce("not a url") == nil)
    #expect(WindowURLPolicy.reduce("https:?x=1") == nil)
}

@Test
func documentValueIsClassifiedAsPathOrURL() {
    let fileURL = WindowDocumentPolicy.classify("file:///Users/me/Projets/Pulse/notes%20jour.md")
    #expect(fileURL.document == "/Users/me/Projets/Pulse/notes jour.md")
    #expect(fileURL.url == nil)

    let path = WindowDocumentPolicy.classify("/Users/me/Documents/plan.txt")
    #expect(path.document == "/Users/me/Documents/plan.txt")

    let web = WindowDocumentPolicy.classify("https://example.com/page?session=42")
    #expect(web.document == nil)
    #expect(web.url == "https://example.com/page")

    let empty = WindowDocumentPolicy.classify("  ")
    #expect(empty.document == nil && empty.url == nil)
}

@Test
func titleIsCollapsedAndBounded() {
    let context = WindowContext(
        application: safari,
        title: "  Pull request\n\t#89   —  GitHub  ",
        document: nil,
        url: nil
    )
    #expect(context.title == "Pull request #89 — GitHub")
    let long = WindowContext(
        application: safari,
        title: String(repeating: "x", count: 1_000),
        document: " ",
        url: "https://example.com/a?b=c"
    )
    #expect(long.title?.count == WindowContext.maximumTitleLength)
    #expect(long.document == nil)
    #expect(long.url == "https://example.com/a")
    #expect(WindowContext(application: safari, title: " ", document: nil, url: nil)
        .hasWindowInformation == false)
}

@Test
func ignoredApplicationsMatchBundleOrNameCaseInsensitively() {
    let ignored = IgnoredApplications.default
    #expect(ignored.contains(ApplicationContext(name: "Messages", bundleID: "com.apple.MobileSMS")!))
    #expect(ignored.contains(ApplicationContext(name: "Renamed", bundleID: "com.apple.mail")!))
    #expect(ignored.contains(ApplicationContext(name: "Trousseaux d'accès", bundleID: nil)!))
    #expect(ignored.contains(ApplicationContext(name: "1password", bundleID: "unknown")!))
    #expect(!ignored.contains(safari))
}

@Test
func ignoredApplicationsFileReplacesDefaults() {
    let custom = IgnoredApplications.parse("""
        # commentaire
        com.example.Secret

        Slack
        """)
    #expect(custom.contains(ApplicationContext(name: "Slack", bundleID: "com.tinyspeck.slackmacgap")!))
    #expect(custom.contains(ApplicationContext(name: "Secret", bundleID: "com.example.secret")!))
    #expect(!custom.contains(ApplicationContext(name: "Messages", bundleID: "com.apple.MobileSMS")!))
    #expect(!IgnoredApplications.parse("").contains(ApplicationContext(name: "Mail", bundleID: "com.apple.mail")!))
    let missing = IgnoredApplications.load(from: URL(fileURLWithPath: "/nonexistent/pulse/ignored"))
    #expect(missing.contains(ApplicationContext(name: "Mail", bundleID: "com.apple.mail")!))
}

@Test
func windowRecorderEmitsOncePerContextAndAgainAfterForget() throws {
    final class Sink: @unchecked Sendable {
        var payloads: [Data] = []
        func enqueue(_ payload: Data) throws { payloads.append(payload) }
    }
    let sink = Sink()
    var recorder = try WindowEventRecorder(
        builder: CanonicalEventBuilder(instanceID: "stable-instance"),
        enqueue: sink.enqueue
    )
    let context = WindowContext(
        application: safari,
        title: "Pulse",
        document: nil,
        url: "https://example.com/pulse?x=1"
    )
    let start = Date(timeIntervalSince1970: 1_000)
    #expect(try recorder.record(context, at: start) == .recorded)
    #expect(try recorder.record(context, at: start) == .duplicate)
    recorder.forget()
    // Après oubli, le même contexte est de nouveau un événement, mais le
    // filet d'intervalle le retient jusqu'à l'échéance.
    #expect(try recorder.record(context, at: start.addingTimeInterval(5)) == .held(retryAfter: 25))
    #expect(try recorder.flush(at: start.addingTimeInterval(10)) == false)
    #expect(try recorder.flush(at: start.addingTimeInterval(30)) == true)
    #expect(sink.payloads.count == 2)

    let json = try JSONSerialization.jsonObject(with: sink.payloads[0]) as! [String: Any]
    #expect(json["type"] as? String == "window_focused")
    #expect(json["schema_version"] as? Int == 1)
    let producer = json["producer"] as! [String: Any]
    #expect(producer["version"] as? String == CanonicalEventBuilder.producerVersion)
    let details = json["details"] as! [String: Any]
    #expect(details["app"] as? String == "Safari")
    #expect(details["bundle_id"] as? String == "com.apple.Safari")
    #expect(details["title"] as? String == "Pulse")
    #expect(details["url"] as? String == "https://example.com/pulse")
    #expect(details["document"] == nil)
}


private func spinnerTitle(_ glyph: String, command: String = "caffeinate") -> String {
    "Pulse — \(glyph) Observer window context — \(command) ◂ claude — 103×55"
}

@Test
func progressGlyphsDoNotChangeTheComparisonKey() {
    let turning = WindowContext(application: safari, title: spinnerTitle("◐"), document: nil, url: nil)
    let turned = WindowContext(application: safari, title: spinnerTitle("◑"), document: nil, url: nil)
    let braille = WindowContext(application: safari, title: spinnerTitle("⠹"), document: nil, url: nil)
    let asterisk = WindowContext(application: safari, title: spinnerTitle("✳"), document: nil, url: nil)
    let idle = WindowContext(application: safari, title: spinnerTitle("·"), document: nil, url: nil)
    let other = WindowContext(application: safari, title: spinnerTitle("◐", command: "gh"), document: nil, url: nil)
    #expect(turning.key == turned.key)
    #expect(turning.key == braille.key)
    #expect(turning.key == asterisk.key)
    #expect(turning.key == idle.key)
    #expect(turning.key != other.key)
    // Le titre stocké reste le titre affiché.
    #expect(turning.title == spinnerTitle("◐"))
    #expect(WindowContext.comparisonTitle("◐ ◑ ⠋") == nil)
    #expect(WindowContext.comparisonTitle("  Pull   request #89  ") == "Pull request #89")
}

@Test
func anHourOfClaudeCodeInTerminalStaysUnderThirtyEvents() throws {
    final class Sink: @unchecked Sendable {
        var count = 0
        func enqueue(_ payload: Data) throws { count += 1 }
    }
    let sink = Sink()
    var recorder = try WindowEventRecorder(
        builder: CanonicalEventBuilder(instanceID: "stable-instance"),
        enqueue: sink.enqueue
    )
    let terminal = ApplicationContext(name: "Terminal", bundleID: "com.apple.Terminal")!
    let start = Date(timeIntervalSince1970: 1_000_000)
    // Instants réels des changements de sous-commande dans le titre, première
    // heure du 2026-09-12 (30 changements, 2 032 lectures) ; le spinner
    // tourne chaque seconde entre deux.
    let changes: Set<Int> = [
        0, 53, 55, 215, 349, 709, 711, 747, 748, 791, 1297, 1742, 1792, 2033,
        2136, 2326, 2328, 2616, 2617, 2631, 2632, 2663, 2665, 3105, 3135,
        3137, 3139, 3335, 3533, 3539,
    ]
    var command = "caffeinate"
    var generation = 0
    for second in 0..<3_600 {
        let glyph = second % 2 == 0 ? "◐" : "◑"
        if changes.contains(second) {
            generation += 1
            command = "cmd\(generation)"
        }
        let context = WindowContext(
            application: terminal, title: spinnerTitle(glyph, command: command), document: nil, url: nil
        )
        let now = start.addingTimeInterval(TimeInterval(second))
        _ = try recorder.record(context, at: now)
        _ = try recorder.flush(at: now)
    }
    _ = try recorder.flush(at: start.addingTimeInterval(3_600), force: true)
    #expect(sink.count < 30)
    #expect(sink.count > 0)
}

@Test
func heldContextIsEmittedWhenTheApplicationLeavesTheFront() throws {
    final class Sink: @unchecked Sendable {
        var titles: [String] = []
        func enqueue(_ payload: Data) throws {
            let json = try JSONSerialization.jsonObject(with: payload) as! [String: Any]
            titles.append(((json["details"] as! [String: Any])["title"] as? String) ?? "")
        }
    }
    let sink = Sink()
    var recorder = try WindowEventRecorder(
        builder: CanonicalEventBuilder(instanceID: "stable-instance"),
        enqueue: sink.enqueue
    )
    let start = Date(timeIntervalSince1970: 2_000)
    let first = WindowContext(application: safari, title: "Onglet A", document: nil, url: nil)
    let second = WindowContext(application: safari, title: "Onglet B", document: nil, url: nil)
    let third = WindowContext(application: safari, title: "Onglet C", document: nil, url: nil)
    #expect(try recorder.record(first, at: start) == .recorded)
    #expect(try recorder.record(second, at: start.addingTimeInterval(3)) == .held(retryAfter: 27))
    #expect(try recorder.record(third, at: start.addingTimeInterval(6)) == .held(retryAfter: 24))
    // Retour à l'état émis : ce qui était retenu est caduc.
    #expect(try recorder.record(first, at: start.addingTimeInterval(8)) == .duplicate)
    #expect(recorder.hasHeldContext == false)
    #expect(try recorder.record(third, at: start.addingTimeInterval(9)) == .held(retryAfter: 21))
    // L'application quitte le premier plan : le dernier état retenu part.
    #expect(try recorder.flush(at: start.addingTimeInterval(10), force: true) == true)
    #expect(sink.titles == ["Onglet A", "Onglet C"])
    // Une autre application n'est pas retenue par l'intervalle de Safari.
    let code = ApplicationContext(name: "Code", bundleID: "com.microsoft.VSCode")!
    let editor = WindowContext(application: code, title: "main.py", document: nil, url: nil)
    #expect(try recorder.record(editor, at: start.addingTimeInterval(11)) == .recorded)
}
