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
//              specs/api-contract.md § GET /api/widget.

import WidgetKit

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
    /// Device-level stale threshold: no fix in the last two hours.
    var isStale: Bool { age_minutes > 120 }
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
