# Find+ Invariants — Test Coverage Map

Maps each invariant from `.github/docs/PROMPT.md §2` to the test(s) that enforce it.
A failing test in the Tests column is a regression, not a flaky test.

## Invariants

| # | Invariant | Tests |
|---|-----------|-------|
| I1 | Deduplication. A sighting is `(device_id, observed_at, latitude_e7, longitude_e7)` with a DB-level unique constraint. Repeats bump `times_returned` and `last_fetched_at` and create no point. | `test_dedup.py::test_identical_sighting_returned_again_is_not_a_new_point`, `test_dedup.py::test_repeat_updates_last_fetched_but_not_first` |
| I2 | `observed_at` ≠ `fetched_at`. Timelines use `observed_at`; the UI shows both plus the lag. | `test_timestamps.py::test_observed_and_fetched_are_independent` |
| I3 | Coordinates stored as integer 1e-7 degrees. | `test_timestamps.py::test_coordinates_round_trip_at_full_precision` |
| I4 | All timestamps stored naive-UTC via a `UtcDateTime` TypeDecorator that raises on naive input. Day boundaries are local midnight to next local midnight (23 h / 25 h on DST days, tested). | `test_timestamps.py::test_naive_datetimes_are_rejected`, `test_timeline.py::test_spring_forward_day_is_23_hours`, `test_timeline.py::test_fall_back_day_is_25_hours` |
| I5 | Timelines are never merged across devices. | `test_multi_device.py::test_tracks_are_never_merged_across_devices` |
| I6 | No interpolation, ever. A detection gap is drawn as a gap. | `test_timeline.py::test_no_interpolation_across_a_gap` |
| I7 | Distance is labelled "Approximate distance between observed locations" everywhere, including exports. | `test_api.py::test_timeline_stats_label_distance_as_approximate` |
| I8 | Movement filtering annotates, never deletes (`is_movement` at read time). | `test_timeline.py::test_jitter_below_threshold_is_flagged_but_retained` |
| I9 | No test in this suite reaches a real network, a real browser or a real account: `conftest.py::_block_non_loopback_sockets` is autouse, and the sign-in suites (`providers/test_google_browser_auth.py`, `providers/test_apple_web_auth.py`, `api/test_auth_routes.py`) drive fakes only. Loopback only. `Settings` raises on any other host unless `FINDPLUS_ALLOW_PUBLIC_BIND=1`. No analytics, telemetry or third-party scripts. OSM tiles are the one documented external call from the browser; §4b adds Telegram / webhook calls **only when the user configures them**. | `test_config_and_logging.py::test_default_bind_is_loopback_only`, `test_config_and_logging.py::test_non_loopback_bind_is_refused`, `test_config_and_logging.py::test_public_bind_requires_an_explicit_opt_in`, `test_api.py::test_dashboard_page_has_no_third_party_scripts` |
| I10 | 5-minute poll floor, overridable only via `ALLOW_FAST_POLLING=true`. | `test_poller.py::test_poll_interval_floor_is_five_minutes` |
| I11 | The app lock is enforced server-side (401 on every data endpoint) and `purgeRenderedData()` destroys coordinates already in the DOM. | Server-side: `test_lock_api.py::test_locked_api_refuses_every_gated_endpoint`, `test_lock_api.py::test_locked_export_returns_no_coordinates`, `api/test_auth_route_security.py::test_every_e6_route_401s_while_locked` (the seven sign-in routes, discovered from the live route table). DOM purge: `test_ui_browser.py::test_no_location_data_is_in_the_dom_while_locked`, `test_ui_browser.py::test_manual_lock_returns_to_the_lock_screen` |
| I12 | Never fabricate a location. A failed poll records status and stores nothing. | `test_poller.py::test_empty_response_records_no_location_and_invents_nothing` |

## Honesty Sentences

