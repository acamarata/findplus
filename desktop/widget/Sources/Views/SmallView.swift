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
                // widget.md § Behaviour: "Down shows 'Find+ is not running'
                // and the Open intent" — without it a stopped daemon leaves
                // the widget with no way back into the app.
                Button(intent: OpenFindPlusIntent()) {
                    Label("Open", systemImage: "arrow.up.right.square")
                }
            } else {
                HStack {
                    Circle().fill(dotColour(entry.state)).frame(width: 10, height: 10)
                    Text(stateLabel(entry.state)).font(.headline)
                }
                Text("\(entry.response?.tracked_count ?? 0) tracked")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                if let device = entry.response?.devices.first {
                    // The age line is the only thing small says about a
                    // specific device, so the icon rides with it rather than
                    // costing a name row the frame has no space for.
                    HStack(spacing: 4) {
                        Image(systemName: sfSymbol(for: device.icon, label: device.label, name: device.name))
                            .foregroundStyle(Color(hex: device.color))
                        Text(formatAge(minutes: device.age_minutes))
                            .font(.caption)
                            .foregroundStyle(
                                device.isStale(after: entry.staleAfterMinutes)
                                    ? Color.dotGrey : .primary
                            )
                    }
                }
                // No buttons in systemSmall (CF-13): the frame already carries the
                // dot line, count, age and the footer notice. Poll now / Open stay
                // on the medium and large families. The Down branch above keeps its
                // Open intent, which widget.md's Behaviour section pins for every
                // family.
            }
            Spacer()
            NoticeFooter(entry: entry)
        }
    }
}
