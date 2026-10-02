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
| I5 | Timelines are never merged across devices. | `test_multi_device_api.py::test_tracks_are_never_merged_across_devices` |
| I6 | No interpolation, ever. A detection gap is drawn as a gap. | `test_timeline.py::test_no_interpolation_across_a_gap` |
| I7 | Distance is labelled "Approximate distance between observed locations" everywhere, including exports. | `test_api.py::test_timeline_stats_label_distance_as_approximate` (timeline stats), `test_exports.py::test_every_export_that_carries_a_distance_labels_it_approximate` (CSV, JSON, KML), `test_exports.py::test_csv_distance_column_says_it_is_approximate` |
| I8 | Movement filtering annotates, never deletes (`is_movement` at read time). | `test_timeline.py::test_jitter_below_threshold_is_flagged_but_retained` |
| I9 | No test in this suite reaches a real network, a real browser or a real account: `conftest.py::_block_non_loopback_sockets` is autouse, and the sign-in suites (`providers/test_google_browser_auth.py`, `providers/test_apple_web_auth.py`, `api/test_auth_routes.py`) drive fakes only. Loopback only. `Settings` raises on any other host unless `FINDPLUS_ALLOW_PUBLIC_BIND=1`. No analytics, telemetry or third-party scripts. OSM tiles are the one documented external call from the browser; §4b adds Telegram / webhook calls **only when the user configures them**. | `test_config_and_logging.py::test_default_bind_is_loopback_only`, `test_config_and_logging.py::test_non_loopback_bind_is_refused`, `test_config_and_logging.py::test_public_bind_requires_an_explicit_opt_in`, `test_api.py::test_dashboard_page_has_no_third_party_scripts` |
| I10 | 5-minute poll floor, overridable only via `ALLOW_FAST_POLLING=true`. | `test_poller.py::test_poll_interval_floor_is_five_minutes` |
| I11 | The app lock is enforced server-side (401 on every data endpoint) and `purgeRenderedData()` destroys coordinates already in the DOM. | Server-side: `api/test_lock_api_guards.py::test_locked_api_refuses_every_gated_endpoint`, `api/test_lock_api_guards.py::test_locked_export_returns_no_coordinates`, `api/test_auth_route_security.py::test_every_e6_route_401s_while_locked` (the seven sign-in routes, discovered from the live route table). DOM purge: `ui/boot/test_boot_lock.py::test_no_location_data_is_in_the_dom_while_locked`, `ui/boot/test_boot_controls.py::test_manual_lock_returns_to_the_lock_screen` |
| I12 | Never fabricate a location. A failed poll records status and stores nothing. | `test_poller.py::test_empty_response_records_no_location_and_invents_nothing` |

## Schema guards

| Guard | Tests |
|---|---|
| A migration never loses rows through ON DELETE CASCADE during a table rebuild. | `test_migration_cascade_guard.py` (0007/0008), `test_migration_0013.py::test_upgrade_reaches_0013_with_zero_row_loss`, `test_migration_0013.py::test_rules_and_delivery_log_survive_byte_for_byte`, `test_migration_0013.py::test_foreign_key_and_integrity_checks_are_clean`, `test_migration_0013_guards.py::test_revision_refuses_to_rebuild_with_foreign_keys_enforced` |
| Cascades still fire after a rebuild. | `test_migration_0013.py::test_rule_delete_still_cascades_to_its_deliveries`, `test_migration_0013.py::test_group_place_and_device_cascades_reach_the_rebuilt_rules`, `test_migration_0013.py::test_new_tables_cascade_from_their_parents` |
| A tracker belongs to at most one person or pet (0013 triggers). | `test_migration_0013_guards.py::test_a_second_person_for_one_tracker_is_rejected`, `test_migration_0013_guards.py::test_moving_a_membership_into_a_second_person_is_rejected`, `test_migration_0013_guards.py::test_turning_a_set_into_a_person_is_rejected_on_overlap`, `test_migration_0013_guards.py::test_triggers_exist_at_head` |
| Quality flags live beside observations; raw rows never change (I8). | `test_migration_0013.py::test_new_tables_cascade_from_their_parents` |
| Downgrade then upgrade keeps every row; re-running at head is a no-op. | `test_migration_0013_guards.py::test_downgrade_then_upgrade_round_trips`, `test_migration_0013_guards.py::test_findplus_db_upgrade_is_idempotent_at_head` |

## Quality and durability guards

