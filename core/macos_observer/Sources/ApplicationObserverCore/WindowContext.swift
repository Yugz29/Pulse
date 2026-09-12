import Foundation

/// Ce que l'utilisateur regarde dans la fenêtre au premier plan : le titre,
/// le document ouvert et l'URL de la page, jamais le contenu de la fenêtre.
///
/// Les trois champs sont déjà réduits ici (titre borné, URL sans identifiants,
/// paramètres ni fragment) ; Core applique la même réduction à l'ingestion,
/// c'est lui qui garantit ce qui entre en base.
public struct WindowContext: Equatable, Sendable {
    public static let maximumTitleLength = 300

    public let app: String
    public let bundleID: String?
    public let title: String?
    public let document: String?
    public let url: String?

    public init(
        application: ApplicationContext,
        title: String?,
        document: String?,
        url: String?
    ) {
        self.app = application.app
        self.bundleID = application.bundleID
        self.title = Self.normalizedTitle(title)
        self.document = Self.normalizedPath(document)
        self.url = url.flatMap(WindowURLPolicy.reduce)
    }

    /// Le contexte porte-t-il autre chose que le nom de l'application ?
    public var hasWindowInformation: Bool {
        title != nil || document != nil || url != nil
    }

    /// Identité de comparaison : le titre y est débarrassé des glyphes de
    /// progression. Un spinner (◐◑, ⠋⠙, ✳✶…) qui tourne chaque seconde dans
    /// le titre d'un terminal n'est pas un changement de fenêtre. Le titre
    /// stocké reste le titre affiché.
    public struct Key: Equatable, Sendable {
        public let app: String
        public let bundleID: String?
        public let title: String?
        public let document: String?
        public let url: String?
    }

    public var key: Key {
        Key(
            app: app,
            bundleID: bundleID,
            title: title.flatMap(Self.comparisonTitle),
            document: document,
            url: url
        )
    }

    /// Clé de l'application pour le filet d'intervalle : bundle, sinon nom.
    public var applicationKey: String {
        bundleID ?? app
    }

    /// Le titre sans ses glyphes de progression ni ses symboles décoratifs,
    /// espaces repliés. `nil` s'il ne reste rien.
    public static func comparisonTitle(_ title: String) -> String? {
        let kept = title.unicodeScalars.map { scalar -> Character in
            Self.isProgressGlyph(scalar) ? " " : Character(scalar)
        }
        let collapsed = String(kept)
            .split(whereSeparator: { $0.isWhitespace || $0.isNewline })
            .joined(separator: " ")
        return collapsed.isEmpty ? nil : collapsed
    }

    private static func isProgressGlyph(_ scalar: Unicode.Scalar) -> Bool {
        switch scalar.value {
        case 0x2800...0x28FF,   // motifs braille (spinners ⠋⠙⠹)
             0x25A0...0x25FF,   // formes géométriques (◐◑◒◓ ◂▸ ■□)
             0x2700...0x27BF,   // dingbats (✳ ✶ ✻ ✽ ✢)
             0x2B00...0x2BFF,   // symboles et flèches divers
             0x2300...0x23FF,   // techniques (⌛ ⏳)
             0x00B7, 0x2022, 0x2026:  // point médian, puce, points de suspension
            return true
        default:
            return scalar.properties.generalCategory == .otherSymbol
        }
    }

    static func normalizedTitle(_ raw: String?) -> String? {
        guard let raw else { return nil }
        let collapsed = raw
            .split(whereSeparator: { $0.isWhitespace || $0.isNewline })
            .joined(separator: " ")
        guard !collapsed.isEmpty else { return nil }
        return String(collapsed.prefix(maximumTitleLength))
    }

    static func normalizedPath(_ raw: String?) -> String? {
        guard let raw = raw?.trimmingCharacters(in: .whitespacesAndNewlines),
              !raw.isEmpty else {
            return nil
        }
        return raw
    }
}

/// Classement de la valeur `AXDocument` d'une fenêtre : un chemin local
/// (`file://` ou chemin absolu) devient `document`, une adresse web devient
/// `url`. Le reste est ignoré.
public enum WindowDocumentPolicy {
    public static func classify(_ raw: String?) -> (document: String?, url: String?) {
        guard let raw = raw?.trimmingCharacters(in: .whitespacesAndNewlines),
              !raw.isEmpty else {
            return (nil, nil)
        }
        if raw.hasPrefix("/") {
            return (raw, nil)
        }
        guard let components = URLComponents(string: raw),
              let scheme = components.scheme?.lowercased() else {
            return (nil, nil)
        }
        if scheme == "file" {
            let path = components.percentEncodedPath.removingPercentEncoding
                ?? components.path
            return (path.isEmpty ? nil : path, nil)
        }
        return (nil, WindowURLPolicy.reduce(raw))
    }
}

/// Une URL observée est réduite à son origine et son chemin : ni
/// identifiants, ni paramètres, ni fragment. Ce qui suit `?` ou `#` porte
/// des jetons, des recherches et des identifiants de session ; ça n'entre
/// jamais dans la base.
public enum WindowURLPolicy {
    public static func reduce(_ raw: String) -> String? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        // Coupe d'abord au texte, pour ne pas dépendre du parseur quand la
        // requête contient des caractères qu'il refuse.
        let withoutFragment = trimmed.split(separator: "#", maxSplits: 1,
                                            omittingEmptySubsequences: false)[0]
        let withoutQuery = withoutFragment.split(separator: "?", maxSplits: 1,
                                                 omittingEmptySubsequences: false)[0]
        guard var components = URLComponents(string: String(withoutQuery)),
              let scheme = components.scheme, !scheme.isEmpty else {
            return nil
        }
        components.user = nil
        components.password = nil
        components.query = nil
        components.fragment = nil
        guard let reduced = components.string, reduced != "\(scheme):" else {
            return nil
        }
        return reduced
    }
}
