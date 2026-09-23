// PlacesWidget.swift
//
// Purpose    : The second widget kind (E13 seed, deferred from 1.0, shipped
//              1.1): who is at each saved place right now. Registered in
//              FindPlusWidgetBundle alongside StatusWidget.
// Inputs     : The same GET /api/widget feed as StatusWidget — FindPlusProvider
//              is reused unchanged so the two widgets never disagree about
//              state/lock/down.
// Outputs    : PlacesWidgetView, switching on family between the small and
//              medium layouts (Views/PlacesSmallView.swift,
//              Views/PlacesMediumView.swift). No large family: a place list
//              has nothing further to add at that size that medium does not
//              already show.
// Constraints: Provider.swift is owned by a concurrent port-source fix this
//              ticket does not touch (see Model.swift's `places` default);
//              this widget reuses FindPlusProvider exactly as it stands.

import SwiftUI
import WidgetKit

struct PlacesWidget: Widget {
    let kind: String = "FindPlusPlaces"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: FindPlusProvider()) { entry in
            PlacesWidgetView(entry: entry)
        }
        .configurationDisplayName("Find+ Places")
        .description("Shows who is at each saved place.")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

struct PlacesWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: WidgetEntry

    var body: some View {
        Group {
            switch family {
            case .systemMedium:
                PlacesMediumView(entry: entry)
            default:
                PlacesSmallView(entry: entry)
            }
        }
        // Tapping anywhere on the widget opens the dashboard's Places tab
        // (urlscheme.rs's "findplus://places" -> windows::open_places).
        .widgetURL(URL(string: "findplus://places"))
    }
}
