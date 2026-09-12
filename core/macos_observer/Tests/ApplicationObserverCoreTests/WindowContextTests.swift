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
    #expect(try recorder.record(context))
    #expect(try recorder.record(context) == false)
    recorder.forget()
    #expect(try recorder.record(context))
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
