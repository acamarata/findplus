// PlacesMediumView.swift
//
// Purpose    : systemMedium layout for the Places widget — up to four saved
//              places, each with its name, occupant badges (or "Nobody
//              here"), and the last presence change time.
// Inputs     : WidgetEntry (same feed as StatusWidget).
// Outputs    : A SwiftUI View for the medium Places widget family.
// Constraints: Locked/Down states show no place data, matching every other
//              widget family's rule (widget.md § Behaviour). `device_ids`
//              in a WidgetPlace already excludes members of any badged
//              group (api/_widget.py), so this view never double-badges.

import SwiftUI
import WidgetKit

struct PlacesMediumView: View {
    let entry: WidgetEntry

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if entry.state == .locked {
                HStack {
                    Image(systemName: "lock.fill")
                    Text("Locked")
                }
            } else if entry.state == .down {
                Text("Find+ is not running")
            } else {
                let places = Array((entry.response?.places ?? []).prefix(4))
                if places.isEmpty {
                    Text("No places yet").font(.caption).foregroundStyle(.secondary)
                } else {
                    ForEach(places, id: \.id) { place in
                        placeRow(place)
                    }
                }
            }
            Spacer()
            NoticeFooter(entry: entry)
        }
    }

    private func placeRow(_ place: WidgetPlace) -> some View {
        HStack(alignment: .top) {
            Text(place.name).font(.caption).bold().frame(width: 70, alignment: .leading)
            occupancy(place)
            Spacer()
            if let minutes = minutesSince(place.last_change_at) {
                Text(formatAge(minutes: minutes)).font(.caption2).foregroundStyle(.secondary)
            }
        }
    }

    private func occupancy(_ place: WidgetPlace) -> some View {
        HStack(spacing: 4) {
            if place.device_ids.isEmpty && place.group_ids.isEmpty {
                Text("Nobody here").font(.caption2).foregroundStyle(.secondary)
            } else {
                ForEach(place.group_ids, id: \.self) { gid in
                    if let group = entry.response?.group(id: gid) {
                        // WidgetGroup carries no `color` (api/_widget.py's
                        // _group_rows never served one, matching every other
                        // group badge in this widget extension) -- .primary,
                        // not a fabricated tint.
                        Image(systemName: sfSymbol(for: group.icon, label: nil, name: group.name))
                            .foregroundStyle(.primary)
                    }
                }
                ForEach(place.device_ids, id: \.self) { did in
                    if let device = entry.response?.device(id: did) {
                        Image(systemName: sfSymbol(for: device.icon, label: nil, name: device.name))
                            .foregroundStyle(Color(hex: device.color))
                    }
                }
            }
        }
        .font(.caption2)
    }
}
