// Colors.swift
//
// Purpose    : Dot colours shared by every widget view/family.
// Inputs     : None (constants).
// Outputs    : Four Color extensions matching specs/widget.md § Files Colors.swift.
// Constraints: Constants only, no logic; system semantic equivalents apply
//              automatically in dark mode via SwiftUI's Color(red:green:blue:).

import Foundation
import SwiftUI

extension Color {
    static let dotGreen = Color(red: 0x34 / 255.0, green: 0xc7 / 255.0, blue: 0x59 / 255.0)
    static let dotAmber = Color(red: 0xff / 255.0, green: 0x9f / 255.0, blue: 0x0a / 255.0)
    static let dotRed = Color(red: 0xff / 255.0, green: 0x3b / 255.0, blue: 0x30 / 255.0)
    static let dotGrey = Color(red: 0x8e / 255.0, green: 0x8e / 255.0, blue: 0x93 / 255.0)
}

extension Color {
    /// Parses "#rrggbb" — the only shape `labels.py:validate_color` stores.
    ///
    /// Falls back to grey on anything malformed rather than failing a widget
    /// render. A stored colour is always valid, but a widget that cannot draw
    /// is worse than one drawing the wrong colour.
    init(hex: String) {
        let stripped = hex.hasPrefix("#") ? String(hex.dropFirst()) : hex
        var value: UInt64 = 0
        guard stripped.count == 6, Scanner(string: stripped).scanHexInt64(&value) else {
            self = .gray
            return
        }
        self.init(
            red: Double((value & 0xFF0000) >> 16) / 255.0,
            green: Double((value & 0x00FF00) >> 8) / 255.0,
            blue: Double(value & 0x0000FF) / 255.0
        )
    }
}
