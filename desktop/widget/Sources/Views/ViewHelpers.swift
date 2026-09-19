// ViewHelpers.swift
//
// Purpose    : Small pure helpers shared by SmallView/MediumView/LargeView.
// Inputs     : WidgetState, WidgetEntry.
// Outputs    : dot colour, state label text, and the 9 pt footer notice every
//              family renders (widget.md § Behaviour: "Every entry shows
//              `notice` in the footer at 9 pt").
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

/// The 9 pt footer notice. `response.notice` when the daemon answered; the
/// pinned sentence when it did not (locked/down/error entries carry no body).
struct NoticeFooter: View {
    let entry: WidgetEntry

    var body: some View {
        Text(entry.response?.notice ?? "Locations can be minutes to hours late.")
            .font(.system(size: 9))
            .foregroundStyle(.secondary)
            .lineLimit(2)
    }
}
