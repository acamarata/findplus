// Colors.swift
//
// Purpose    : Dot colours shared by every widget view/family.
// Inputs     : None (constants).
// Outputs    : Four Color extensions matching specs/widget.md § Files Colors.swift.
// Constraints: Constants only, no logic; system semantic equivalents apply
//              automatically in dark mode via SwiftUI's Color(red:green:blue:).

import SwiftUI

extension Color {
    static let dotGreen = Color(red: 0x34 / 255.0, green: 0xc7 / 255.0, blue: 0x59 / 255.0)
    static let dotAmber = Color(red: 0xff / 255.0, green: 0x9f / 255.0, blue: 0x0a / 255.0)
    static let dotRed = Color(red: 0xff / 255.0, green: 0x3b / 255.0, blue: 0x30 / 255.0)
    static let dotGrey = Color(red: 0x8e / 255.0, green: 0x8e / 255.0, blue: 0x93 / 255.0)
}
