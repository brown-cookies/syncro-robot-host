# SYNCRO Retention and Deletion Schedule

**Status:** Written on 24 September 2026. This document defines the project data-retention requirement; it does **not** implement the deletion job. The six-month post-study analysis window is the project's proposed default and remains subject to adviser/ethics confirmation.

## 1. Data covered

| Data                                                                                                                                                                                        | Persistence                                                                     | Retention / deletion rule                                                                                                                                   |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Raw voice audio                                                                                                                                                                             | **Not persisted**; held only in the per-session in-memory buffer while STT runs | Discard immediately after `end_audio` processing completes and the transcript is produced                                                                   |
| Acoustic feature vectors                                                                                                                                                                    | **Not persisted**; computed in memory for affect classification                 | Discard after the affect classifier completes                                                                                                               |
| Transcript text                                                                                                                                                                             | **Not persisted verbatim**                                                      | No retained transcript; only derived intent/confidence/context fields may enter the decision trace                                                          |
| Participant-scoped structured data (`tasks`, `routine_log`, `decision_trace`, `activity_buckets`, `lead_time_state`, `outages`, `consent_records`, `self_reports`, `exit_survey_responses`) | SQLite on the research-operated host                                            | Retain until the earlier of **(a)** study completion + 6-month analysis window, or **(b)** a participant deletion request                                   |
| `users` identity row                                                                                                                                                                        | SQLite                                                                          | Retained as the minimum identity record required to preserve referential integrity and deletion auditability; it contains no behavioral interaction history |
| `deletion_receipts`                                                                                                                                                                         | SQLite                                                                          | Retain as an audit record that deletion was requested/completed; it is not part of participant-content deletion                                             |
| `ingress_event_log`                                                                                                                                                                         | SQLite                                                                          | Connector audit metadata only; not participant-scoped. Retain under the connector/audit record policy rather than the participant-content schedule          |

## 2. Deletion triggers

Two triggers use the same participant-data deletion scope:

1. **Participant request:** deletion may be requested at any time via
   `POST /v1/data-deletion-request` (SPEC §6.5, FR-H11a). **Status: UNIMPLEMENTED.**
   This endpoint is not present in the current codebase (`api/http/` contains only
   `health.py` and `tasks.py`). The scope defined here — clear all participant-scoped
   content listed in §1, while preserving the `users` row and writing a
   `deletion_receipts` row — is the *intended* behavior once built, not a live capability.
2. **Schedule expiry:** after the study ends, participant-scoped data reaches deletion
   eligibility at the end of the 6-month analysis window. **Status: UNIMPLEMENTED.**
   No host-side scheduled deletion job exists yet (see §3). When built, the expiry
   trigger must apply the same per-table deletion scope as a participant request.

## 3. Operational rule

    The retention schedule is a policy requirement, not a claim that the current prototype already performs automatic expiry. A host-side scheduled deletion job is **not implemented**. Until that mechanism exists, no fieldwork data is authorized by this schedule to exceed the stated retention window, and any participant deletion request must be handled using the same defined per-table scope.

## 4. Protection boundary

Participant data may cross the network boundary only to the team-operated research host
under the project's approved architecture. The binding protections are:

| Protection | Mechanism (per SPEC §14) | Status |
|---|---|---|
| Encryption in transit | WireGuard tunnel, edge client to host | **Planned.** No WireGuard, TLS, or transport-encryption code exists in the current repo. |
| Encryption at rest | Encryption on the host's data store | **Planned.** No at-rest encryption code exists in the current repo. |
| Retention-and-deletion schedule | This document | **Partially in place.** Schedule is written; the deletion endpoint and expiry job it describes are both unimplemented (§2, §3). |

**Approval note:** The 6-month duration is a proposed default pending adviser/ethics
confirmation. If the confirmed duration changes, only the retention interval changes;
the data categories, deletion triggers, and deletion scope remain as specified here
unless separately revised.
