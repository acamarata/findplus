// FindPlusWidget.swift
//
// Purpose    : @main WidgetBundle entry point for the Find+ widget extension.
// Inputs     : None directly; StatusWidget/PlacesWidget each supply their own
//              TimelineProvider (both reuse FindPlusProvider — see
//              PlacesWidget.swift).
// Outputs    : Registers StatusWidget and PlacesWidget with WidgetKit.
// Constraints: PlacesWidget shipped 1.1 (deferred from 1.0 by the 2026-09-19
//              ruling, which required 1.0 ship one widget only and forbade a
//              gallery stub — that deferral ends here).

import SwiftUI
import WidgetKit

@main
struct FindPlusWidgetBundle: WidgetBundle {
    var body: some Widget {
        StatusWidget()
        PlacesWidget()
    }
}

struct StatusWidget: Widget {
    let kind: String = "FindPlusStatus"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: FindPlusProvider()) { entry in
            FindPlusWidgetView(entry: entry)
        }
        .configurationDisplayName("Find+")
        .description("Shows tracker status.")
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge])
    }
}

struct FindPlusWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: WidgetEntry

    var body: some View {
        switch family {
        case .systemMedium:
            MediumView(entry: entry)
        case .systemLarge:
            LargeView(entry: entry)
        default:
            SmallView(entry: entry)
        }
    }
}
