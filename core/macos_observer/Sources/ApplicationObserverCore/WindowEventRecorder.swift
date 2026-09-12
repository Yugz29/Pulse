import Foundation

/// Un `window_focused` par changement de contexte de fenêtre, deux fois
/// filtré :
///
/// - dédoublonnage sur la clé de comparaison (`WindowContext.Key`) : un
///   spinner qui tourne dans le titre n'est pas un nouveau contexte ;
/// - filet d'intervalle : au plus un événement par application toutes les
///   `minimumInterval` secondes. Un contexte arrivé trop tôt est **retenu**,
///   pas perdu : le dernier état retenu est émis quand l'intervalle est
///   écoulé (`flush`), ou dès que l'application quitte le premier plan
///   (`flush(force:)`). Rien n'est perdu, seuls les états intermédiaires
///   d'une même fenêtre en moins de `minimumInterval` sont regroupés.
public enum WindowRecordOutcome: Equatable, Sendable {
    case recorded
    case duplicate
    case held(retryAfter: TimeInterval)
}

public struct WindowDeduplicator: Sendable {
    private var lastKey: WindowContext.Key?

    public init() {}

    public func isDuplicate(_ context: WindowContext) -> Bool {
        lastKey == context.key
    }

    public mutating func record(_ context: WindowContext) {
        lastKey = context.key
    }

    /// Oublie la dernière fenêtre : la prochaine lecture identique est de
    /// nouveau un événement (retour depuis une application ignorée ou sans
    /// fenêtre).
    public mutating func forget() {
        lastKey = nil
    }
}

public struct WindowEventRecorder: Sendable {
    /// 30 s : sur une heure réelle de Claude Code dans Terminal (2 032
    /// lectures), la normalisation seule laisse 36 vrais changements de
    /// sous-commande, 30 s les ramène à 26 et 60 s à 20 ; 30 s est le plus
    /// petit filet sous le critère de 30 par heure, et un onglet tenu
    /// 30 secondes est toujours enregistré.
    public static let defaultMinimumInterval: TimeInterval = 30

    private let builder: CanonicalEventBuilder
    private let enqueue: @Sendable (Data) throws -> Void
    private let minimumInterval: TimeInterval
    private var deduplicator = WindowDeduplicator()
    private var lastEmittedAt: [String: Date] = [:]
    private var held: WindowContext?

    public init(
        builder: CanonicalEventBuilder,
        enqueue: @escaping @Sendable (Data) throws -> Void,
        minimumInterval: TimeInterval = WindowEventRecorder.defaultMinimumInterval
    ) {
        self.builder = builder
        self.enqueue = enqueue
        self.minimumInterval = minimumInterval
    }

    public var hasHeldContext: Bool {
        held != nil
    }

    @discardableResult
    public mutating func record(
        _ context: WindowContext,
        at now: Date = Date()
    ) throws -> WindowRecordOutcome {
        guard !deduplicator.isDuplicate(context) else {
            // Retour à l'état déjà émis : ce qui était retenu est caduc.
            held = nil
            return .duplicate
        }
        if let previous = lastEmittedAt[context.applicationKey] {
            let elapsed = now.timeIntervalSince(previous)
            if elapsed < minimumInterval {
                held = context
                return .held(retryAfter: minimumInterval - elapsed)
            }
        }
        try emit(context, at: now)
        return .recorded
    }

    /// Émet le contexte retenu si l'intervalle est écoulé, ou sans attendre
    /// avec `force` (l'application quitte le premier plan). Rend `true` si un
    /// événement est parti.
    @discardableResult
    public mutating func flush(at now: Date = Date(), force: Bool = false) throws -> Bool {
        guard let context = held else { return false }
        if !force, let previous = lastEmittedAt[context.applicationKey],
           now.timeIntervalSince(previous) < minimumInterval {
            return false
        }
        held = nil
        guard !deduplicator.isDuplicate(context) else { return false }
        try emit(context, at: now)
        return true
    }

    public mutating func forget() {
        deduplicator.forget()
        held = nil
    }

    private mutating func emit(_ context: WindowContext, at now: Date) throws {
        let payload = try builder.build(window: context, occurredAt: now)
        try enqueue(payload)
        deduplicator.record(context)
        lastEmittedAt[context.applicationKey] = now
        held = nil
    }
}
