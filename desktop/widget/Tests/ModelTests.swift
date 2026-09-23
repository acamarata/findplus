// ModelTests.swift
//
// Purpose    : Decoding fixtures for every WidgetState, formatAge boundary
//              cases, and WidgetDevice.isStale.
// Inputs     : Fixture JSON matching GET /api/widget's shape.
// Outputs    : XCTest assertions.
// Constraints: No network — pure decoding and pure-function tests only.

import WidgetKit
import XCTest

// Model.swift is compiled directly into this test target (see project.yml)
// rather than imported from FindPlusWidgetExtension: app-extension bundles
// do not export Swift symbols for a separate test bundle to @testable
// import.

final class ModelTests: XCTestCase {
    private func decode(state: String) throws -> WidgetResponse {
        let json = """
        {"state":"\(state)","version":"1.0","last_poll_at":null,"next_poll_at":null,
         "tracked_count":2,"stale_after_minutes":90,"devices":[],"groups":[],
         "show_map":false,
         "notice":"Alerts inherit the network's delay. An arrival or departure may be reported minutes to hours late."}
        """
        return try JSONDecoder().decode(WidgetResponse.self, from: Data(json.utf8))
    }

    func testDecodeOkState() throws {
        let response = try decode(state: "ok")
        XCTAssertEqual(response.state, .ok)
        XCTAssertEqual(response.tracked_count, 2)
    }

    func testDecodeStaleState() throws {
        XCTAssertEqual(try decode(state: "stale").state, .stale)
    }

    func testDecodeErrorState() throws {
        XCTAssertEqual(try decode(state: "error").state, .error)
    }

    func testDecodeLockedEntryFields() {
        let entry = WidgetEntry(date: Date(), response: nil, state: .locked, errorMessage: nil)
        XCTAssertEqual(entry.state, .locked)
        XCTAssertNil(entry.response)
    }

    func testDecodeDownEntryFields() {
        let entry = WidgetEntry(date: Date(), response: nil, state: .down, errorMessage: "Find+ is not running")
        XCTAssertEqual(entry.state, .down)
        XCTAssertEqual(entry.errorMessage, "Find+ is not running")
    }

    func testFormatAgeJustNow() {
        XCTAssertEqual(formatAge(minutes: 0), "just now")
    }

    func testFormatAgeMinutes() {
        XCTAssertEqual(formatAge(minutes: 1), "1 min ago")
        XCTAssertEqual(formatAge(minutes: 59), "59 min ago")
    }

    func testFormatAgeHours() {
        XCTAssertEqual(formatAge(minutes: 60), "1 h ago")
        XCTAssertEqual(formatAge(minutes: 2879), "47 h ago")
    }

    /// E1 honesty round 2 F15: the stale line divided by 60 and printed hours
    /// only, so 119 minutes read "no fix for 1 h" and five days read
    /// "no fix for 120 h". Rounding a gap in location history down is the
    /// wrong direction for this app.
    /// E1 honesty round 2 F10: the widget printed the engine's raw enum while
    /// the dashboard said "Together", README and FAQ advertised a fourth word
    /// ("apart") the engine never produces.
    func testVerdictLabelMatchesTheDashboardWording() {
        XCTAssertEqual(verdictLabel("all_together"), "Together")
        XCTAssertEqual(verdictLabel("partial"), "Partial")
        XCTAssertEqual(verdictLabel("unknown"), "Unknown")
    }

    func testVerdictLabelPassesAnUnknownValueThrough() {
        XCTAssertEqual(verdictLabel("something_new"), "something_new")
    }

    func testFormatStaleGapUsesTheSameLadderAsFormatAge() {
        XCTAssertEqual(formatStaleGap(minutes: 5), "no fix for 5 min")
        XCTAssertEqual(formatStaleGap(minutes: 59), "no fix for 59 min")
        XCTAssertEqual(formatStaleGap(minutes: 119), "no fix for 1 h")
        XCTAssertEqual(formatStaleGap(minutes: 2879), "no fix for 47 h")
        XCTAssertEqual(formatStaleGap(minutes: 7200), "no fix for 5 d")
    }

