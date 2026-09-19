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
         "tracked_count":2,"devices":[],"groups":[],"show_map":false,
         "notice":"Locations can be minutes to hours late."}
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

    func testFormatAgeDays() {
        XCTAssertEqual(formatAge(minutes: 2880), "2 d ago")
        XCTAssertEqual(formatAge(minutes: 4320), "3 d ago")
    }

    func testDeviceIsStale() {
        let stale = WidgetDevice(
            device_id: "d1", name: "Tag", provider: "google-find-hub",
            last_observed_at: "2026-01-01T00:00:00Z", age_minutes: 121,
            latitude: 0, longitude: 0, place: nil, group: nil
        )
        let fresh = WidgetDevice(
            device_id: "d1", name: "Tag", provider: "google-find-hub",
            last_observed_at: "2026-01-01T00:00:00Z", age_minutes: 120,
            latitude: 0, longitude: 0, place: nil, group: nil
        )
        XCTAssertTrue(stale.isStale)
        XCTAssertFalse(fresh.isStale)
    }

    func testNoticeField() throws {
        let response = try decode(state: "ok")
        XCTAssertEqual(response.notice, "Locations can be minutes to hours late.")
    }
}