| Guard | Tests |
|---|---|
| A real drive and a school run are never flagged; scoring ignores input order and is idempotent. | `quality/test_properties.py`, `quality/test_vectors.py::test_v2_real_drive_flags_nothing`, `quality/test_vectors.py::test_v3_school_run_flags_nothing` |
| The owner's 4:17 teleport is flagged, two bad fixes in a row are kept, a corroborated jump is rescued. | `quality/test_vectors.py::test_v1_owner_case_flags_the_middle_fix`, `test_v4_two_bad_in_a_row_are_kept_and_scored_point_six`, `test_v6_corroborated_jump_is_rescued`, `test_v5_sibling_disagree_flags_the_bag` |
| A lone jump is held out of the geofence for one poll, then confirmed or dropped; a failing scorer never loses observations (I8, I12). | `quality/test_ingest_hold.py` |
| Recompute is idempotent, honours `--since`, and never changes raw rows. | `quality/test_store.py::test_recompute_is_idempotent`, `test_raw_observations_are_never_changed` |
| Backups are online, verified, 0600 in a 0700 directory, rotated 7 daily + 4 weekly, secret-free, and whole while ingest writes. | `durability/test_backup.py` |
| Restore validates, refuses while running, backs up first, keeps the replaced file, never changes the source. | `durability/test_restore.py`, `durability/test_cli.py::test_restore_refuses_while_running` |
| Damage is found; a damaged daemon is read-only and starts no workers; the file is untouched. | `durability/test_integrity.py`, `durability/test_doctor_and_serve.py` |
| The JSONL export round-trips losslessly, holds no secrets, and imports only into an empty database. | `durability/test_portable.py`, `durability/test_cli.py::test_export_jsonl_to_a_file_is_private_and_importable` |

## Honesty Sentences

