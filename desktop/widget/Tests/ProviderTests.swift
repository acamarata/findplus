// ProviderTests.swift
//
// Purpose    : Exercise FindPlusProvider.fetch() against stubbed HTTP
//              responses — 200/401/connection-refused — without ever
//              touching the real network (PRI rule 3).
// Inputs     : URLProtocolStub, registered on the provider's injected
//              URLSessionConfiguration.
// Outputs    : XCTest assertions on the resulting WidgetEntry.
// Constraints: URLProtocolStub is registered only on the custom
//              configuration passed to FindPlusProvider, never on
//              URLSession.shared, so only this provider's requests are
//              intercepted. WidgetKit's TimelineProviderContext has no
//              accessible initializer, so these tests call fetch() (made
//              internal for testability, see Provider.swift) and the pure
//              nextReloadDate() helper directly rather than
//              getSnapshot(in:)/getTimeline(in:).

import WidgetKit
import XCTest

// Provider.swift is compiled directly into this test target (see
// project.yml) rather than imported from FindPlusWidgetExtension — see the
// note in ModelTests.swift.

final class URLProtocolStub: URLProtocol {
    static var stubbedData: Data?
    static var stubbedStatusCode: Int = 200

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let data = URLProtocolStub.stubbedData else {
            client?.urlProtocol(self, didFailWithError: URLError(.cannotConnectToHost))
            return
        }
        let response = HTTPURLResponse(
            url: request.url!,
            statusCode: URLProtocolStub.stubbedStatusCode,
            httpVersion: nil,
            headerFields: nil
        )!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

final class ProviderTests: XCTestCase {
    private func stubbedConfiguration() -> URLSessionConfiguration {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [URLProtocolStub.self]
        return config
    }

    override func tearDown() {
        URLProtocolStub.stubbedData = nil
        URLProtocolStub.stubbedStatusCode = 200
        super.tearDown()
    }

    func testFetch200ReturnsOkEntry() async {
        let json = """
        {"state":"ok","version":"1.0","last_poll_at":null,"next_poll_at":null,
         "tracked_count":1,"devices":[],"groups":[],"show_map":false,
         "notice":"Locations can be minutes to hours late."}
        """
        URLProtocolStub.stubbedData = Data(json.utf8)
        URLProtocolStub.stubbedStatusCode = 200
        let provider = FindPlusProvider(configuration: stubbedConfiguration())

        let entry = await provider.fetch()
        XCTAssertEqual(entry.state, .ok)
        XCTAssertEqual(entry.response?.tracked_count, 1)
    }

    func testFetch401ReturnsLockedEntry() async {
        URLProtocolStub.stubbedData = Data()
        URLProtocolStub.stubbedStatusCode = 401
        let provider = FindPlusProvider(configuration: stubbedConfiguration())

        let entry = await provider.fetch()
        XCTAssertEqual(entry.state, .locked)
        XCTAssertNil(entry.response)
    }

    func testFetchConnectionRefusedReturnsDownEntry() async {
        URLProtocolStub.stubbedData = nil
        let provider = FindPlusProvider(configuration: stubbedConfiguration())

        let entry = await provider.fetch()
        XCTAssertEqual(entry.state, .down)
        XCTAssertEqual(entry.errorMessage, "Find+ is not running")
    }

    func testTimelinePolicy15Min() {
        let now = Date()
        let next = FindPlusProvider.nextReloadDate(from: now)
        let minutesFromNow = next.timeIntervalSince(now) / 60
        XCTAssertTrue((14...16).contains(minutesFromNow), "expected ~15 min, got \(minutesFromNow)")
    }

    func testFetchMalformedJsonReturnsErrorEntryWithoutCrashing() async {
        URLProtocolStub.stubbedData = Data("{\"state\":\"ok\",".utf8)
        URLProtocolStub.stubbedStatusCode = 200
        let provider = FindPlusProvider(configuration: stubbedConfiguration())

        let entry = await provider.fetch()
        XCTAssertEqual(entry.state, .error)
        XCTAssertNil(entry.response)
        XCTAssertNotNil(entry.errorMessage)
    }

    func testFetchPartialJsonMissingRequiredFieldReturnsErrorEntry() async {
        // tracked_count is non-null in specs/api-contract.md; dropping it must
        // surface as the error state, never a crash or a half-built response.
        let json = """
        {"state":"ok","version":"1.0","last_poll_at":null,"next_poll_at":null,
         "devices":[],"groups":[],"show_map":false,
         "notice":"Locations can be minutes to hours late."}
        """
        URLProtocolStub.stubbedData = Data(json.utf8)
        let provider = FindPlusProvider(configuration: stubbedConfiguration())

        let entry = await provider.fetch()
        XCTAssertEqual(entry.state, .error)
        XCTAssertNil(entry.response)
    }

    func testFetchDecodesDeviceAndGroupRowsWithNullPlaceAndGroup() async {
        // Locks the wire field names of specs/api-contract.md GET /api/widget:
        // every device field except place/group is non-null, and group.id is a
        // JSON number. The other fixtures use empty arrays, so this is the only
        // test that decodes a real row.
        let json = """
        {"state":"stale","version":"1.0","last_poll_at":"2026-01-01T00:00:00Z",
         "next_poll_at":"2026-01-01T00:05:00Z","tracked_count":1,
         "devices":[{"device_id":"d1","name":"Keys","provider":"google-find-hub",
           "last_observed_at":"2026-01-01T00:00:00Z","age_minutes":181,
           "latitude":40.5,"longitude":-74.25,"place":null,"group":null}],
         "groups":[{"id":7,"name":"School run","verdict":"together",
           "note":"last seen 3 h ago"}],
         "show_map":true,"notice":"Locations can be minutes to hours late."}
        """
        URLProtocolStub.stubbedData = Data(json.utf8)
        let provider = FindPlusProvider(configuration: stubbedConfiguration())

        let entry = await provider.fetch()
        XCTAssertEqual(entry.state, .stale)
        let device = entry.response?.devices.first
        XCTAssertNotNil(device)
        XCTAssertEqual(device?.device_id, "d1")
        XCTAssertEqual(device?.age_minutes, 181)
        XCTAssertEqual(device?.latitude, 40.5)
        XCTAssertNil(device?.place)
        XCTAssertNil(device?.group)
        XCTAssertEqual(device?.isStale, true)
        XCTAssertEqual(entry.response?.groups.first?.id, 7)
        XCTAssertEqual(entry.response?.show_map, true)
    }
}
