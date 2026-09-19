// ViewHelpers.swift
//
// Purpose    : Small pure helpers shared by SmallView/MediumView/LargeView.
// Inputs     : WidgetState.
// Outputs    : dot colour and state label text.
// Constraints: No logic beyond a fixed mapping; colours come from
//              Sources/Colors.swift so dark mode adapts automatically.

import SwiftUI

func dotColour(_ state: WidgetState) -> Color {
    switch state {
    case .ok: return .dotGreen
    case .stale: return .dotAmber
    case .error: return .dotRed
    case .locked: return .dotGrey
    case .down: return .dotGrey
    }
}

func stateLabel(_ state: WidgetState) -> String {
    switch state {
    case .ok: return "Polling"
    case .stale: return "Stale"
    case .error: return "Error"
    case .locked: return "Locked"
    case .down: return "Offline"
    }
}
