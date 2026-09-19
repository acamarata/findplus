// FindPlusWidget.swift
//
// Purpose    : @main WidgetBundle entry point for the Find+ widget extension.
// Inputs     : None directly; StatusWidget supplies its own TimelineProvider.
// Outputs    : Registers StatusWidget with WidgetKit.
// Constraints: PlacesWidget is deferred to 1.1 (ruling 2026-09-19) — 1.0 ships
//              one widget only; a stub must never ship in the gallery.

import SwiftUI
import WidgetKit

@main
struct FindPlusWidgetBundle: WidgetBundle {
    var body: some Widget {
        StatusWidget()
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