    func testFormatStaleGapNeverReportsAbsurdHours() {
        // The old spelling: 7200 / 60 = 120.
        XCTAssertFalse(formatStaleGap(minutes: 7200).contains("120 h"))
    }

    func testFormatAgeDays() {
        XCTAssertEqual(formatAge(minutes: 2880), "2 d ago")
        XCTAssertEqual(formatAge(minutes: 4320), "3 d ago")
    }

    private func device(ageMinutes: Int, place: String? = nil) -> WidgetDevice {
        WidgetDevice(
            device_id: "d1", name: "Tag", provider: "google-find-hub",
            last_observed_at: "2026-01-01T00:00:00Z", age_minutes: ageMinutes,
            latitude: 0, longitude: 0, place: place, group: nil,
            icon: "letter", color: "#888888"
        )
    }

    /// The threshold comes from the API (90 per D18), not from a constant here.
    func testDeviceIsStaleAgainstTheServedThreshold() {
        XCTAssertTrue(device(ageMinutes: 91).isStale(after: 90))
        XCTAssertFalse(device(ageMinutes: 90).isStale(after: 90))
        // The old hardcoded 120 would have called this one fresh.
        XCTAssertTrue(device(ageMinutes: 100).isStale(after: 90))
    }

    func testStaleDeviceRendersItsPlaceAsUnknown() {
        XCTAssertEqual(device(ageMinutes: 91).placeText(staleAfter: 90), "unknown")
        XCTAssertEqual(
            device(ageMinutes: 91, place: "Home").placeText(staleAfter: 90), "unknown"
        )
    }

    func testFreshDeviceRendersItsPlace() {
        XCTAssertEqual(device(ageMinutes: 5, place: "Home").placeText(staleAfter: 90), "Home")
        XCTAssertEqual(device(ageMinutes: 5).placeText(staleAfter: 90), "no named place")
    }

    // UAT2 N2/N11: MediumView's device row and every sfSymbol() letter badge
    // read `name` raw even when the tag had a label.
    func testDisplayNamePrefersTheLabel() {
        var d = device(ageMinutes: 0)
        d.label = "Omar's backpack"
        XCTAssertEqual(d.displayName, "Omar's backpack")
    }

    func testDisplayNameFallsBackToNameWithNoLabel() {
        XCTAssertEqual(device(ageMinutes: 0).displayName, "Tag")
    }

    func testDisplayNameFallsBackToNameWithABlankLabel() {
        var d = device(ageMinutes: 0)
        d.label = "   "
        XCTAssertEqual(d.displayName, "Tag")
    }

    func testStaleAfterMinutesIsDecoded() throws {
        XCTAssertEqual(try decode(state: "ok").stale_after_minutes, 90)
    }

    func testEntryFallsBackToD18WhenThereIsNoResponse() {
        let entry = WidgetEntry(date: Date(), response: nil, state: .locked, errorMessage: nil)
        XCTAssertEqual(entry.staleAfterMinutes, 90)
    }

    /// The footer sentence is honesty.md's `alerts_latency`, verbatim.
    func testNoticeField() throws {
        let response = try decode(state: "ok")
        XCTAssertEqual(response.notice, pinnedLatencyNotice)
        XCTAssertEqual(
            pinnedLatencyNotice,
            "Alerts inherit the network's delay. An arrival or departure may be "
                + "reported minutes to hours late."
        )
    }

    // --------------------------------------------- icons and colours (P2-E2)
    func testWidgetDeviceDecodesIconAndColor() throws {
        let json = """
        {"device_id":"d1","name":"Tag","provider":"google-find-hub",
         "last_observed_at":"2026-01-01T00:00:00Z","age_minutes":0,
         "latitude":0,"longitude":0,"place":null,"group":null,
         "icon":"lucide:dog","color":"#4f8cf7"}
        """
        let device = try JSONDecoder().decode(WidgetDevice.self, from: Data(json.utf8))
        XCTAssertEqual(device.icon, "lucide:dog")
        XCTAssertEqual(device.color, "#4f8cf7")
    }

