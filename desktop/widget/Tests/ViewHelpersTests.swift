// ViewHelpersTests.swift
//
// Purpose    : Color(hex:) parsing (P2-E4-W3-S1-T5), the two sfSymbol()
//              branches P2-E2-W2-S1-T7's ModelTests additions do not reach,
//              and the ruling R-P2-23 legacy-payload decode.
// Inputs     : Literal icon/label/name/hex strings and one JSON literal.
// Outputs    : XCTest assertions.
// Constraints: No network — pure-function and decode tests only. No (icon,
//              label, name) triple asserted here is already asserted in
//              ModelTests.swift, which this ticket does not touch.

import SwiftUI
import XCTest

final class ViewHelpersTests: XCTestCase {
    // ------------------------------------------------- sfSymbol, uncovered branches

    /// `none` is not in the table and is not a letter form, so it still has to
    /// land on a real symbol rather than an empty string.
    func testSfSymbolNoneFallsBackToLetter() {
        XCTAssertEqual(sfSymbol(for: "none", label: nil, name: "Bag"), "B.circle.fill")
    }

    /// Bare `letter` with no label: the character comes from the device name.
    func testSfSymbolBareLetterFallsBackToName() {
        XCTAssertEqual(sfSymbol(for: "letter", label: nil, name: "Wallet"), "W.circle.fill")
    }

    // ------------------------------------------------------------- Color(hex:)

    func testColorHexParsesEachChannel() {
        let expected = Color(red: 0x4F / 255.0, green: 0x8C / 255.0, blue: 0xF7 / 255.0)
        XCTAssertEqual(Color(hex: "#4f8cf7"), expected)
        XCTAssertEqual(Color(hex: "4f8cf7"), expected, "the leading # is optional")
    }

    /// `Scanner.scanHexInt64` scans a prefix and accepts "0x" and leading
    /// spaces, so these six-character strings were parsed as real colours
    /// before CR-C-E4 F2 rather than falling back (T5's own acceptance).
    func testColorHexSixCharactersThatAreNotAllHexAreGray() {
        XCTAssertEqual(Color(hex: "#12345z"), Color.gray)
        XCTAssertEqual(Color(hex: "#0x1234"), Color.gray)
        XCTAssertEqual(Color(hex: "#  1234"), Color.gray)
    }

    func testColorHexMalformedFallsBackToGray() {
        XCTAssertEqual(Color(hex: "not-a-color"), Color.gray)
        XCTAssertEqual(Color(hex: "#abc"), Color.gray, "three digits is not the stored shape")
        XCTAssertEqual(Color(hex: ""), Color.gray)
    }

    // ------------------------------------------- R-P2-23: a 1.0.x daemon's payload

    /// A 1.1 widget against a 1.0.x daemon: no `icon`, no `color` on the device
    /// row. Before this ruling the missing keys threw away the WHOLE response,
    /// not just the badge, and the widget showed nothing at all.
    func testDecodesLegacyPayload() throws {
        let json = """
        {"device_id":"TAG-HOME","name":"Home Tag","provider":"google-find-hub",
         "last_observed_at":"2026-01-01T00:00:00Z","age_minutes":3,
         "latitude":41.1,"longitude":-80.1,"place":null,"group":null}
        """
        let device = try JSONDecoder().decode(WidgetDevice.self, from: Data(json.utf8))
        XCTAssertEqual(device.icon, "letter")
        XCTAssertEqual(device.color, paletteColour(for: "TAG-HOME"))
        XCTAssertTrue(devicePalette.contains(device.color))
        // The whole point: it still renders a symbol.
        XCTAssertEqual(
            sfSymbol(for: device.icon, label: nil, name: device.name), "H.circle.fill"
        )
    }

    func testDecodesLegacyGroupPayload() throws {
        let json = """
        {"id":1,"name":"Family","verdict":"together","note":"note"}
        """
        let group = try JSONDecoder().decode(WidgetGroup.self, from: Data(json.utf8))
        XCTAssertEqual(group.icon, "lucide:users")
    }

    /// The default colour is the one `labels.py:palette_color_for` computes, so
    /// a legacy row gets the colour the daemon would later assign it.
    func testPaletteColourMatchesTheDocumentedFormula() {
        // sha1("TAG-HOME") mod 12, computed with hashlib and pinned here.
        XCTAssertEqual(paletteColour(for: "TAG-HOME"), Self.pinnedHomeColour)
        XCTAssertEqual(paletteColour(for: "TAG-HOME"), paletteColour(for: "TAG-HOME"))
    }

    /// Filled from `python -c "from findplus.labels import palette_color_for"`.
    private static let pinnedHomeColour = "#8fb43f"
}
