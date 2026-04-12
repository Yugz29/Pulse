import AppKit

private let startupExtensionHeight: CGFloat = 22

class NotchWindow: NSPanel {

    static let panelWidth:      CGFloat = 440
    static let dashboardHeight: CGFloat = 214
    static let chatHeight:      CGFloat = 212
    static let insightHeight:   CGFloat = 218
    static let settingsHeight:  CGFloat = 102
    static let statusHeight:    CGFloat = 188
    static let commandHeight:   CGFloat = 80
    static let bottomMargin:    CGFloat = 20

    var currentPanelHeight: CGFloat = NotchWindow.dashboardHeight
    var isExpanded: Bool = false { didSet { updateIgnoresMouseEvents() } }

    private var globalMonitor: Any?
    private var localMonitor:  Any?

    init() {
        guard let screen = NotchWindow.displayScreen() else { fatalError("Aucun écran trouvé") }
        let notchH = screen.safeAreaInsets.top
        let notchW = NotchWindow.realNotchWidth(for: screen)
        let rect   = NotchWindow.collapsedFrame(for: screen, notchHeight: notchH, notchWidth: notchW)

        super.init(contentRect: rect, styleMask: [.borderless, .nonactivatingPanel],
                   backing: .buffered, defer: false)

        isFloatingPanel            = true
        isOpaque                   = false
        backgroundColor            = .clear
        hasShadow                  = false
        isMovable                  = false
        titleVisibility            = .hidden
        titlebarAppearsTransparent = true
        isReleasedWhenClosed       = false
        level = NSWindow.Level(rawValue: Int(CGWindowLevelForKey(.mainMenuWindow)) + 3)
        collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary, .ignoresCycle]
        ignoresMouseEvents = true
        updateIgnoresMouseEvents()
        startTracking()
    }

    deinit { stopTracking() }
    override var canBecomeKey:  Bool { true }
    override var canBecomeMain: Bool { true }

    func expandToPanel() {
        guard let screen = currentDisplayScreen() else { return }
        setFrame(NotchWindow.expandedFrame(for: screen, panelHeight: currentPanelHeight), display: true)
    }

    func expandForStartup() {
        guard let screen = currentDisplayScreen() else { return }
        setFrame(NotchWindow.expandedFrame(for: screen, panelHeight: startupExtensionHeight), display: true)
    }

    func collapseToNotch() {
        guard let screen = currentDisplayScreen() else { return }
        let notchH = screen.safeAreaInsets.top
        let notchW = NotchWindow.realNotchWidth(for: screen)
        setFrame(NotchWindow.collapsedFrame(for: screen, notchHeight: notchH, notchWidth: notchW), display: true)
    }

    static func isFrontAppFullscreen() -> Bool {
        guard let screen = displayScreen() else { return false }
        return screen.frame.maxY - screen.visibleFrame.maxY < 5
            && screen.visibleFrame.height > screen.frame.height * 0.92
    }

    static func displayScreen() -> NSScreen? {
        let screens = NSScreen.screens
        if let notched = screens.first(where: { hasHardwareNotch(on: $0) }) { return notched }
        return NSScreen.main ?? screens.first
    }

    static func hasHardwareNotch(on screen: NSScreen) -> Bool {
        let left  = screen.auxiliaryTopLeftArea?.width  ?? 0
        let right = screen.auxiliaryTopRightArea?.width ?? 0
        return left > 0 && right > 0 && realNotchWidth(for: screen) > 0
    }

    static func realNotchWidth(for screen: NSScreen) -> CGFloat {
        let left  = screen.auxiliaryTopLeftArea?.width  ?? 0
        let right = screen.auxiliaryTopRightArea?.width ?? 0
        return screen.frame.width - left - right
    }

    private static func collapsedFrame(for screen: NSScreen, notchHeight: CGFloat, notchWidth: CGFloat) -> NSRect {
        let winW = max(NotchWindow.panelWidth + 40, notchWidth + 40)
        let winX = screen.frame.minX + (screen.frame.width - winW) / 2
        return NSRect(x: winX, y: screen.frame.maxY - notchHeight - NotchWindow.bottomMargin,
                      width: winW, height: notchHeight + NotchWindow.bottomMargin)
    }

    private static func expandedFrame(for screen: NSScreen, panelHeight: CGFloat) -> NSRect {
        let notchH = screen.safeAreaInsets.top
        let notchW = realNotchWidth(for: screen)
        let totalH = notchH + panelHeight + NotchWindow.bottomMargin
        let winW   = max(NotchWindow.panelWidth + 40, notchW + 40)
        let winX   = screen.frame.minX + (screen.frame.width - winW) / 2
        return NSRect(x: winX, y: screen.frame.maxY - totalH, width: winW, height: totalH)
    }

    private func currentDisplayScreen() -> NSScreen? {
        if let current = screen, NotchWindow.hasHardwareNotch(on: current) { return current }
        return NotchWindow.displayScreen()
    }

    private func startTracking() {
        let mask: NSEvent.EventTypeMask = [.mouseMoved, .leftMouseDragged, .rightMouseDragged]
        globalMonitor = NSEvent.addGlobalMonitorForEvents(matching: mask) { [weak self] _ in
            self?.updateIgnoresMouseEvents()
        }
        localMonitor = NSEvent.addLocalMonitorForEvents(matching: mask) { [weak self] event in
            self?.updateIgnoresMouseEvents(); return event
        }
    }

    private func stopTracking() {
        if let m = globalMonitor { NSEvent.removeMonitor(m); globalMonitor = nil }
        if let m = localMonitor  { NSEvent.removeMonitor(m); localMonitor = nil }
    }

    private func updateIgnoresMouseEvents() {
        let mouse  = NSEvent.mouseLocation
        let active = isExpanded ? panelScreenRect() : notchScreenRect()
        ignoresMouseEvents = !active.contains(mouse)
    }

    private func notchScreenRect() -> NSRect {
        guard let screen = currentDisplayScreen() else { return .zero }
        let notchW = NotchWindow.realNotchWidth(for: screen)
        let notchH = screen.safeAreaInsets.top
        return NSRect(x: screen.frame.minX + (screen.frame.width - notchW) / 2,
                      y: screen.frame.maxY - notchH, width: notchW, height: notchH)
    }

    private func panelScreenRect() -> NSRect {
        guard let screen = currentDisplayScreen() else { return .zero }
        let notchH = screen.safeAreaInsets.top
        let totalH = notchH + currentPanelHeight
        return NSRect(x: screen.frame.minX + (screen.frame.width - NotchWindow.panelWidth) / 2,
                      y: screen.frame.maxY - totalH, width: NotchWindow.panelWidth, height: totalH)
    }
}
