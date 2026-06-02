import SwiftUI
import AppKit
import Combine
import Carbon.HIToolbox

@main
struct AppApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    var body: some Scene { Settings { EmptyView() } }
}

final class FirstMouseHostingView<Content: View>: NSHostingView<Content> {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}

class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {

    var notchWindow: NotchWindow?
    var vm: PulseViewModel!
    var observer: SystemObserver?
    private var cancellables = Set<AnyCancellable>()
    private let bridge = DaemonBridge()
    private var dashboardWindow: DashboardWindow?
    private var dashboardVM: DashboardViewModel?
    private var resumeThreadPanel: ResumeThreadPanelWindow?
    private var appleFoundationWorker: AppleFoundationWorker?
    private let accessibilityDiagnosticStore = AccessibilityContextProbeDiagnosticStore()
    private var contextHotKeyRef: EventHotKeyRef?
    private var focusedTextProbeHotKeyRef: EventHotKeyRef?
    private var accessibilityDiagnosticHotKeyRef: EventHotKeyRef?
    private var hotKeyHandlerRef: EventHandlerRef?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        vm = PulseViewModel(bridge: bridge)
        notchWindow = NotchWindow()

        let hostingView = FirstMouseHostingView(rootView: NotchRootView(vm: vm))
        hostingView.frame = notchWindow!.contentView!.bounds
        hostingView.autoresizingMask = [.width, .height]
        hostingView.wantsLayer = true
        hostingView.layer?.backgroundColor = CGColor(red: 0, green: 0, blue: 0, alpha: 0)
        notchWindow!.contentView = hostingView

        // Panel principal
        vm.$isExpanded
            .receive(on: RunLoop.main)
            .sink { [weak self] expanded in
                guard let self else { return }
                self.notchWindow?.isExpanded = expanded
                DispatchQueue.main.async {
                    if expanded {
                        self.notchWindow?.currentPanelHeight = self.vm.currentPanelHeight
                        self.notchWindow?.currentPanelWidth = self.vm.currentPanelWidth
                        self.notchWindow?.expandToPanel()
                    } else {
                        self.notchWindow?.collapseToNotch()
                    }
                }
            }
            .store(in: &cancellables)

        // Startup — redimensionne pour l'extension étroite de l'encoche
        vm.$isStartupExpanded
            .receive(on: RunLoop.main)
            .sink { [weak self] startupExpanded in
                guard let self, !self.vm.isExpanded else { return }
                DispatchQueue.main.async {
                    if startupExpanded {
                        self.notchWindow?.expandForStartup()
                    } else {
                        self.notchWindow?.collapseToNotch()
                    }
                }
            }
            .store(in: &cancellables)

