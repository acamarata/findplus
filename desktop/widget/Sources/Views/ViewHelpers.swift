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

/// The character a letter badge shows: the pinned one, else the label's
/// initial, else the provider name's. nil when there is no text at all.
func resolveLetter(icon: String, label: String?, name: String) -> Character? {
    let raw: Character?
    if icon.hasPrefix("letter:"), let c = icon.dropFirst(7).first { raw = c }
    else {
        let labelSource = label?.trimmingCharacters(in: .whitespacesAndNewlines)
        let nameSource = name.trimmingCharacters(in: .whitespacesAndNewlines)
        let source = (labelSource?.isEmpty == false ? labelSource! : nameSource)
        raw = source.first
    }
    guard let c = raw else { return nil }
    return String(c).uppercased().first ?? c
}

/// The SF Symbol for a Find+ icon id (specs/labels-and-icons.md § Widget).
///
/// `squirrel` and `anchor` are the two pinned Lucide ids with no good SF
/// Symbol match; they fall through to the letter circle, as do `letter`,
/// `letter:X` and `none`. An SF Symbol exists for every uppercase letter and
/// digit in the `X.circle.fill` form, so the fallback never resolves to a
/// missing symbol.
func sfSymbol(for icon: String, label: String?, name: String) -> String {
    let table: [String: String] = [
        "user": "person.fill", "users": "person.2.fill",
        "user-round": "person.crop.circle.fill", "baby": "figure.child",
        "footprints": "shoeprints.fill", "glasses": "eyeglasses",
        "shirt": "tshirt.fill", "graduation-cap": "graduationcap.fill",
        "heart": "heart.fill", "smile": "face.smiling.fill",
        "dog": "dog.fill", "cat": "cat.fill", "bird": "bird.fill",
        "rabbit": "hare.fill", "fish": "fish.fill", "paw-print": "pawprint.fill",
        "turtle": "tortoise.fill",
        "bike": "bicycle", "backpack": "backpack", "shopping-bag": "bag.fill",
        "key": "key.fill", "key-round": "key.fill", "car": "car.fill",
        "luggage": "suitcase.fill", "wallet": "wallet.pass.fill",
        "watch": "applewatch", "smartphone": "iphone", "laptop": "laptopcomputer",
        "umbrella": "umbrella.fill", "camera": "camera.fill",
        "book-open": "book.fill", "gift": "gift.fill", "guitar": "guitars.fill",
        "scissors": "scissors", "wrench": "wrench.fill", "hammer": "hammer.fill",
        "briefcase": "briefcase.fill",
        "door-open": "door.left.hand.open", "house": "house.fill", "tent": "tent.fill",
        "map-pin": "mappin.circle.fill", "compass": "location.north.circle.fill",
        "plane": "airplane", "train-front": "train.side.front.car",
        "bus": "bus.fill", "sailboat": "sailboat.fill", "bell": "bell.fill",
    ]
    if icon.hasPrefix("lucide:"), let symbol = table[String(icon.dropFirst(7))] {
        return symbol
    }
    if let letter = resolveLetter(icon: icon, label: label, name: name) {
        return "\(letter).circle.fill"
    }
    return "circle.fill"
}

/// The 9 pt footer notice. `response.notice` when the daemon answered; the
/// pinned sentence when it did not (locked/down/error entries carry no body).
///
/// Three lines with a 0.8 minimum scale factor: the sentence is 104
/// characters and would otherwise be ellipsed away in the small family,
/// which is the one place a reader most needs it.
struct NoticeFooter: View {
    let entry: WidgetEntry

    var body: some View {
        Text(entry.response?.notice ?? pinnedLatencyNotice)
            .font(.system(size: 9))
            .foregroundStyle(.secondary)
            .lineLimit(3)
            .minimumScaleFactor(0.8)
            .fixedSize(horizontal: false, vertical: true)
    }
}
