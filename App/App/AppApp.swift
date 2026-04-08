import SwiftUI
import AppKit
import Combine

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

        setupFullscreenDetection()
        observer = SystemObserver()
        observer?.startObserving()
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

    func applicationWillTerminate(_ notification: Notification) {
        observer?.stopObserving()
        cancellables.removeAll()
        notchWindow = nil
    }
}
