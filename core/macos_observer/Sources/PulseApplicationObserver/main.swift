import ApplicationObserverCore
import Darwin
import Foundation

let configuredRoot = ProcessInfo.processInfo.environment["PULSE_CORE_REPO_ROOT"]
let repositoryRoot = URL(
    fileURLWithPath: configuredRoot ?? FileManager.default.currentDirectoryPath,
    isDirectory: true
)

let ignoredApplicationsURL = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent(".pulse_v2/ignored_applications")

do {
    let windowObserver = try WindowObserver(
        repositoryRoot: repositoryRoot,
        ignoredApplicationsURL: ignoredApplicationsURL
    )
    let applicationObserver = try ApplicationObserver(
        repositoryRoot: repositoryRoot,
        windowObserver: windowObserver
    )
    let systemObserver = try SystemObserver(repositoryRoot: repositoryRoot)
    windowObserver.start()
    applicationObserver.start()
    systemObserver.start()

    signal(SIGINT, SIG_IGN)
    signal(SIGTERM, SIG_IGN)
    let interruptSource = DispatchSource.makeSignalSource(signal: SIGINT, queue: .main)
    let terminateSource = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
    let stop: @Sendable () -> Void = {
        systemObserver.stop()
        applicationObserver.stop()
        windowObserver.stop()
        exit(0)
    }
    interruptSource.setEventHandler(handler: stop)
    terminateSource.setEventHandler(handler: stop)
    interruptSource.resume()
    terminateSource.resume()

    RunLoop.main.run()
} catch {
    ObserverLog.write("Pulse ApplicationObserver: \(error)")
    exit(1)
}