        vm.$pendingCommand
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in
                guard let self, self.vm.isExpanded else { return }
                DispatchQueue.main.async {
                    self.notchWindow?.currentPanelHeight = self.vm.currentPanelHeight
                    self.notchWindow?.currentPanelWidth = self.vm.currentPanelWidth
                    self.notchWindow?.expandToPanel()
                }
            }
            .store(in: &cancellables)

        vm.$panelMode
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in
                guard let self, self.vm.isExpanded, self.vm.pendingCommand == nil else { return }
                DispatchQueue.main.async {
                    self.notchWindow?.currentPanelHeight = self.vm.currentPanelHeight
                    self.notchWindow?.currentPanelWidth = self.vm.currentPanelWidth
                    self.notchWindow?.expandToPanel()
                }
            }
            .store(in: &cancellables)

        vm.$activeResumeCard
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in
                guard let self, self.vm.isExpanded else { return }
                DispatchQueue.main.async {
                    self.notchWindow?.currentPanelHeight = self.vm.currentPanelHeight
                    self.notchWindow?.currentPanelWidth = self.vm.currentPanelWidth
                    self.notchWindow?.expandToPanel()
                }
            }
            .store(in: &cancellables)

        setupFullscreenDetection()
        registerGlobalShortcut()
        appleFoundationWorker = AppleFoundationWorker(bridge: bridge)
        appleFoundationWorker?.start()
        observer = SystemObserver()
        observer?.startObserving()
        vm.onObservationToggle = { [weak self] enabled in
            guard let self else { return }
            if enabled {
                if self.observer == nil {
                    self.observer = SystemObserver()
                }
                self.observer?.startObserving()
            } else {
                self.observer?.stopObserving()
            }
        }
        vm.onDaemonReconnected = { [weak self] in
            self?.observer?.refreshCurrentContext()
        }
        vm.onToggleDashboard = { [weak self] in
            self?.toggleDashboard()
        }
        vm.onShowResumeThreadPanel = { [weak self] in
            self?.toggleResumeThreadPanel()
        }
        notchWindow?.orderFrontRegardless()
    }

    private func setupFullscreenDetection() {
        NSWorkspace.shared.notificationCenter
            .publisher(for: NSWorkspace.activeSpaceDidChangeNotification)
            .merge(with: NotificationCenter.default.publisher(
                for: NSApplication.didChangeScreenParametersNotification))
            .debounce(for: .milliseconds(300), scheduler: RunLoop.main)
            .sink { [weak self] _ in self?.updateFullscreenState() }
            .store(in: &cancellables)

        NSWorkspace.shared.notificationCenter
            .publisher(for: NSWorkspace.didActivateApplicationNotification)
            .debounce(for: .milliseconds(200), scheduler: RunLoop.main)
            .sink { [weak self] _ in self?.updateFullscreenState() }
            .store(in: &cancellables)
    }

    private func updateFullscreenState() {
        let isFullscreen = NotchWindow.isFrontAppFullscreen()
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            if isFullscreen { self.notchWindow?.orderOut(nil) }
            else { self.notchWindow?.orderFrontRegardless() }
            self.vm.isFullscreen = isFullscreen
        }
    }

    private func registerGlobalShortcut() {
        var eventType = EventTypeSpec(
            eventClass: OSType(kEventClassKeyboard),
            eventKind: UInt32(kEventHotKeyPressed)
        )

        let handler: EventHandlerUPP = { _, eventRef, userData in
            guard let eventRef, let userData else { return noErr }

            var hotKeyID = EventHotKeyID()
            let status = GetEventParameter(
                eventRef,
                EventParamName(kEventParamDirectObject),
                EventParamType(typeEventHotKeyID),
                nil,
                MemoryLayout<EventHotKeyID>.size,
                nil,
                &hotKeyID
            )

            guard status == noErr else { return noErr }
            guard hotKeyID.signature == AppDelegate.hotKeySignature else { return noErr }

            let delegate = Unmanaged<AppDelegate>.fromOpaque(userData).takeUnretainedValue()
            switch hotKeyID.id {
            case AppDelegate.contextHotKeyID:
                delegate.copyContextSnapshot()
            case AppDelegate.focusedTextProbeHotKeyID:
                delegate.captureFocusedTextProbeFromShortcut()
            case AppDelegate.accessibilityDiagnosticHotKeyID:
                delegate.diagnoseFocusedElementFromShortcut()
            default:
                break
            }
            return noErr
        }

        InstallEventHandler(
            GetApplicationEventTarget(),
            handler,
            1,
            &eventType,
            UnsafeMutableRawPointer(Unmanaged.passUnretained(self).toOpaque()),
            &hotKeyHandlerRef
        )

        let contextHotKeyID = EventHotKeyID(
            signature: AppDelegate.hotKeySignature,
            id: AppDelegate.contextHotKeyID
        )

        RegisterEventHotKey(
            UInt32(kVK_ANSI_C),
            UInt32(cmdKey | optionKey | shiftKey),
            contextHotKeyID,
            GetApplicationEventTarget(),
            0,
            &contextHotKeyRef
        )

        let focusedTextProbeHotKeyID = EventHotKeyID(
            signature: AppDelegate.hotKeySignature,
            id: AppDelegate.focusedTextProbeHotKeyID
        )

        RegisterEventHotKey(
            UInt32(kVK_ANSI_P),
            UInt32(cmdKey | optionKey),
            focusedTextProbeHotKeyID,
            GetApplicationEventTarget(),
            0,
            &focusedTextProbeHotKeyRef
        )

        let accessibilityDiagnosticHotKeyID = EventHotKeyID(
            signature: AppDelegate.hotKeySignature,
            id: AppDelegate.accessibilityDiagnosticHotKeyID
        )

        RegisterEventHotKey(
            UInt32(kVK_ANSI_D),
            UInt32(cmdKey | optionKey),
            accessibilityDiagnosticHotKeyID,
            GetApplicationEventTarget(),
            0,
            &accessibilityDiagnosticHotKeyRef
        )
    }

    private func copyContextSnapshot() {
        Task {
            guard let context = try? await bridge.getContext(), !context.isEmpty else { return }
            let pb = NSPasteboard.general
            pb.clearContents()
            pb.setString(context, forType: .string)
            await MainActor.run {
                self.vm.showTransientStatus("Context copied")
            }
            print("[Pulse] Context snapshot copied to clipboard")
        }
    }

    private func captureFocusedTextProbeFromShortcut() {
        Task {
            guard let payload = await bridge.getContextProbeRequests(status: "approved", includeTerminal: false) else {
                print("[Pulse] Focused text probe shortcut ignored: daemon unavailable")
                return
            }
            guard let request = AccessibilityContextProbeShortcutHandler.approvedFocusedElementTextRequest(
                from: payload.requests
            ) else {
                print("[Pulse] Focused text probe shortcut ignored: no approved request")
                return
            }

            let capture: AccessibilityTextProbeCapture
            do {
                capture = try AccessibilityContextProbeService().captureFocusedText()
            } catch {
                print("[Pulse] Focused text probe shortcut failed: \(error)")
                return
            }

            guard let response = await bridge.submitContextProbeResult(request.requestId, capture: capture) else {
                print("[Pulse] Focused text probe shortcut submit failed")
                return
            }

            await MainActor.run {
                self.dashboardVM?.contextProbeResults[request.requestId] = response.result
            }
            await dashboardVM?.refreshContextProbeRequests()
            print("[Pulse] Focused text probe captured for request \(request.requestId)")
        }
    }

    private func diagnoseFocusedElementFromShortcut() {
        Task {
            let diagnostic: AccessibilityTextProbeDiagnostic
            do {
                diagnostic = try AccessibilityContextProbeService().diagnoseFocusedElement()
            } catch {
                diagnostic = AccessibilityTextProbeDiagnostic(
                    appName: "unknown",
                    bundleId: "unknown",
                    pid: 0,
                    axTrusted: AXIsProcessTrusted(),
                    focusedElementStatus: "error",
                    focusedRole: nil,
                    focusedSubrole: nil,
                    focusedRoleDescription: nil,
                    canReadSelectedText: false,
                    selectedTextLength: nil,
                    canReadValue: false,
                    valueLength: nil,
                    focusedWindowStatus: "error",
                    focusedWindowRole: nil,
                    focusedWindowTitleAvailable: false,
                    rejectionReason: "diagnostic_failed:\(error)",
                    isSecureField: false,
                    isWebArea: false,
                    treeSummary: nil
                )
            }
            await MainActor.run {
                self.accessibilityDiagnosticStore.record(diagnostic)
                self.dashboardVM?.setAccessibilityProbeDiagnostic(diagnostic)
            }
            print("[Pulse] AX diagnostic updated from shortcut")
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        appleFoundationWorker?.stop()
        observer?.stopObserving()
        dashboardVM?.stopPolling()
        if let contextHotKeyRef { UnregisterEventHotKey(contextHotKeyRef) }
        if let focusedTextProbeHotKeyRef { UnregisterEventHotKey(focusedTextProbeHotKeyRef) }
        if let accessibilityDiagnosticHotKeyRef { UnregisterEventHotKey(accessibilityDiagnosticHotKeyRef) }
        if let hotKeyHandlerRef { RemoveEventHandler(hotKeyHandlerRef) }
        cancellables.removeAll()
        notchWindow = nil
        dashboardWindow = nil
        resumeThreadPanel = nil
    }

    func windowWillClose(_ notification: Notification) {
        guard let window = notification.object as? NSWindow else { return }
        if window == dashboardWindow {
            dashboardVM?.stopPolling()
        }
        if window == resumeThreadPanel {
            resumeThreadPanel = nil
        }
    }

    @MainActor private func toggleResumeThreadPanel() {
        if resumeThreadPanel == nil {
            let panel = ResumeThreadPanelWindow()
            let hostingView = FirstMouseHostingView(rootView: ResumeThreadPanelView(
                vm: vm,
                onClose: { [weak self] in
                    self?.resumeThreadPanel?.orderOut(nil)
                }
            ))
            hostingView.frame = panel.contentView?.bounds ?? .zero
            hostingView.autoresizingMask = [.width, .height]
            hostingView.wantsLayer = true
            hostingView.layer?.backgroundColor = CGColor(red: 0, green: 0, blue: 0, alpha: 0)
            if let containerView = panel.contentView {
                containerView.addSubview(hostingView)
            } else {
                panel.contentView = hostingView
            }
            panel.delegate = self
            resumeThreadPanel = panel
        }

        guard let panel = resumeThreadPanel else { return }
        if panel.isVisible {
            panel.orderOut(nil)
            return
        }

        panel.positionNearNotch(on: notchWindow?.screen, below: notchWindow?.frame)
        panel.orderFrontRegardless()
    }

    @MainActor private func toggleDashboard() {
        if dashboardWindow == nil {
            let vm = DashboardViewModel(
                bridge: bridge,
                appleFoundationStatusProvider: { [weak self] in
                    await self?.appleFoundationWorker?.status()
                }
            )
            vm.setAccessibilityProbeDiagnostic(accessibilityDiagnosticStore.latestDiagnostic)
            dashboardVM = vm

            let window = DashboardWindow()
            let hostingView = NSHostingView(rootView: DashboardRootView(vm: vm))
            hostingView.frame = window.contentView?.bounds ?? .zero
            hostingView.autoresizingMask = [.width, .height]
            if let containerView = window.contentView {
                containerView.addSubview(hostingView)
            } else {
                window.contentView = hostingView
            }
            window.delegate = self
            dashboardWindow = window
        }

        guard let window = dashboardWindow else { return }

        if window.isVisible {
            window.orderOut(nil)
            dashboardVM?.stopPolling()
        } else {
            vm.isExpanded = false
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            Task { await dashboardVM?.refresh() }
            dashboardVM?.startPolling()
        }
    }

    private static let hotKeySignature: OSType = 0x50554C53 // 'PULS'
    private static let contextHotKeyID: UInt32 = 1
    private static let focusedTextProbeHotKeyID: UInt32 = 2
    private static let accessibilityDiagnosticHotKeyID: UInt32 = 3
}
