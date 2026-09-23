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
//              on WidgetDevice; every other field, `icon`/`color` included,
//              is guaranteed non-null by specs/api-contract.md
//              § GET /api/widget. The staleness
//              threshold is never hardcoded here: the API serves
//              `stale_after_minutes` (90 per D18) and the views use that.

import CryptoKit
import Foundation
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
    let icon: String
    let color: String
    /// `var`, not `let` (same reason as `WidgetResponse.places` below): the
    /// default keeps ModelTests.swift's `device(...)` memberwise-init helper
    /// compiling unchanged, and `init(from:)` still needs to assign it for a
    /// real payload. A 1.0.x/1.1-pre daemon never sent this key either
    /// (UAT2 N2/N11/N14 -- see `displayName` below).
    var label: String? = nil
}

/// `labels.py:DEVICE_PALETTE`, in order. Only read when a 1.0.x daemon sends a
/// device row with no `color`; `cli/tests/test_labels.py` pins the two copies
/// together so this one cannot drift.
let devicePalette = [
    "#4f8cf7", "#e7663f", "#37c67a", "#c77ae6", "#e7b53f", "#3fc9d6",
    "#e64f7a", "#8fb43f", "#f2994a", "#9b6bd6", "#4fd6a8", "#d65f5f",
]

/// `labels.py:palette_color_for` — sha1 of the id, as one big integer, mod 12.
func paletteColour(for deviceID: String) -> String {
    let digest = Insecure.SHA1.hash(data: Data(deviceID.utf8))
    var remainder = 0
    for byte in digest {
        remainder = (remainder * 256 + Int(byte)) % devicePalette.count
    }
    return devicePalette[remainder]
}

extension WidgetDevice {
    /// Decode `icon`/`color` as optional, defaulting the way a 1.0.x row would.
    ///
    /// Ruling R-P2-23: those two columns arrived with the 1.1 daemon, and a 1.1
    /// widget talking to a 1.0.x daemon must still render. Without this the
    /// missing keys failed the WHOLE payload, not just the badge. The init sits
    /// in an extension so the memberwise initialiser survives for the tests.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        device_id = try c.decode(String.self, forKey: .device_id)
        name = try c.decode(String.self, forKey: .name)
        provider = try c.decode(String.self, forKey: .provider)
        last_observed_at = try c.decode(String.self, forKey: .last_observed_at)
        age_minutes = try c.decode(Int.self, forKey: .age_minutes)
        latitude = try c.decode(Double.self, forKey: .latitude)
        longitude = try c.decode(Double.self, forKey: .longitude)
        place = try c.decodeIfPresent(String.self, forKey: .place)
        group = try c.decodeIfPresent(String.self, forKey: .group)
        icon = try c.decodeIfPresent(String.self, forKey: .icon) ?? "letter"
        color = try c.decodeIfPresent(String.self, forKey: .color)
            ?? paletteColour(for: device_id)
        label = try c.decodeIfPresent(String.self, forKey: .label)
    }

    /// Stale against the threshold the daemon served, not one chosen here.
    func isStale(after minutes: Int) -> Bool { age_minutes > minutes }

    /// The label the user gave this tracker, or its raw provider name --
    /// mirrors web/app/state.js's displayName() and labels.py's display_name()
    /// (UAT2 N2/N11/N14: MediumView's device row and this widget's letter
    /// badges read `name` raw even when a label was set).
    var displayName: String {
        let trimmed = label?.trimmingCharacters(in: .whitespacesAndNewlines)
        return (trimmed?.isEmpty == false ? trimmed : nil) ?? name
    }

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
    let icon: String
    let verdict: String
    /// The phrase the API computed. Optional so an older daemon still decodes.
    let verdict_label: String?
    let note: String

    /// What to show: the served label, else the local mapping.
    ///
    /// The dashboard, this widget and the CLI each had their own mapping and
    /// printed three different things for one state, so the API serves it now
    /// (E1 honesty round 3 F4).
    var displayVerdict: String {
        verdict_label ?? verdictLabel(verdict)
    }
}

extension WidgetGroup {
    /// `icon` optional, defaulting to the 0007 group default (ruling R-P2-23):
    /// a 1.0.x daemon does not send it, and one missing key must not throw the
    /// whole payload away.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(Int.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        icon = try c.decodeIfPresent(String.self, forKey: .icon) ?? "lucide:users"
        verdict = try c.decode(String.self, forKey: .verdict)
        verdict_label = try c.decodeIfPresent(String.self, forKey: .verdict_label)
        note = try c.decode(String.self, forKey: .note)
    }
}

