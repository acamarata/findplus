// Intents.swift
//
// Purpose    : The widget's two interactive affordances: trigger an
//              immediate poll, and open the Find+ dashboard.
// Inputs     : None (no parameters).
// Outputs    : A POST to /api/poll-now; a NSWorkspace open of findplus://open.
// Constraints: Declared at module scope (required for App Intents
//              registration); perform() is @MainActor for the NSWorkspace
//              call. PollNowIntent is fire-and-forget — the timeline
//              refreshes within 15 minutes regardless of the response.

import AppIntents
import AppKit
import Foundation

struct PollNowIntent: AppIntent {
    static var title: LocalizedStringResource = "Poll now"
    static var description = IntentDescription("Trigger an immediate location poll.")

    @MainActor
    func perform() async throws -> some IntentResult {
        guard let url = URL(string: "http://127.0.0.1:8647/api/poll-now") else {
            return .result()
        }
        var req = URLRequest(url: url, timeoutInterval: 3)
        req.httpMethod = "POST"
        _ = try? await URLSession.shared.data(for: req)
        return .result()
    }
}

struct OpenFindPlusIntent: AppIntent {
    static var title: LocalizedStringResource = "Open Find+"
    static var description = IntentDescription("Open the Find+ dashboard.")

    @MainActor
    func perform() async throws -> some IntentResult {
        if let url = URL(string: "findplus://open") {
            NSWorkspace.shared.open(url)
        }
        return .result()
    }
}