    func testWidgetDeviceDecodesLabel() throws {
        let json = """
        {"device_id":"d1","name":"Pebblebee Clip","provider":"google-find-hub",
         "last_observed_at":"2026-01-01T00:00:00Z","age_minutes":0,
         "latitude":0,"longitude":0,"place":null,"group":null,
         "label":"Omar's backpack"}
        """
        let device = try JSONDecoder().decode(WidgetDevice.self, from: Data(json.utf8))
        XCTAssertEqual(device.label, "Omar's backpack")
        XCTAssertEqual(device.displayName, "Omar's backpack")
    }

    /// R-P2-23: a 1.0.x/1.1-pre daemon never sent `label` at all.
    func testWidgetDeviceDecodesWithoutLabel() throws {
        let json = """
        {"device_id":"d1","name":"Tag","provider":"google-find-hub",
         "last_observed_at":"2026-01-01T00:00:00Z","age_minutes":0,
         "latitude":0,"longitude":0,"place":null,"group":null}
        """
        let device = try JSONDecoder().decode(WidgetDevice.self, from: Data(json.utf8))
        XCTAssertNil(device.label)
        XCTAssertEqual(device.displayName, "Tag")
    }

    func testWidgetGroupDecodesIcon() throws {
        let json = """
        {"id":1,"name":"Family","verdict":"together","note":"note","icon":"lucide:users"}
        """
        let group = try JSONDecoder().decode(WidgetGroup.self, from: Data(json.utf8))
        XCTAssertEqual(group.icon, "lucide:users")
    }

    /// R-P2-23: a 1.1 widget must still decode a payload from a 1.0.x daemon, which never
    /// sent `icon`/`color` at all (loop2 C3 — the production defaulting existed but had
    /// no regression test for the old-payload shape).
    func testWidgetDeviceDecodesWithoutIconOrColor() throws {
        let json = """
        {"device_id":"d1","name":"Tag","provider":"google-find-hub",
         "last_observed_at":"2026-01-01T00:00:00Z","age_minutes":0,
         "latitude":0,"longitude":0,"place":null,"group":null}
        """
        let device = try JSONDecoder().decode(WidgetDevice.self, from: Data(json.utf8))
        XCTAssertEqual(device.icon, "letter")
        XCTAssertEqual(device.color, paletteColour(for: "d1"))
    }

    func testWidgetGroupDecodesWithoutIcon() throws {
        let json = """
        {"id":1,"name":"Family","verdict":"together","note":"note"}
        """
        let group = try JSONDecoder().decode(WidgetGroup.self, from: Data(json.utf8))
        XCTAssertEqual(group.icon, "lucide:users")
    }

    func testSfSymbolKnownLucideId() {
        XCTAssertEqual(sfSymbol(for: "lucide:dog", label: nil, name: "Fido"), "dog.fill")
    }

    func testSfSymbolUnmappedLucideIdFallsBackToLetter() {
        XCTAssertEqual(
            sfSymbol(for: "lucide:squirrel", label: nil, name: "Nutty"), "N.circle.fill")
        XCTAssertEqual(
            sfSymbol(for: "lucide:anchor", label: nil, name: "boat"), "B.circle.fill")
    }

    func testSfSymbolBareLetterUsesLabelOverName() {
        XCTAssertEqual(sfSymbol(for: "letter", label: "Mom", name: "Moto Tag 2"), "M.circle.fill")
    }

    func testSfSymbolPinnedLetterUsesItsOwnCharacter() {
        XCTAssertEqual(sfSymbol(for: "letter:Z", label: "Mom", name: "Moto Tag 2"), "Z.circle.fill")
    }

