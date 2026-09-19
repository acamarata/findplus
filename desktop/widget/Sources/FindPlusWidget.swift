// FindPlusWidget.swift
//
// Purpose    : @main WidgetBundle entry point for the Find+ widget extension.
// Inputs     : None directly; each Widget supplies its own TimelineProvider.
// Outputs    : Registers StatusWidget (and, in 1.0, the stub PlacesWidget)
//              with WidgetKit.
// Constraints: T1 stub only — T2 swaps EmptyProvider/SimpleEntry for
//              FindPlusProvider/WidgetEntry; T3 swaps the stub view for the
//              real per-family views.

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

struct PlacesWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "FindPlusPlaces", provider: EmptyProvider()) { _ in
            Text("Stub")
        }
    }
}

struct SimpleEntry: TimelineEntry {
    let date: Date
}

struct EmptyProvider: TimelineProvider {
    func placeholder(in context: Context) -> SimpleEntry {
        SimpleEntry(date: Date())
    }

    func getSnapshot(in context: Context, completion: @escaping (SimpleEntry) -> Void) {
        completion(SimpleEntry(date: Date()))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<SimpleEntry>) -> Void) {
        completion(Timeline(entries: [SimpleEntry(date: Date())], policy: .atEnd))
    }
}
