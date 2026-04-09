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

class AppDelegate: NSObject, NSApplicationDelegate {

    var notchWindow: NotchWindow?
    var vm: PulseViewModel!
    var observer: SystemObserver?
    private var cancellables = Set<AnyCancellable>()
    private let bridge = DaemonBridge()
    private var hotKeyRef: EventHotKeyRef?
    private var hotKeyHandlerRef: EventHandlerRef?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        vm = PulseViewModel()
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
                    self.notchWindow?.expandToPanel()
                }
            }
            .store(in: &cancellables)

        setupFullscreenDetection()
        registerGlobalShortcut()
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
            guard hotKeyID.id == AppDelegate.hotKeyID else { return noErr }

            let delegate = Unmanaged<AppDelegate>.fromOpaque(userData).takeUnretainedValue()
            delegate.copyContextSnapshot()
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

        let hotKeyID = EventHotKeyID(
            signature: AppDelegate.hotKeySignature,
            id: AppDelegate.hotKeyID
        )

        RegisterEventHotKey(
            UInt32(kVK_ANSI_C),
            UInt32(cmdKey | optionKey | shiftKey),
            hotKeyID,
            GetApplicationEventTarget(),
            0,
            &hotKeyRef
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

    func applicationWillTerminate(_ notification: Notification) {
        observer?.stopObserving()
        if let hotKeyRef { UnregisterEventHotKey(hotKeyRef) }
        if let hotKeyHandlerRef { RemoveEventHandler(hotKeyHandlerRef) }
        cancellables.removeAll()
        notchWindow = nil
    }

    private static let hotKeySignature: OSType = 0x50554C53 // 'PULS'
    private static let hotKeyID: UInt32 = 1
}
