// SmallView.swift
//
// Purpose    : systemSmall widget layout — dot, state, tracked count, age
//              of the newest fix, footer notice.
// Inputs     : WidgetEntry.
// Outputs    : A SwiftUI View for the small widget family.
// Constraints: Locked/Down states show no device data, per widget.md
//              § Behaviour. Footer always renders response.notice (falling
//              back to the pinned sentence only when response is nil).

import SwiftUI
import WidgetKit

struct SmallView: View {
    let entry: WidgetEntry

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if entry.state == .locked {
                Image(systemName: "lock.fill")
                Text("Locked")
            } else if entry.state == .down {
                Text("Find+ is not running")
            } else {
                HStack {
                    Circle().fill(dotColour(entry.state)).frame(width: 10, height: 10)
                    Text(stateLabel(entry.state)).font(.headline)
                }
                Text("\(entry.response?.tracked_count ?? 0) tracked")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                if let device = entry.response?.devices.first {
                    Text(formatAge(minutes: device.age_minutes))
                        .font(.caption)
                        .foregroundStyle(
                            device.isStale(after: entry.staleAfterMinutes)
                                ? Color.dotGrey : .primary
                        )
                }
                Button(intent: PollNowIntent()) {
                    Label("Poll now", systemImage: "arrow.clockwise")
                }
                .disabled(entry.state == .locked || entry.state == .down)
                Button(intent: OpenFindPlusIntent()) {
                    Label("Open", systemImage: "arrow.up.right.square")
                }
            }
            Spacer()
            NoticeFooter(entry: entry)
        }
    }
}
