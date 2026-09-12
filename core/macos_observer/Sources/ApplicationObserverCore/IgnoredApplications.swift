import Foundation

/// Applications dont on n'observe jamais la fenêtre : messagerie, courrier,
/// appels, gestionnaires de mots de passe, réglages système. Le nom de
/// l'application reste observé par `app_activated` ; c'est le contexte de
/// fenêtre (titre, document, URL) qui est exclu.
///
/// La liste vit dans `~/.pulse_v2/ignored_applications` : un identifiant de
/// bundle ou un nom d'application par ligne, `#` pour un commentaire. Quand le
/// fichier existe, il remplace la liste par défaut ; l'installeur le crée
/// avec cette liste si absent.
public struct IgnoredApplications: Sendable {
    public static let defaultEntries: [String] = [
        "# Applications dont Pulse n'observe jamais la fenêtre (titre, document, URL).",
        "# Un identifiant de bundle ou un nom d'application par ligne. Après édition :",
        "#   launchctl kickstart -k gui/$(id -u)/com.pulse.app-observer",
        "com.apple.MobileSMS",
        "Messages",
        "com.apple.mail",
        "Mail",
        "com.apple.FaceTime",
        "FaceTime",
        "com.apple.keychainaccess",
        "Keychain Access",
        "Trousseaux d’accès",
        "com.apple.Passwords",
        "Passwords",
        "Mots de passe",
        "com.apple.systempreferences",
        "System Settings",
        "System Preferences",
        "Réglages Système",
        "Préférences Système",
        "com.1password.1password",
        "com.agilebits.onepassword7",
        "com.agilebits.onepassword-osx",
        "1Password",
        "com.bitwarden.desktop",
        "Bitwarden",
        "org.keepassxc.keepassxc",
        "KeePassXC",
        "com.dashlane.dashlanephonefinal",
        "Dashlane",
        "com.lastpass.LastPass",
        "LastPass",
        "in.sinew.Enpass-Desktop",
        "Enpass",
        "com.markmcguill.strongbox",
        "Strongbox",
        "com.nordpass.macos",
        "NordPass",
        "me.proton.pass.electron",
        "Proton Pass",
    ]

    public static let defaultFileContents =
        defaultEntries.joined(separator: "\n") + "\n"

    private let entries: Set<String>

    public init(entries: [String]) {
        self.entries = Set(entries.compactMap(Self.normalize))
    }

    public static let `default` = IgnoredApplications(entries: defaultEntries)

    /// Lit la liste dans le fichier de configuration ; sans fichier, la
    /// liste par défaut. Un fichier vide n'ignore rien.
    public static func load(from url: URL) -> IgnoredApplications {
        guard let data = FileManager.default.contents(atPath: url.path),
              let contents = String(data: data, encoding: .utf8) else {
            return .default
        }
        return parse(contents)
    }

    public static func parse(_ contents: String) -> IgnoredApplications {
        IgnoredApplications(entries: contents.components(separatedBy: .newlines))
    }

    public func contains(_ application: ApplicationContext) -> Bool {
        if let bundleID = application.bundleID,
           let normalized = Self.normalize(bundleID),
           entries.contains(normalized) {
            return true
        }
        guard let name = Self.normalize(application.app) else { return false }
        return entries.contains(name)
    }

    private static func normalize(_ line: String) -> String? {
        let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !trimmed.hasPrefix("#") else { return nil }
        // Les apostrophes typographique et droite désignent la même app.
        return trimmed
            .replacingOccurrences(of: "’", with: "'")
            .lowercased()
    }
}