| Sentence key | Required text (verbatim from specs/honesty.md) | Enforced by |
|---|---|---|
| find_hub | "This history consists of locations reported through Google's Find Hub network. Your trackers use nearby participating Android devices to report their location. Location updates can therefore be delayed, sparse, or unavailable, and this application should not be treated as real-time emergency or child-safety GPS tracking." | `test_honesty.py::test_every_constant_matches_the_spec_verbatim` (verbatim vs `specs/honesty.md`), `test_honesty.py::test_notices_dict_matches_named_constants`, `test_honesty_text.py::test_config_notices_present` (exact), `test_api.py::test_config_exposes_thresholds_and_the_findhub_notice` (substring), `ui/boot/test_boot_dashboard.py::test_findhub_notice_is_present_after_unlocking` |
| apple | "Apple Find My locations come from nearby Apple devices and can be delayed, sparse or unavailable. Find+ can only query accessories whose keys you hold; genuine AirTags require extracting pairing keys, which most users cannot do." | `test_honesty.py::test_every_constant_matches_the_spec_verbatim` (verbatim vs `specs/honesty.md`), `test_honesty.py::test_notices_dict_matches_named_constants`, `test_honesty_text.py::test_config_notices_present` (exact); the short badge form "Apple Find My (keys you hold)" is pinned in the catalog and its fallback by `test_i18n_catalog.py::test_apple_badge_text_is_pinned_in_the_catalog_and_its_fallback` |
| alerts_latency | "Alerts inherit the network's delay. An arrival or departure may be reported minutes to hours late." | `test_honesty.py::test_every_constant_matches_the_spec_verbatim` (verbatim vs `specs/honesty.md`), `test_honesty.py::test_notices_dict_matches_named_constants`, `test_honesty_text.py::test_config_notices_present` (exact), `test_honesty_text.py::test_alerts_js_latency_fallback_matches_honesty_sentence` (dashboard fallback), `ui/test_alerts_rules.py::test_alerts_latency_disclaimer_present` (rendered), `api/test_core_endpoints.py::test_widget_unlocked` (served as `/api/widget.notice`), widget `ModelTests.testNoticeField` (Swift footer) |
| presence_stale | "A tag with no recent fix is stale, not at home and not left behind. Find+ reports it as unknown." | `test_honesty.py::test_every_constant_matches_the_spec_verbatim` (verbatim vs `specs/honesty.md`), `test_honesty.py::test_notices_dict_matches_named_constants`, `test_honesty_text.py::test_config_notices_present` (exact), `api/test_core_endpoints.py::test_widget_hides_the_place_of_a_stale_device` (the rule applied, not just the sentence), widget `ModelTests.testStaleDeviceRendersItsPlaceAsUnknown` |
| lock_not_encryption | "The app lock stops casual browsing. It does not encrypt the database; anyone with access to this user account or the disk can read it. Use FileVault." | `test_honesty.py::test_every_constant_matches_the_spec_verbatim` (verbatim vs `specs/honesty.md`), `test_honesty.py::test_notices_dict_matches_named_constants`, `test_honesty_text.py::test_config_notices_present` (exact), `ui/test_lock.py::test_lock_not_encryption_notice_present` (rendered) |
| not_affiliated | "Find+ is not affiliated with Apple or Google. Find Hub and Find My are their trademarks." | `test_honesty.py::test_every_constant_matches_the_spec_verbatim` (verbatim vs `specs/honesty.md`), `test_honesty.py::test_notices_dict_matches_named_constants`, `test_honesty_text.py::test_config_notices_present` (exact) |
| chrome_required | "Google Chrome was not found on this machine. Google sign-in drives Chrome directly and cannot run without it. Install it from https://www.google.com/chrome/ and try again." | `test_honesty.py::test_notices_dict_matches_named_constants`, `test_honesty.py::test_chrome_sentence_has_exactly_one_literal` (the CLI, the API and /api/config read one constant, R-P2-6), `test_honesty_text.py::test_config_notices_present` (exact), `service/test_auth_cmd.py::test_auth_stops_early_when_chrome_is_missing` (rendered by the CLI) |
| whatsapp_relay | "WhatsApp alerts are relayed through CallMeBot, a third-party free service. Your alert text transits CallMeBot's servers before reaching WhatsApp. Delivery is best-effort with no guarantee. Find+ is not affiliated with WhatsApp, Meta or CallMeBot." | `test_honesty.py::test_notices_dict_matches_named_constants`, `test_i18n_catalog.py::test_honesty_block_matches_notices_value_for_value`, `ui/test_alerts_whatsapp.py` (rendered), `ui/test_setup_wizard_notifications.py` (wizard) |
| whatsapp_setup | CallMeBot pairing steps (see `honesty.WHATSAPP_SETUP`). | same tests as whatsapp_relay |
| alerts_locked | "Notifications are held while Find+ is locked. Unlock to see what you missed." | `test_honesty.py::test_notices_dict_matches_named_constants`, `test_i18n_catalog.py::test_honesty_block_matches_notices_value_for_value`, `ui/test_alerts_whatsapp.py::test_the_alerts_locked_sentence_sits_beside_the_channel_choice` (rendered) |
| native_generic | macOS notifications show a generic "Find+ alert" until details are turned on (see `honesty.NATIVE_GENERIC`). | `test_honesty.py::test_notices_dict_matches_named_constants`, `test_i18n_catalog.py::test_honesty_block_matches_notices_value_for_value`, `ui/test_setup_wizard_native.py` (rendered note) |
| address_search | "Address search sends the text you type to OpenStreetMap's Nominatim service, a third party not affiliated with Find+, and only when you press Search." | `test_honesty.py::test_notices_dict_matches_named_constants`, `test_i18n_catalog.py::test_honesty_block_matches_notices_value_for_value`, `ui/test_places_address_notice.py::test_the_place_dialog_states_where_address_search_sends_text` (rendered), `ui/test_places.py::test_address_search_is_opt_in_and_mocked` (opt-in behaviour) |
| trips_approximate | "Stays and trips are worked out from sparse, delayed sightings. Times are when a tag was seen, and distances are approximate straight lines, not the road driven." | `test_honesty.py::test_notices_dict_matches_named_constants`, `test_i18n_catalog.py::test_honesty_block_matches_notices_value_for_value`, `test_honesty_text.py::test_config_notices_present` (exact), `trips/test_api.py::test_trips_payload_carries_the_label` |
| route_likely | "Likely route between sparse sightings, not a record of the road driven." | `test_honesty.py::test_notices_dict_matches_named_constants`, `test_i18n_catalog.py::test_honesty_block_matches_notices_value_for_value`, `test_honesty_text.py::test_config_notices_present` (exact), `trips/test_routing.py::test_routed_answer_carries_the_label` |
| routing_privacy | "Road routes are off unless you enter a routing server address. When one is set, the sightings of each trip you open are sent to that server to draw the path, so use a server you run yourself." | `test_honesty.py::test_notices_dict_matches_named_constants`, `test_i18n_catalog.py::test_honesty_block_matches_notices_value_for_value`, `test_honesty_text.py::test_config_notices_present` (exact), `trips/test_routing.py::test_no_request_without_an_endpoint` |

Every sentence above is covered end to end: `test_honesty.py` pins the constant against
`specs/honesty.md` (the P1 sentences) and the NOTICES dict, `test_honesty_text.py` pins what
`/api/config` serves and what the README carries, `test_i18n_catalog.py` pins the browser
catalog, and the rendered column names the surface test where one exists.

## How to use this file

When adding a test that covers an invariant: add its name to the Tests column.
When a listed test is removed or renamed: update this file in the same commit.
