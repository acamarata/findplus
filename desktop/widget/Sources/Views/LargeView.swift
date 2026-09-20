// LargeView.swift
//
// Purpose    : systemLarge widget layout — Medium plus group verdicts and
//              an optional map snapshot of the newest fix.
// Inputs     : WidgetEntry.
// Outputs    : A SwiftUI View for the large widget family; MapSnapshotView
//              (a separate MKMapSnapshotter-backed view) when show_map.
// Constraints: Map code is gated on @available(macOS 14.0, *) and falls
//              back to a grey box on any snapshot failure, per widget.md
//              § Behaviour "falls back to no map on failure".

import MapKit
import SwiftUI
import WidgetKit

struct LargeView: View {
    let entry: WidgetEntry

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            MediumView(entry: entry, embedded: true)
            ForEach(entry.response?.groups ?? [], id: \.id) { g in
                HStack {
                    Text(g.displayVerdict).bold()
                    Text(g.note).foregroundStyle(.secondary)
                }
                .font(.caption)
            }
            // A stale device's place column already reads "unknown", but the map
            // kept drawing its last known fix beside it, and the picture outranks
            // the words (CF-12). Suppress the map instead of captioning it: an
            // overlay still shows a location that reads as current.
            if entry.response?.show_map == true,
               let device = entry.response?.devices.first,
               !device.isStale(after: entry.staleAfterMinutes) {
                MapSnapshotView(latitude: device.latitude, longitude: device.longitude)
                    .frame(width: 200, height: 120)
            }
            HStack {
                if entry.state != .down {
                    Button(intent: PollNowIntent()) {
                        Label("Poll now", systemImage: "arrow.clockwise")
                    }
                    .disabled(entry.state == .locked || entry.state == .down)
                }
                Button(intent: OpenFindPlusIntent()) {
                    Label("Open", systemImage: "arrow.up.right.square")
                }
            }
            Spacer()
            NoticeFooter(entry: entry)
        }
    }
}

@available(macOS 14.0, *)
struct MapSnapshotView: View {
    let latitude: Double
    let longitude: Double
    @State private var image: Image?
    @State private var failed = false

    var body: some View {
        Group {
            if let image {
                image.resizable().scaledToFill()
            } else if failed {
                Rectangle().fill(Color.dotGrey.opacity(0.3))
            } else {
                Rectangle().fill(Color.dotGrey.opacity(0.15))
            }
        }
        .task(id: "\(latitude),\(longitude)") { await render() }
    }

    private func render() async {
        let options = MKMapSnapshotter.Options()
        options.region = MKCoordinateRegion(
            center: CLLocationCoordinate2D(latitude: latitude, longitude: longitude),
            latitudinalMeters: 1500,
            longitudinalMeters: 1500
        )
        options.size = CGSize(width: 200, height: 120)
        let snapshotter = MKMapSnapshotter(options: options)
        do {
            let snapshot = try await snapshotter.start()
            image = Image(nsImage: snapshot.image)
        } catch {
            failed = true
        }
    }
}
