import Foundation

/// Lignes du journal de l'observateur, chacune datée en ISO 8601, heure
/// locale avec décalage (`2026-09-11T20:48:19+02:00 message`). Sans date,
/// un « Fatal access conflict detected » ou une notification de verrou
/// ne se situent ni par rapport à un redémarrage ni entre eux.
public enum ObserverLog {
    public static func line(
        _ message: String,
        at date: Date = Date(),
        timeZone: TimeZone = .current
    ) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        formatter.timeZone = timeZone
        return "\(formatter.string(from: date)) \(message)\n"
    }

    /// Écrit une ligne datée sur stderr, le journal que launchd capture.
    public static func write(_ message: String) {
        FileHandle.standardError.write(Data(line(message).utf8))
    }
}
