import AppKit
import SwiftUI

struct ResumeThreadPanelView: View {
    @ObservedObject var vm: PulseViewModel
    let onClose: () -> Void

    private var snapshot: ResumeThreadPanelSnapshot {
        ResumeThreadPanelSnapshot(vm: vm)
    }

    var body: some View {
        let snapshot = snapshot

        ScrollView(showsIndicators: false) {
            VStack(alignment: .leading, spacing: 18) {
                HStack(alignment: .top, spacing: 12) {
                    VStack(alignment: .leading, spacing: 5) {
                        Text(snapshot.title)
                            .font(.system(size: 20, weight: .bold, design: .rounded))
                            .foregroundColor(.white.opacity(0.92))
                        Text("Comment je reprends le fil ?")
                            .font(.system(size: 12, weight: .medium))
                            .foregroundColor(.white.opacity(0.46))
                    }
                    .overlay(ResumeThreadPanelDragHandle())

                    Spacer()

                    Button(action: onClose) {
                        Image(systemName: "xmark")
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundColor(.white.opacity(0.58))
                            .frame(width: 26, height: 26)
                            .background(Color.white.opacity(0.07))
                            .clipShape(Circle())
                    }
                    .buttonStyle(.plain)
                }

                section(
                    "Maintenant",
                    icon: "waveform.path.ecg",
                    lines: [
                        snapshot.contextLine,
                        snapshot.fileLine,
                        "\(snapshot.taskLine) · \(snapshot.sessionLine) · \(snapshot.focusLine)",
                    ],
                    accent: Color(hex: "#5DCAA5")
                )

                HStack(alignment: .top, spacing: 12) {
                    section(
                        "Dernier signal",
                        icon: "bell",
                        lines: [snapshot.lastSignalTitle, snapshot.lastSignalDetail],
                        accent: Color(hex: "#5E9EFF")
                    )

                    section(
                        "Pourquoi",
                        icon: "checkmark.seal",
                        lines: [snapshot.whyLine],
                        accent: Color(hex: "#EF9F27")
                    )
                }

                section(
                    "À reprendre",
                    icon: "arrow.clockwise.circle",
                    lines: [snapshot.nextActionLine],
                    accent: Color(hex: "#8B5CF6"),
                    isEmphasized: true
                )
            }
            .padding(.top, 22)
            .padding(.horizontal, 22)
            .padding(.bottom, 30)
        }
        .frame(width: 520, height: 388, alignment: .topLeading)
        .background(Color.black.opacity(0.28))
    }

    private func section(
        _ title: String,
        icon: String,
        lines: [String],
        accent: Color,
        isEmphasized: Bool = false
    ) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 7) {
                Image(systemName: icon)
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundColor(accent)
                Text(title)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundColor(.white.opacity(0.38))
                    .textCase(.uppercase)
            }

            VStack(alignment: .leading, spacing: 4) {
                ForEach(Array(lines.enumerated()), id: \.offset) { index, line in
                    let expandedText = title == "Pourquoi" || isEmphasized
                    Text(line)
                        .font(.system(size: index == 0 || isEmphasized ? 12 : 11, weight: index == 0 || isEmphasized ? .semibold : .regular))
                        .foregroundColor(.white.opacity(index == 0 || isEmphasized ? 0.80 : 0.48))
                        .lineLimit(expandedText ? 3 : 2)
                        .truncationMode(.middle)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Color.white.opacity(isEmphasized ? 0.075 : 0.045))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(accent.opacity(isEmphasized ? 0.18 : 0.10), lineWidth: 0.8)
        )
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

private struct ResumeThreadPanelDragHandle: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView {
        DragHandleView()
    }

    func updateNSView(_ nsView: NSView, context: Context) {}

    private final class DragHandleView: NSView {
        override var mouseDownCanMoveWindow: Bool { true }
        override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

        override func mouseDown(with event: NSEvent) {
            window?.performDrag(with: event)
        }
    }
}
