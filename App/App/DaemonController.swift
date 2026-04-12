import Foundation
import AppKit
import Combine

// MARK: - État du daemon

enum DaemonState {
    case running
    case paused
    case stopped
    case starting
    case stopping
    case restarting
}

// MARK: - DaemonController

/// Gère le cycle de vie du daemon Python.
/// Deux modes :
///   - LaunchAgent installé  → commandes launchctl
///   - Mode dev              → gestion directe du Process
@MainActor
class DaemonController: ObservableObject {

    @Published var state: DaemonState = .stopped
    @Published var lastError: String?  = nil

    private let base          = "http://127.0.0.1:8765"
    private let session       = URLSession.shared
    private let launchLabel   = "cafe.pulse.daemon"
    private var daemonProcess: Process?

    // Chemin de la plist installée
    private var launchAgentPlist: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/LaunchAgents/cafe.pulse.daemon.plist")
    }

    var isLaunchAgentInstalled: Bool {
        FileManager.default.fileExists(atPath: launchAgentPlist.path)
    }

    // ── Actions publiques ────────────────────────────────────────────────────

    func start() {
        guard state == .stopped else { return }
        state = .starting
        lastError = nil

        Task {
            if isLaunchAgentInstalled {
                await startViaLaunchctl()
            } else {
                await startDirectly()
            }
        }
    }

    func stop() {
        guard state == .running || state == .paused else { return }
        state = .stopping
        lastError = nil

        Task {
            await stopDaemon()
        }
    }

    func restart() {
        guard state == .running || state == .paused || state == .stopped else { return }
        state = .restarting
        lastError = nil

        Task {
            await restartDaemon()
        }
    }

    func pause() {
        guard state == .running else { return }
        lastError = nil
        Task {
            let status = await postDaemonStatus("/daemon/pause")
            await MainActor.run {
                if status == 200 {
                    self.state = .paused
                } else {
                    self.lastError = status == 404
                        ? "Pause indisponible — redémarre le daemon"
                        : "Pause du daemon échouée"
                }
            }
        }
    }

    func resume() {
        guard state == .paused else { return }
        lastError = nil
        Task {
            let status = await postDaemonStatus("/daemon/resume")
            await MainActor.run {
                if status == 200 {
                    self.state = .running
                } else {
                    self.lastError = status == 404
                        ? "Reprise indisponible — redémarre le daemon"
                        : "Reprise du daemon échouée"
                }
            }
        }
    }

    // ── Démarrage ────────────────────────────────────────────────────────────

    private func startViaLaunchctl() async {
        let uid = getuid()
        // Bootstrap d'abord : recharge la plist si le job avait été bootout'd (ex. après un Stop)
        _ = await shell("/bin/launchctl",
                        args: ["bootstrap", "gui/\(uid)", launchAgentPlist.path])
        // Puis kickstart : démarre ou force le redémarrage du service
        let result = await shell("/bin/launchctl",
                                 args: ["kickstart", "-k", "gui/\(uid)/\(launchLabel)"])
        if result.success {
            await waitForDaemon(timeout: 10)
        } else {
            state = .stopped
            lastError = result.output.isEmpty ? "launchctl kickstart échoué" : result.output
        }
    }

    private func startDirectly() async {
        // Cherche le script de démarrage depuis les répertoires connus
        guard let scriptURL = findStartScript() else {
            state = .stopped
            lastError = "Script start_pulse_daemon.sh introuvable.\nVérifiez ~/.pulse/settings.json (daemon_script_path)"
            return
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.arguments     = [scriptURL.path]
        process.environment   = ProcessInfo.processInfo.environment

        do {
            try process.run()
            daemonProcess = process
            await waitForDaemon(timeout: 15)
        } catch {
            state = .stopped
            lastError = "Erreur lancement : \(error.localizedDescription)"
        }
    }

    // ── Arrêt ────────────────────────────────────────────────────────────────

    private func stopDaemon() async {
        if isLaunchAgentInstalled {
            // Avec LaunchAgent : bootout empêche le redémarrage automatique,
            // puis on arrête le service proprement.
            let uid = getuid()
            _ = await shell("/bin/launchctl",
                            args: ["bootout", "gui/\(uid)/\(launchLabel)"])
            // bootout tue déjà le process — on attend la confirmation
            await waitForStop(timeout: 6)
        } else {
            // Mode dev : shutdown HTTP puis kill si nécessaire
            _ = await postDaemon("/daemon/shutdown")
            await waitForStop(timeout: 5)
            if state != .stopped {
                daemonProcess?.terminate()
                state = .stopped
            }
        }
    }

    // ── Redémarrage ──────────────────────────────────────────────────────────

    private func restartDaemon() async {
        if isLaunchAgentInstalled {
            // Avec LaunchAgent : kickstart -k recharge et relance le service
            let uid = getuid()
            // S'assure que le service est chargé (il peut avoir été bootout'd)
            _ = await shell("/bin/launchctl",
                            args: ["bootstrap", "gui/\(uid)", launchAgentPlist.path])
            let result = await shell("/bin/launchctl",
                                    args: ["kickstart", "-k", "gui/\(uid)/\(launchLabel)"])
            if result.success {
                await waitForDaemon(timeout: 15)
            } else {
                state = .stopped
                lastError = result.output.isEmpty ? "launchctl kickstart échoué" : result.output
            }
        } else {
            // Mode dev : shutdown HTTP puis redémarre le process
            _ = await postDaemon("/daemon/shutdown")
            await waitForStop(timeout: 4)
            await startDirectly()
        }
    }

    // ── Attente / polling ────────────────────────────────────────────────────

    /// Attend que le daemon réponde sur /ping (max `timeout` secondes).
    private func waitForDaemon(timeout: TimeInterval) async {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if await ping() {
                state = .running
                lastError = nil
                return
            }
            try? await Task.sleep(nanoseconds: 500_000_000)
        }
        state = .stopped
        lastError = "Daemon démarré mais ne répond pas sur :8765"
    }

    /// Attend que le daemon arrête de répondre (max `timeout` secondes).
    private func waitForStop(timeout: TimeInterval) async {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if !(await ping()) {
                state = .stopped
                return
            }
            try? await Task.sleep(nanoseconds: 400_000_000)
        }
        // Timeout — on suppose qu'il est quand même arrêté
        state = .stopped
    }

    // ── Helpers HTTP ─────────────────────────────────────────────────────────

    func ping() async -> Bool {
        guard let url = URL(string: "\(base)/ping") else { return false }
        do {
            let (_, response) = try await session.data(from: url)
            return (response as? HTTPURLResponse)?.statusCode == 200
        } catch { return false }
    }

    @discardableResult
    private func postDaemon(_ path: String) async -> Bool {
        (await postDaemonStatus(path)) == 200
    }

    private func postDaemonStatus(_ path: String) async -> Int? {
        guard let url = URL(string: "\(base)\(path)") else { return nil }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 3
        do {
            let (_, response) = try await session.data(for: req)
            return (response as? HTTPURLResponse)?.statusCode
        } catch { return nil }
    }

    // ── Shell helper ─────────────────────────────────────────────────────────

    private struct ShellResult { let success: Bool; let output: String }

    private func shell(_ path: String, args: [String]) async -> ShellResult {
        await withCheckedContinuation { continuation in
            DispatchQueue.global().async {
                let p   = Process()
                let out = Pipe()
                let err = Pipe()
                p.executableURL  = URL(fileURLWithPath: path)
                p.arguments      = args
                p.standardOutput = out
                p.standardError  = err
                do {
                    try p.run()
                    p.waitUntilExit()
                    let data   = out.fileHandleForReading.readDataToEndOfFile()
                    let errData = err.fileHandleForReading.readDataToEndOfFile()
                    let output = (String(data: data, encoding: .utf8) ?? "")
                               + (String(data: errData, encoding: .utf8) ?? "")
                    continuation.resume(returning: ShellResult(
                        success: p.terminationStatus == 0,
                        output:  output.trimmingCharacters(in: .whitespacesAndNewlines)
                    ))
                } catch {
                    continuation.resume(returning: ShellResult(success: false, output: error.localizedDescription))
                }
            }
        }
    }

    // ── Recherche du script de démarrage ─────────────────────────────────────

    private func findStartScript() -> URL? {
        // 1. Chemin personnalisé dans ~/.pulse/settings.json
        let settingsPath = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".pulse/settings.json")
        if let data = try? Data(contentsOf: settingsPath),
           let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let customPath = json["daemon_script_path"] as? String {
            let url = URL(fileURLWithPath: customPath)
            if FileManager.default.fileExists(atPath: url.path) { return url }
        }

        // 2. Chemin relatif à l'app bundle (production)
        if let bundlePath = Bundle.main.bundlePath.components(separatedBy: "/App/").first {
            let candidate = URL(fileURLWithPath: bundlePath)
                .appendingPathComponent("scripts/start_pulse_daemon.sh")
            if FileManager.default.fileExists(atPath: candidate.path) { return candidate }
        }

        // 3. Chemins de dev courants
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let devPaths = [
            "\(home)/Projets/Pulse/Pulse/scripts/start_pulse_daemon.sh",
            "\(home)/Projects/Pulse/Pulse/scripts/start_pulse_daemon.sh",
            "\(home)/Developer/Pulse/scripts/start_pulse_daemon.sh",
        ]
        for path in devPaths {
            if FileManager.default.fileExists(atPath: path) {
                return URL(fileURLWithPath: path)
            }
        }

        return nil
    }
}