| Sentence key | Required text (verbatim from specs/honesty.md) | Enforced by |
|---|---|---|
| find_hub | "This history consists of locations reported through Google's Find Hub network. Moto Tag uses nearby participating Android devices to report its location. Location updates can therefore be delayed, sparse, or unavailable, and this application should not be treated as real-time emergency or child-safety GPS tracking." | `test_honesty.py::test_every_constant_matches_the_spec_verbatim` (verbatim vs `specs/honesty.md`), `test_honesty.py::test_notices_dict_matches_named_constants`, `test_honesty_text.py::test_config_notices_present` (exact), `test_api.py::test_config_exposes_thresholds_and_the_findhub_notice` (substring), `test_ui_browser.py::test_findhub_notice_is_present_after_unlocking` |
| apple | "Apple Find My locations come from nearby Apple devices and can be delayed, sparse or unavailable. Find+ can only query accessories whose keys you hold; genuine AirTags require extracting pairing keys, which most users cannot do." | `test_honesty.py::test_every_constant_matches_the_spec_verbatim` (verbatim vs `specs/honesty.md`), `test_honesty.py::test_notices_dict_matches_named_constants`, `test_honesty_text.py::test_config_notices_present` (exact); the short badge form "Apple Find My (keys you hold)" is asserted by grep in P1-E10-W6-S1-T3 acceptance — no UI test yet |
| alerts_latency | "Alerts inherit the network's delay. An arrival or departure may be reported minutes to hours late." | `test_honesty.py::test_every_constant_matches_the_spec_verbatim` (verbatim vs `specs/honesty.md`), `test_honesty.py::test_notices_dict_matches_named_constants`, `test_honesty_text.py::test_config_notices_present` (exact), `test_honesty_text.py::test_alerts_js_latency_fallback_matches_honesty_sentence` (dashboard fallback), `ui/test_alerts.py::test_alerts_latency_disclaimer_present` (rendered), `api/test_core_endpoints.py::test_widget_unlocked` (served as `/api/widget.notice`), widget `ModelTests.testNoticeField` (Swift footer) |
| presence_stale | "A tag with no recent fix is stale, not at home and not left behind. Find+ reports it as unknown." | `test_honesty.py::test_every_constant_matches_the_spec_verbatim` (verbatim vs `specs/honesty.md`), `test_honesty.py::test_notices_dict_matches_named_constants`, `test_honesty_text.py::test_config_notices_present` (exact), `api/test_core_endpoints.py::test_widget_hides_the_place_of_a_stale_device` (the rule applied, not just the sentence), widget `ModelTests.testStaleDeviceRendersItsPlaceAsUnknown` |
| lock_not_encryption | "The app lock stops casual browsing. It does not encrypt the database; anyone with access to this user account or the disk can read it. Use FileVault." | `test_honesty.py::test_every_constant_matches_the_spec_verbatim` (verbatim vs `specs/honesty.md`), `test_honesty.py::test_notices_dict_matches_named_constants`, `test_honesty_text.py::test_config_notices_present` (exact), `ui/test_lock.py::test_lock_not_encryption_notice_present` (rendered) |
| not_affiliated | "Find+ is not affiliated with Apple or Google. Find Hub and Find My are their trademarks." | `test_honesty.py::test_every_constant_matches_the_spec_verbatim` (verbatim vs `specs/honesty.md`), `test_honesty.py::test_notices_dict_matches_named_constants`, `test_honesty_text.py::test_config_notices_present` (exact) |
| chrome_required | "Google Chrome was not found on this machine. Google sign-in drives Chrome directly and cannot run without it. Install it from https://www.google.com/chrome/ and try again." | `test_honesty.py::test_notices_dict_matches_named_constants`, `test_honesty.py::test_chrome_sentence_has_exactly_one_literal` (the CLI, the API and /api/config read one constant, R-P2-6), `test_honesty_text.py::test_config_notices_present` (exact), `service/test_auth_cmd.py::test_auth_stops_early_when_chrome_is_missing` (rendered by the CLI) |

Every sentence above is covered end to end: `test_honesty.py` pins the constant against
`specs/honesty.md`, `test_honesty_text.py` pins what `/api/config` serves, and the rendered
column names the surface test where one exists. `apple` has no UI test yet — that gap is real
and is recorded here rather than papered over.

## How to use this file

When adding a test that covers an invariant: add its name to the Tests column.
When a listed test is removed or renamed: update this file in the same commit.
