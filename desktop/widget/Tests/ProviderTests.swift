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
}
