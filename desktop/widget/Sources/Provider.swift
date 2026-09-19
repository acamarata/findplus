// Provider.swift
//
// Purpose    : TimelineProvider that fetches GET /api/widget over loopback
//              and maps the response onto the five widget entry states.
// Inputs     : http://127.0.0.1:8647/api/widget (3 s request timeout).
// Outputs    : WidgetEntry (ok/stale/error from the API; locked on HTTP 401;
//              down on any URLError).
// Constraints: Foundation + WidgetKit only — no AppKit, no findplus Python
//              modules. fetch() is async, bridged to the completion-based
//              TimelineProvider API via Task {}.

import Foundation
import WidgetKit

struct FindPlusProvider: TimelineProvider {
    typealias Entry = WidgetEntry

    /// Injectable so ProviderTests can register a URLProtocol stub; the
    /// default preserves the widget's real production behaviour.
    var configuration: URLSessionConfiguration = .default

    func placeholder(in context: Context) -> WidgetEntry {
        let response = WidgetResponse(
            state: .ok,
            version: "1.0",
            last_poll_at: nil,
            next_poll_at: nil,
            tracked_count: 3,
            devices: [],
            groups: [],
            show_map: false,
            notice: "Locations can be minutes to hours late."
        )
        return WidgetEntry(date: Date(), response: response, state: .ok, errorMessage: nil)
    }

    func getSnapshot(in context: Context, completion: @escaping (WidgetEntry) -> Void) {
        Task { completion(await fetch()) }
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<WidgetEntry>) -> Void) {
        Task {
            let entry = await fetch()
            completion(Timeline(entries: [entry], policy: .after(Self.nextReloadDate())))
        }
    }

    /// 15 minutes from `now` — the timeline reload policy. A separate pure
    /// function (not inlined into getTimeline) because WidgetKit's
    /// TimelineProviderContext has no accessible initializer, so
    /// ProviderTests cannot call getTimeline(in:completion:) directly; this
    /// is what ProviderTests exercises instead.
    static func nextReloadDate(from now: Date = Date()) -> Date {
        Calendar.current.date(byAdding: .minute, value: 15, to: now) ?? now
    }

    /// Internal (not private) so @testable ProviderTests, in a different
    /// file, can call it directly — Swift's `private` is file-scoped even
    /// under @testable import.
    func fetch() async -> WidgetEntry {
        guard let url = URL(string: "http://127.0.0.1:8647/api/widget") else {
            return WidgetEntry(date: Date(), response: nil, state: .down, errorMessage: "Find+ is not running")
        }
        configuration.timeoutIntervalForRequest = 3.0
        let session = URLSession(configuration: configuration)

        do {
            let (data, response) = try await session.data(from: url)
            if let http = response as? HTTPURLResponse, http.statusCode == 401 {
                return WidgetEntry(date: Date(), response: nil, state: .locked, errorMessage: nil)
            }
            let decoded = try JSONDecoder().decode(WidgetResponse.self, from: data)
            return WidgetEntry(date: Date(), response: decoded, state: decoded.state, errorMessage: nil)
        } catch is URLError {
            return WidgetEntry(date: Date(), response: nil, state: .down, errorMessage: "Find+ is not running")
        } catch {
            return WidgetEntry(date: Date(), response: nil, state: .error, errorMessage: error.localizedDescription)
        }
    }
}
