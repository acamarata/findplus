// PlacesSmallView.swift
//
// Purpose    : systemSmall layout for the Places widget — up to two saved
//              places, each with its name and occupant badges (or "Nobody
//              here").
// Inputs     : WidgetEntry (same feed as StatusWidget).
// Outputs    : A SwiftUI View for the small Places widget family.
// Constraints: Locked/Down states show no place data (widget.md § Behaviour,
//              the same rule every other widget family follows). No last-
//              change time here: the frame has room for the name and the
//              badge row only, same trade StatusWidget's SmallView makes.

import SwiftUI
import WidgetKit

struct PlacesSmallView: View {
    let entry: WidgetEntry

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if entry.state == .locked {
                Image(systemName: "lock.fill")
                Text("Locked")
            } else if entry.state == .down {
                Text("Find+ is not running")
            } else {
                let places = Array((entry.response?.places ?? []).prefix(2))
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
        VStack(alignment: .leading, spacing: 1) {
            Text(place.name).font(.caption).bold()
            if place.device_ids.isEmpty && place.group_ids.isEmpty {
                Text("Nobody here").font(.caption2).foregroundStyle(.secondary)
            } else {
                HStack(spacing: 3) {
                    ForEach(place.group_ids, id: \.self) { gid in
                        if let group = entry.response?.group(id: gid) {
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
                .font(.caption2)
            }
        }
    }
}