    /// CR-C-E2 F1: a label whose first character uppercases to more than one
    /// scalar (ß -> SS, ﬁ -> FI) used to trap `Character(String)`'s
    /// one-grapheme-cluster precondition. resolveLetter must fall back to a
    /// single-character badge instead of crashing the widget extension.
    func testSfSymbolMultiScalarUppercaseDoesNotTrap() {
        XCTAssertEqual(sfSymbol(for: "letter", label: "ßtart", name: "Tag"), "S.circle.fill")
        XCTAssertEqual(sfSymbol(for: "letter", label: "ﬁnder", name: "Tag"), "F.circle.fill")
    }

    // ------------------------------------------------------- places (P2-E13)

    /// A 1.0.x/1.1-pre daemon sends no `places` key at all; `decode(state:)`'s
    /// fixture already omits it, so the whole response must still decode
    /// (same fallback R-P2-23 pins for device icon/color).
    func testWidgetResponseDecodesWithoutPlacesKey() throws {
        let response = try decode(state: "ok")
        XCTAssertEqual(response.places, [])
    }

    func testWidgetResponseDecodesPlaces() throws {
        let json = """
        {"state":"ok","version":"1.0","last_poll_at":null,"next_poll_at":null,
         "tracked_count":1,"stale_after_minutes":90,"devices":[],"groups":[],
         "show_map":false,"notice":"\(pinnedLatencyNotice)",
         "places":[{"id":3,"name":"Home","device_ids":["d1"],"group_ids":[7],
                    "last_change_at":"2026-01-01T00:00:00Z"}]}
        """
        let response = try JSONDecoder().decode(WidgetResponse.self, from: Data(json.utf8))
        XCTAssertEqual(response.places.count, 1)
        let place = response.places[0]
        XCTAssertEqual(place.id, 3)
        XCTAssertEqual(place.name, "Home")
        XCTAssertEqual(place.device_ids, ["d1"])
        XCTAssertEqual(place.group_ids, [7])
        XCTAssertEqual(place.last_change_at, "2026-01-01T00:00:00Z")
    }

    func testWidgetPlaceDecodesNullLastChangeAt() throws {
        let json = """
        {"id":1,"name":"Empty","device_ids":[],"group_ids":[],"last_change_at":null}
        """
        let place = try JSONDecoder().decode(WidgetPlace.self, from: Data(json.utf8))
        XCTAssertNil(place.last_change_at)
    }

    /// R-P2-23's badge grammar: a place references occupants by id, so the
    /// widget looks their icon/color up in the same response's devices/groups.
    func testWidgetResponseLooksUpDeviceAndGroupById() throws {
        let json = """
        {"state":"ok","version":"1.0","last_poll_at":null,"next_poll_at":null,
         "tracked_count":1,"stale_after_minutes":90,
         "devices":[{"device_id":"d1","name":"Keys","provider":"google-find-hub",
           "last_observed_at":"2026-01-01T00:00:00Z","age_minutes":0,
           "latitude":0,"longitude":0,"place":null,"group":null,
           "icon":"lucide:key","color":"#4f8cf7"}],
         "groups":[{"id":7,"name":"Family","icon":"lucide:users",
           "verdict":"together","note":"n"}],
         "show_map":false,"notice":"\(pinnedLatencyNotice)","places":[]}
        """
        let response = try JSONDecoder().decode(WidgetResponse.self, from: Data(json.utf8))
        XCTAssertEqual(response.device(id: "d1")?.name, "Keys")
        XCTAssertNil(response.device(id: "missing"))
        XCTAssertEqual(response.group(id: 7)?.name, "Family")
        XCTAssertNil(response.group(id: 99))
    }

    func testMinutesSinceParsesAnApiTimestamp() {
        let now = ISO8601DateFormatter().date(from: "2026-01-01T00:10:00Z")!
        let minutes = minutesSince("2026-01-01T00:00:00Z", now: now)
        XCTAssertEqual(minutes, 10)
    }

    func testMinutesSinceIsNilForMissingOrMalformedInput() {
        XCTAssertNil(minutesSince(nil))
        XCTAssertNil(minutesSince("not-a-date"))
    }
}
