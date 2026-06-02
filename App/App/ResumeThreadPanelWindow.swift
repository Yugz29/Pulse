import AppKit

final class ResumeThreadPanelWindow: NSPanel {
    static let panelSize = NSSize(width: 520, height: 388)
    private static let verticalGapBelowNotch: CGFloat = 18

    init() {
        super.init(
            contentRect: NSRect(origin: .zero, size: Self.panelSize),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )

        isFloatingPanel = true
        isOpaque = false
        backgroundColor = .clear
        hasShadow = true
        isMovable = true
        isMovableByWindowBackground = true
        minSize = Self.panelSize
        maxSize = Self.panelSize
        titleVisibility = .hidden
        titlebarAppearsTransparent = true
        isReleasedWhenClosed = false
        level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.mainMenuWindow)) + 4)
        collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary, .ignoresCycle]

        let effect = NSVisualEffectView()
        effect.material = .hudWindow
        effect.blendingMode = .behindWindow
        effect.state = .active
        effect.autoresizingMask = [.width, .height]
        effect.wantsLayer = true
        effect.layer?.cornerRadius = 18
        effect.layer?.masksToBounds = true
        contentView = effect
    }

    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }

    func positionNearNotch(on screen: NSScreen?, below notchFrame: NSRect? = nil) {
        let targetScreen = screen ?? NotchWindow.displayScreen() ?? NSScreen.main
        guard let targetScreen else { return }

        let size = Self.panelSize
        let anchorX = notchFrame?.midX ?? targetScreen.frame.midX
        let unclampedX = anchorX - size.width / 2
        let x = min(
            max(unclampedX, targetScreen.visibleFrame.minX + 16),
            targetScreen.visibleFrame.maxX - size.width - 16
        )

        let y: CGFloat
        if let notchFrame {
            y = max(
                targetScreen.visibleFrame.minY + 24,
                notchFrame.minY - Self.verticalGapBelowNotch - size.height
            )
        } else {
            y = targetScreen.frame.maxY
                - targetScreen.safeAreaInsets.top
                - NotchWindow.bottomMargin
                - Self.verticalGapBelowNotch
                - size.height
        }
        setFrame(NSRect(x: x, y: y, width: size.width, height: size.height), display: true)
    }
}