/// One row of `GET /api/widget`'s `places` array — feeds the PlacesWidget
/// widget kind. `device_ids`/`group_ids` reference `WidgetResponse.devices`/
/// `.groups` by id rather than repeating icon/color, so a badge's look comes
/// from the same lookup R-P2-23 already pins for the device widget.
struct WidgetPlace: Codable, Equatable {
    let id: Int
    let name: String
    let device_ids: [String]
    let group_ids: [Int]
    let last_change_at: String?
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
    // `var`, not `let`: a `let` with a default value is assigned by that
    // default in EVERY initializer, including the custom init(from:) below,
    // and reassigning it there is a compile error ("may only be initialized
    // once"). `var` keeps the default (so the synthesized memberwise init
    // keeps `places:` optional -- Provider.swift's placeholder() builds a
    // WidgetResponse without one, and this struct must not force an edit
    // onto a file this ticket does not own) while still letting the decoder
    // set the real value. Nothing outside this file ever mutates it again.
    var places: [WidgetPlace] = []
}

extension WidgetResponse {
    /// `places` decoded as optional, defaulting to `[]`: a 1.0.x/1.1-pre
    /// daemon answers `GET /api/widget` with no `places` key at all, and the
    /// rest of the payload (state/devices/groups) must still decode rather
    /// than losing everything because one new key is missing (same rule as
    /// R-P2-23's device/group icon fallback). The init sits in an extension
    /// so the memberwise initialiser survives for Provider.swift's
    /// placeholder() and the tests.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        state = try c.decode(WidgetState.self, forKey: .state)
        version = try c.decode(String.self, forKey: .version)
        last_poll_at = try c.decodeIfPresent(String.self, forKey: .last_poll_at)
        next_poll_at = try c.decodeIfPresent(String.self, forKey: .next_poll_at)
        tracked_count = try c.decode(Int.self, forKey: .tracked_count)
        stale_after_minutes = try c.decode(Int.self, forKey: .stale_after_minutes)
        devices = try c.decode([WidgetDevice].self, forKey: .devices)
        groups = try c.decode([WidgetGroup].self, forKey: .groups)
        show_map = try c.decode(Bool.self, forKey: .show_map)
        notice = try c.decode(String.self, forKey: .notice)
        places = try c.decodeIfPresent([WidgetPlace].self, forKey: .places) ?? []
    }

    /// Badge lookups: a place stores its occupants' ids, not their icon/color,
    /// so the two widgets never disagree about how a device or group looks.
    func device(id: String) -> WidgetDevice? { devices.first { $0.device_id == id } }
    func group(id: Int) -> WidgetGroup? { groups.first { $0.id == id } }
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
/// "no fix for 2 h" / "no fix for 5 d" -- the same ladder as formatAge.
///
/// The stale line divided by 60 and printed hours only, so 119 minutes read
/// "no fix for 1 h" and five days read "no fix for 120 h". Rounding a gap in
/// someone's location history DOWN is the wrong direction for this app
/// (E1 honesty round 2 F15).
/// "all_together" -> "Together". The widget printed the raw engine enum while
/// the dashboard said "Together"/"Unknown", making four vocabularies for one
/// verdict (E1 honesty round 2 F10). An unknown value is shown as-is rather
/// than guessed at.
func verdictLabel(_ verdict: String) -> String {
    switch verdict {
    case "all_together": return "Together"
    case "partial": return "Partial"
    case "unknown": return "Unknown"
    default: return verdict
    }
}

func formatStaleGap(minutes: Int) -> String {
    if minutes < 60 {
        return "no fix for \(minutes) min"
    }
    if minutes < 2880 {
        return "no fix for \(minutes / 60) h"
    }
    return "no fix for \(minutes / 1440) d"
}

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

/// Minutes elapsed since an API `...Z` instant, or nil if it does not parse.
///
/// Places carries `last_change_at` as a timestamp rather than a
/// pre-computed age the way device rows carry `age_minutes` (the server has
/// no single "the" device to compute it against per place), so the widget
/// derives it the same way it would format any other served instant.
func minutesSince(_ iso: String?, now: Date = Date()) -> Int? {
    guard let iso, let date = ISO8601DateFormatter().date(from: iso) else { return nil }
    return max(0, Int(now.timeIntervalSince(date) / 60))
}
