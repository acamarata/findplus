// Model.swift
//
// Purpose    : Codable mirror of GET /api/widget plus the WidgetKit timeline
//              entry type and small view-layer helpers (age formatting,
//              staleness).
// Inputs     : JSON decoded from the loopback /api/widget response.
// Outputs    : WidgetState, WidgetDevice, WidgetGroup, WidgetResponse,
//              WidgetEntry, formatAge(minutes:).
// Constraints: Field names are snake_case to match the API JSON directly —
//              no CodingKeys mapping. Only `place` and `group` are optional
//              on WidgetDevice; every other field is guaranteed non-null by
//              specs/api-contract.md § GET /api/widget. The staleness
//              threshold is never hardcoded here: the API serves
//              `stale_after_minutes` (90 per D18) and the views use that.

import WidgetKit

/// The honesty.md `alerts_latency` sentence, verbatim. The daemon serves it as
/// `notice`; this copy is the fallback for a locked or down entry, so the
/// widget states the limit even when it cannot reach the daemon. It lives here
/// rather than in ViewHelpers.swift because the test target compiles Model.swift.
let pinnedLatencyNotice =
    "Alerts inherit the network's delay. An arrival or departure may be reported "
    + "minutes to hours late."

enum WidgetState: String, Codable, CaseIterable {
    case ok
    case stale
    case error
    case locked
    case down
}

struct WidgetDevice: Codable {
    let device_id: String
    let name: String
    let provider: String
    let last_observed_at: String
    let age_minutes: Int
    let latitude: Double
    let longitude: Double
    let place: String?
    let group: String?
}

extension WidgetDevice {
    /// Stale against the threshold the daemon served, not one chosen here.
    func isStale(after minutes: Int) -> Bool { age_minutes > minutes }

    /// What to show in the place column. The API already sends `place: null`
    /// for a stale device (honesty.md `presence_stale`); this renders that as
    /// "unknown" rather than letting it read like "no named place".
    func placeText(staleAfter minutes: Int) -> String {
        if isStale(after: minutes) {
            return "unknown"
        }
        return place ?? "no named place"
    }
}

struct WidgetGroup: Codable {
    let id: Int
    let name: String
    let verdict: String
    let note: String
}

struct WidgetResponse: Codable {
    let state: WidgetState
    let version: String
    let last_poll_at: String?
    let next_poll_at: String?
    let tracked_count: Int
    let stale_after_minutes: Int
    let devices: [WidgetDevice]
    let groups: [WidgetGroup]
    let show_map: Bool
    let notice: String
}

struct WidgetEntry: TimelineEntry {
    let date: Date
    let response: WidgetResponse?
    let state: WidgetState
    let errorMessage: String?
}

extension WidgetEntry {
    /// The threshold the daemon served. The fallback matters only for locked
    /// and down entries, which carry no response and render no device rows.
    var staleAfterMinutes: Int { response?.stale_after_minutes ?? 90 }
}

/// minutes < 1 -> "just now"; < 60 -> "N min ago"; < 2880 (48 h) -> "N h ago"; else "N d ago".
func formatAge(minutes: Int) -> String {
    if minutes < 1 {
        return "just now"
    }
    if minutes < 60 {
        return "\(minutes) min ago"
    }
    if minutes < 2880 {
        return "\(minutes / 60) h ago"
    }
    return "\(minutes / 1440) d ago"
}
