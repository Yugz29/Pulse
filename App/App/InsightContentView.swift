import SwiftUI

struct InsightView: View {
    @ObservedObject var vm: PulseViewModel
    private let eventLimit = 25
    private let proposalLimit = 4

    private var visibleEvents: [InsightEvent] {
        Array(vm.recentEvents.suffix(eventLimit).reversed())
    }

    private var visibleProposals: [ProposalRecord] {
        Array(vm.recentProposals.prefix(proposalLimit))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 8) {
                if visibleProposals.isEmpty && visibleEvents.isEmpty {
                    HStack {
                        Spacer()
                        Text("Aucune activité ni proposition récente")
                            .font(.system(size: 11))
                            .foregroundColor(.white.opacity(0.22))
                        Spacer()
                    }
                    .padding(.top, 16)
                } else {
                    ScrollView(.vertical, showsIndicators: false) {
                        VStack(alignment: .leading, spacing: 0) {
                            if !visibleProposals.isEmpty {
                                sectionHeaderRow("Propositions récentes", count: visibleProposals.count)
                                    .padding(.horizontal, 18)
                                    .padding(.top, 10)

                                VStack(spacing: 0) {
                                    ForEach(visibleProposals) { proposal in
                                        proposalRow(proposal)
                                        if proposal.id != visibleProposals.last?.id {
                                            Divider().background(Color.white.opacity(0.05))
                                        }
                                    }
                                }
                                .padding(.horizontal, 18)
                            }

                            if !visibleEvents.isEmpty {
                                if !visibleProposals.isEmpty {
                                    Divider().background(Color.white.opacity(0.05))
                                }
                                sectionHeaderRow("Activité récente", count: visibleEvents.count)
                                    .padding(.horizontal, 18)
                                    .padding(.top, visibleProposals.isEmpty ? 10 : 8)

                                VStack(spacing: 0) {
                                    ForEach(visibleEvents) { event in
                                        activityRow(event)
                                        if event.id != visibleEvents.last?.id {
                                            Divider().background(Color.white.opacity(0.05))
                                        }
                                    }
                                }
                                .padding(.horizontal, 18)
                            }
                        }
                    }
                }
            }
        }
        .frame(height: NotchWindow.insightHeight - .panelContentGap, alignment: .top)
        .onAppear { vm.refreshInsights() }
    }

    private func sectionHeaderRow(_ title: String, count: Int) -> some View {
        HStack {
            sectionHeader(title)
            Spacer()
            Text("\(count) visible\(count > 1 ? "s" : "")")
                .font(.system(size: 9, weight: .semibold))
                .foregroundColor(.white.opacity(0.30))
        }
    }

    private func sectionHeader(_ title: String) -> some View {
        Text(title)
            .font(.system(size: 10, weight: .semibold))
            .foregroundColor(.white.opacity(0.34))
            .tracking(0.4)
    }

    private func activityRow(_ event: InsightEvent) -> some View {
        HStack(alignment: .top, spacing: 10) {
            ZStack {
                Circle()
                    .fill(Color(hex: event.accentHex).opacity(0.18))
                    .frame(width: 24, height: 24)
                Image(systemName: event.iconName)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundColor(Color(hex: event.accentHex))
            }

            VStack(alignment: .leading, spacing: 3) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(event.primaryText)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundColor(.white.opacity(0.78))
                        .lineLimit(1)
                        .truncationMode(.middle)

                    Spacer(minLength: 8)

                    Text(event.timeLabel)
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundColor(.white.opacity(0.58))
                        .padding(.horizontal, 6)
                        .padding(.vertical, 3)
                        .background(Color.white.opacity(0.06))
                        .clipShape(Capsule())
                }

                Text("\(event.secondaryText) · \(event.relativeTimeLabel)")
                    .font(.system(size: 10))
                    .foregroundColor(.white.opacity(0.36))
                    .lineLimit(1)
            }
        }
        .padding(.vertical, 8)
    }

    private func proposalRow(_ proposal: ProposalRecord) -> some View {
        HStack(alignment: .top, spacing: 10) {
            ZStack {
                Circle()
                    .fill(Color(hex: proposal.statusAccentHex).opacity(0.18))
                    .frame(width: 24, height: 24)
                Circle()
                    .fill(Color(hex: proposal.statusAccentHex))
                    .frame(width: 8, height: 8)
            }

            VStack(alignment: .leading, spacing: 3) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(proposal.displayTitle)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundColor(.white.opacity(0.78))
                        .lineLimit(1)
                        .truncationMode(.tail)

                    Spacer(minLength: 8)

                    Text(proposal.statusLabel)
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundColor(Color(hex: proposal.statusAccentHex))
                        .padding(.horizontal, 6)
                        .padding(.vertical, 3)
                        .background(Color(hex: proposal.statusAccentHex).opacity(0.10))
                        .clipShape(Capsule())
                }

                Text("\(proposal.typeLabel) · \(proposal.flowLabel) · \(proposal.relativeTimeLabel)")
                    .font(.system(size: 10))
                    .foregroundColor(.white.opacity(0.36))
                    .lineLimit(1)

                if let detail = proposal.detailText {
                    Text(detail)
                        .font(.system(size: 10))
                        .foregroundColor(.white.opacity(0.52))
                        .lineLimit(2)
                }
            }
        }
        .padding(.vertical, 8)
    }
}
