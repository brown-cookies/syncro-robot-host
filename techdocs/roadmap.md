# SYNCRO — Prototype Defense Sprint

## Project Execution Plan

|  |  |
|---|---|
| **From** | Yuqin Han (韩玉琴) |
| **To** | Team 9 — Almedejar, Espinosa, Marimla · BS Computer Engineering, Holy Angel University |
| **Document type** | Project execution plan |
| **Revision** | 2.1 |
| **Date** | 23 August 2026 |
| **Status** | Baselined. Schedule of record for the 1 October 2026 prototype defense |
| **Delivery window** | Sunday 23 August 2026 – Thursday 1 October 2026 · 39 calendar days |
| **Supersedes** | `SYNCRO-dev-learning-roadmap.md` §11 (schedule only; that document remains the reference for *what to learn*) · Revision 1.0 of this plan, 16 August 2026 |
| **Reads with** | `SYNCRO-panel-dispositions-signed.md` (D1–D8 dispositions, **signed**) · `SYNCRO-redesign-15k.md` (architecture of record) · `SYNCRO-edge-compute-alternatives.md` (requirements R1–R10, platform selection) · `../archive/REVIEWPANELENGG-TEAM9.md` (reasoning behind D1–D8, role assignments) |
| **Baseline dependency** | Procurement succeeds; all parts ordered 23 August, boards in hand by 29 August. See RSK-03 |
| **Distribution** | Team 9 · project adviser · external firmware reviewer |

### Revision history

| Rev | Date | Author | Change |
|:---|:---|:---|:---|
| 1.0 | 16 Aug 2026 | Y. Han | Initial sprint roadmap |
| 2.0 | 19 Aug 2026 | Y. Han | Restructured as a project execution plan. All Rev 1.0 content preserved and reorganised into standard delivery artifacts: work breakdown structure, RACI matrix, requirements traceability matrix, risk register, assumptions/dependencies/constraints register, change control, deferred-scope backlog. Two substantive corrections: (a) the firmware review tiers, previously labelled R1/R2/R3, collided with system requirements R1–R10 and are renamed **Review Class A/B/C**; (b) traceability now covers all ten requirements, including those deliberately deferred, which Rev 1.0 left unstated. No dates, owners, or scope decisions were changed |
| 2.2 | 26 Aug 2026 | Y. Han | Reduced and citation-repaired ahead of transmission to the AI/software lead. **Removed as duplication:** the RACI matrix (§3 and §2 already carry exactly one accountable owner per package and per deliverable); the per-week owner/work tables in §4.4 (restated §3 verbatim — §4.4 now carries objectives, gates and exit conditions only); the communications cadence and escalation tables (§11.1); five risk narratives that restated their own register rows (§8.3); and 23 glossary entries for standard pipeline components. **Citations repaired:** Figure 17 re-cited to `SYNCRO-redesign-15k.md` §6.1, which carries the same VRAM numbers in prose; a broken `../archive/REVIEWPANELENGG.md` reference at §8 corrected to `-TEAM9`; §7 notes that all ten requirements are restated in full in-table. **No dates, owners, work packages, gates, risks, acceptance criteria or scope decisions changed.** 934 lines to 793 |
| 2.1 | 23 Aug 2026 | Y. Han | Panel dispositions D1–D8 signed by the project adviser (letter of 20 Aug 2026). Disposition of record moves from `../archive/REVIEWPANELENGG-TEAM9.md` to `SYNCRO-panel-dispositions-signed.md`; both prior decision records archived. New **RSK-13** records that the panel has not yet ruled on the three reconsiderations (D4, D6, D7) or on whether any item was a condition of approval. **RSK-01 and A-01 are unchanged** — the letter does not raise the privacy claim and G1b still runs on 23 Aug. No dates, owners or scope decisions changed |

### Approval

| Role | Name | Approval required for | Status |
|:---|:---|:---|:---|
| Plan owner | Y. Han | Baseline; any change to the fixed dates in §4.3 | Baselined 19 Aug 2026 |
| AI/software lead | Almedejar | Workstream 1 and 4 acceptance | Pending acknowledgement |
| Hardware lead | Marimla | Workstream 2 acceptance | Pending acknowledgement |
| Methods lead | Espinosa | Workstream 3 and 5 acceptance | Pending acknowledgement |
| Project adviser | — | D1–D8 panel dispositions | **Signed** — letter of 20 Aug 2026, `SYNCRO-panel-dispositions-signed.md` |
| Project adviser | — | A-01 (privacy claim) and A-07 (prototype-scope rubric) | **Still required by 23 Aug** — see G1b. Not covered by the signed letter |

---

## Contents

| Part | § | Section |
|:---|---:|:---|
| **I — Definition** | 1 | Purpose, scope and conventions |
| | 2 | Deliverables and acceptance criteria |
| **II — Plan** | 3 | Work breakdown structure |
| | 4 | Schedule, milestones and gates |
| | 5 | Organisation and roles |
| **III — Method** | 6 | Delivery approach |
| | 7 | Requirements traceability matrix |
| **IV — Control** | 8 | Risk register |
| | 9 | Assumptions, dependencies and constraints |
| | 10 | Change control and feature freeze |
| | 11 | Communications, reporting and decision log |
| | 12 | Deferred scope — product backlog |
| **Appendices** | A | Defense demonstration runbook |
| | B | Firmware review checklist |
| | C | Glossary and abbreviations |

---
---

# Part I — Definition

## 1. Purpose, scope and conventions

### 1.1 Purpose

This plan defines what Team 9 will build, in what order, by whom, and against which acceptance
criteria, in the 39 days between 23 August and 1 October 2026. It is the schedule of record. Where
it conflicts with any earlier planning document, this plan governs.

### 1.2 Objective and definition of success

The objective is a **prototype defense**, not a final defense. Success is defined as all three of
the following:

1. Every deliverable in §2 accepted against its stated criteria, or formally deferred to §12 with a
   target date;
2. The thesis contribution demonstrated live under conditions the team controls;
3. Every requirement in §7 either satisfied or traceably deferred with a scheduled verification
   date.

A demonstration that shows less but is fully accounted for satisfies this definition. A
demonstration that shows more but cannot state what remains unverified does not.

### 1.3 In scope

Eleven deliverables, DEL-01 through DEL-11, defined in §2. DEL-11 (end-to-end integration) is
classified **stretch**: planned, resourced and targeted, but not load-bearing for the defense.

### 1.4 Out of scope

Nine items, BL-01 through BL-09, each carrying a target date, are held in the deferred-scope backlog
at §12. Deferred items are declared to the panel proactively — Appendix A, item 10.

### 1.5 Document conventions

Identifier schemes used throughout. Each identifier is unique across the project document set.

| Prefix | Meaning | Defined in | Example |
|:---|:---|:---|:---|
| `R1`–`R10` | System requirement | `SYNCRO-edge-compute-alternatives.md` §3 | R6 — offline timer cache |
| `DEL-nn` | Deliverable | §2 | DEL-06 |
| `WP-nnn` | Work package | §3 | WP-207 |
| `G1`–`G6` | Schedule gate — go/no-go decision point | §4.2 | G3 |
| `RR-n` | External firmware review round | §4.2 | RR-2 |
| `RC-A/B/C` | Firmware review class | §6.4 | RC-A |
| `RSK-nn` | Risk register entry | §8 | RSK-01 |
| `A-nn` / `D-nn` / `C-nn` | Assumption / dependency / constraint | §9 | A-07 |
| `BL-nn` | Deferred-scope backlog item | §12 | BL-04 |
| `D1`–`D8` | Panel disposition | `SYNCRO-panel-dispositions-signed.md` | D8 console |

Workstream numbering: **1** host AI pipeline · **2** edge unit · **3** research methods and
compliance · **4** integration (stretch) · **5** defense readiness and project management.

---

## 2. Deliverables and acceptance criteria

Each deliverable has one accountable owner, one acceptance gate, and criteria that can be assessed
as satisfied or not satisfied without further judgement.

| ID | Deliverable | Req | WS | Owner | Acceptance criteria | Evidence | Gate |
|:---|:---|:---|:---:|:---|:---|:---|:---|
| **DEL-01** | Host conversational pipeline: wake word → capture → STT → dialogue Nodes 1–4 → LLM → TTS → speech output | R1, R4 | 1 | Almedejar | A spoken utterance to a USB microphone produces synthesized speech output through the full node chain, repeatably, with no manual intervention between stages | Recorded session; per-stage logs | G3 |
| **DEL-02** | Affect classification branch: openSMILE eGeMAPS → scikit-learn classifier → macro-F1 result | — | 1 | Almedejar | A macro-F1 figure exists, produced under speaker-independent cross-validation (`GroupKFold` grouped by speaker), with the methodology documented | Script or notebook; confusion matrix; method note | G3 |
| **DEL-03** | Node 4 policy table with decision-trace capture | — | 1 | Almedejar | Five rules over stress level × deadline state, resolved deterministically rather than by model judgement; every interaction emits a trace identifying the rule that fired | Policy table; trace output for a live interaction | G5 |
| **DEL-04** | End-to-end latency budget, measured per stage | R4 | 1 | Almedejar | Every stage of a turn carries a measured duration taken from instrumented logs; the total is stated against the 1–3 s target, with any overrun attributed to a named stage | Populated latency table; figures | G6 |
| **DEL-05** | Full-duplex I2S audio path | R2 | 2 | Marimla | 2 × INMP441 capturing on I2S0 and MAX98357A playing on I2S1 **simultaneously**, sustained, without dropout | Bench recording; buffer statistics or scope capture | G2 |
| **DEL-06** | Local timer cache firing offline | R6 | 2 | Marimla | With the network physically disconnected, a timer scheduled before disconnection fires at the correct time from the RTC, using task data held in NVS | Live demonstration; recorded | G6 |
| **DEL-07** | Degradation path | R7 | 2 | Marimla | On host unreachability the unit emits an enum `degradation_reason`, queues interactions to a fixed-capacity store with defined overflow behaviour, increments an outage counter, and drains the queue on reconnection | Live demonstration; queue and counter state before and after | G6 |
| **DEL-08** | Motor actuation, hardware mute switch, status LED | R5, R8 | 2 | Marimla | Motors actuate under PWM control; the mute switch cuts capture in hardware; the LED reflects device state | Live demonstration | G6 |
| **DEL-09** | One assembled kit, powered, in an enclosure | — | 2 | Marimla | The unit operates from its own power arrangement inside an enclosure, and survives being carried, unpacked and set up without rework | Physical inspection at G6; transport test in W5 | G6 |
| **DEL-10** | Ethics amendment, drafted | — | 3 | Espinosa | A complete amendment document exists and is ready for submission. **Approval is explicitly not in scope** — see BL-07 | Draft document | Ongoing → Dec |
| **DEL-11** | *(Stretch)* End-to-end integration: wake word on device → audio to host → pipeline → synthesized speech from the unit's own speaker | R1–R4 | 4 | Both leads | The full loop completes at least once, end to end, on real hardware. Reliability is not part of the criterion | Recorded run | G5 |

### 2.1 Priority and stretch scope

**DEL-02, DEL-06 and DEL-07 are scheduled earliest.** DEL-02 addresses the risk the team rates
highest (RSK-05) and needs no hardware. DEL-06 and DEL-07 are physically performable — the
demonstration is an unplugged cable — and they cover the two requirements a panel is most likely to
assume were simulated.

**DEL-11 is stretch.** Integration carries the widest schedule variance of any element in a
fixed-date demonstration. If it has not completed by G5 (20 September), WP-401 closes and Week 4 is
spent bringing DEL-01 to DEL-09 to a high standard — RSK-06, §6.1.

---
---

# Part II — Plan

## 3. Work breakdown structure

Thirty work packages across five workstreams. Each package has one accountable owner, a scheduled
window, a predecessor where one exists, and an exit condition. Effort is expressed in calendar
windows rather than hours; the team is part-time and hour-based estimates would not be verifiable.

### WBS 1 — Host AI pipeline (Half A) · Owner: Almedejar

| WP | Work package | Owner | Window | Predecessor | Exit condition |
|:---|:---|:---|:---|:---|:---|
| **WP-101** | Platform capacity validation: `llama3.1:8b` on the RTX 4060 within the VRAM budget at `SYNCRO-redesign-15k.md` §6.1, `num_ctx` pinned to 2048, `faster-whisper small int8` loaded alongside | Marimla | 23 Aug | — | G1 answered with a timed measurement on a ~350-token request |
| **WP-102** | Host runtime scaffolding: FastAPI + Ollama + `faster-whisper` + Piper, wired end to end and driven by a USB microphone. No robot involved | Almedejar | W0 | WP-101 | Audio in, synthesized audio out, on the host alone |
| **WP-103** | Dialogue graph Nodes 1–4 on LangGraph, with the production policy table and decision-trace capture from the first commit | Almedejar | W1–W3 | WP-102 | DEL-01, DEL-03 acceptance criteria met |
| **WP-104** | Affect branch: openSMILE eGeMAPS v02 → `StandardScaler` → `SVC(rbf, class_weight="balanced")`, evaluated with `GroupKFold` grouped by speaker | Almedejar | W1 | — | DEL-02: macro-F1 reported with method documented |
| **WP-105** | Transport layer: WebSocket audio endpoints, request queue with instrumented depth, per-stage latency logging | Almedejar | W2 | WP-102 | Endpoints serve the edge unit; every stage emits a timestamped record |
| **WP-106** | Firmware module specifications for the RC-A modules: requirement, interface, invariants, failure modes | Almedejar | W2 | — | Ring buffer and FSM specifications issued to WP-205 |
| **WP-107** | On-device wake word: Porcupine access key, model, frame-length alignment to the ring buffer; false-accept and false-reject measured in a real room | Almedejar | W3 | WP-205 | Measured rates recorded and defensible |
| **WP-108** | Latency budget: populate the per-stage table from real measurements; produce figures | Almedejar | W2–W4 | WP-105 | DEL-04 acceptance criteria met |

### WBS 2 — Edge unit (Half B) · Owner: Marimla

| WP | Work package | Owner | Window | Predecessor | Exit condition |
|:---|:---|:---|:---|:---|:---|
| **WP-201** | Procurement, both tracks, single order on day one: 2 × ESP32 classic and 2 × ESP32-S3 N16R8/N8R8, 4 × INMP441, 2 × MAX98357A, speakers, TB6612FNG, 2 × JGA12-N20, switch, LED, perfboard | Marimla | 23 Aug | — | Orders placed and confirmed. **The S3 part number must carry the `R8` suffix** — see RSK-12 |
| **WP-202** | Board bring-up and audio wiring. PSRAM confirmed present via `ESP.getPsramSize()` | Marimla | W0 (Fri–Sun) | WP-201 | Non-zero PSRAM reported; audio parts wired |
| **WP-203** | Full-duplex I2S validation under ESPHome `voice_assistant`, no C written | Marimla | 30 Aug | WP-202 | DEL-05 acceptance criteria met at G2 |
| **WP-204** | Audio path bench characterisation: sample rates, buffer sizes, absence of clicks | Marimla | W1 | WP-203 | Clean sustained capture and playback at the selected settings |
| **WP-205** | Delivered firmware: I2S capture into a static ring buffer, WebSocket client, playback path. AI-authored per §6.2, bench-debugged on hardware | Marimla | W2 | WP-106, WP-204 | Audio moves board → host → board (G4) |
| **WP-206** | Enclosure, power arrangement, cable management | Marimla | W3 | WP-202 | DEL-09 acceptance criteria met |
| **WP-207** | R6 local timer cache: day's task list and schedule in NVS; timers fired from the RTC | Marimla | W4 | WP-205 | DEL-06 acceptance criteria met and performable on demand |
| **WP-208** | R7 degradation path: enum `degradation_reason`, fixed-capacity queue with defined overflow, outage counter, D7 fallback | Marimla | W4 | WP-205 | DEL-07 acceptance criteria met and performable on demand |
| **WP-209** | R5 motor control, R8 mute switch and status LED | Marimla | W4 | WP-202 | DEL-08 acceptance criteria met |
| **WP-210** | Transport-state packing and test | Marimla | W5 | WP-206 | Kit packs, travels, unpacks and operates without rework |

### WBS 3 — Research methods and compliance · Owner: Espinosa

| WP | Work package | Owner | Window | Predecessor | Exit condition |
|:---|:---|:---|:---|:---|:---|
| **WP-301** | Adviser consultation on the privacy claim. Conducted in person, not by email | Espinosa | 23 Aug | — | G1b answered and recorded |
| **WP-302** | Ethics amendment drafting. Runs beyond this plan to December | Espinosa | W0–W5 → Dec | WP-301 | DEL-10 acceptance criteria met |
| **WP-303** | Consent materials rewritten against the revised data boundary | Espinosa | W1 | WP-301 | Materials consistent with the approved architecture |
| **WP-304** | D8 console stub: task entry and self-report only | Espinosa | W1 | — | Stub accepts task entry and self-report; full console is BL-05 |

### WBS 4 — Integration (stretch) · Owner: both leads

| WP | Work package | Owner | Window | Predecessor | Exit condition |
|:---|:---|:---|:---|:---|:---|
| **WP-401** | Integration push: wake word on the device → audio to host → STT → graph → LLM → TTS → audio returned to the unit's own speaker | Almedejar, Marimla | W3 | WP-107, WP-205 | DEL-11 acceptance criteria met at G5. **On a G5 no-go this package is closed, not extended** |

### WBS 5 — Defense readiness and project management · Owner: Espinosa

| WP | Work package | Owner | Window | Predecessor | Exit condition |
|:---|:---|:---|:---|:---|:---|
| **WP-501** | Defense deck | Espinosa | W3–W4 | — | Deck complete and rehearsed |
| **WP-502** | Demo script and running order (Appendix A) | Espinosa | W4 | WP-501 | Script timed to fifteen minutes |
| **WP-503** | Video backup of demonstration items 5, 6 and 8 | Espinosa | by 26 Sep | WP-207, WP-208 | Recordings exist and play back. **Hard date, see §4.3** |
| **WP-504** | Dry runs and failure drills | All | W5 | WP-502 | Two timed dry runs completed; unanswered questions closed |
| **WP-505** | Venue and network rehearsal | All | 1 Oct | WP-504 | System verified in the actual room, on the actual network, before the panel is seated |
| **WP-506** | Gate decision log and build log (§11.3) | Espinosa | Continuous | — | Every gate decision recorded on the day it was taken |

---

## 4. Schedule, milestones and gates

### 4.1 Schedule summary

| Week | Dates | Almedejar — WS1 | Marimla — WS2 | Espinosa — WS3/5 | Gates |
|:---|:---|:---|:---|:---|:---|
| **W0** | Sun 23 – Sun 30 Aug | WP-102 host scaffolding | WP-201 procurement (day one) · WP-202 bring-up · WP-203 | WP-301 adviser consultation · WP-302 begins | **G1**, **G1b** (23rd) · **G2** (30th) |
| **W1** | Mon 31 Aug – Sun 6 Sep | WP-103 Nodes 1–4 · **WP-104 affect branch** | WP-204 bench characterisation · WP-205 begins | WP-303 consent · WP-304 D8 stub | **G3** (6th) |
| **W2** | Mon 7 – Sun 13 Sep | WP-105 transport · WP-106 module specs | WP-205 firmware, bench debug | WP-302 continues | **RR-1** (11th) · **G4** (13th) |
| **W3** | Mon 14 – Sun 20 Sep | WP-107 Porcupine · WP-103 trace capture | WP-206 enclosure, power, cabling | WP-501 deck begins | **RR-2** (18th) · **G5** (20th) |
| | | ← **WP-401 integration push, both leads** → | | | |
| **W4** | Mon 21 – Sun 27 Sep | WP-108 latency budget and figures | **WP-207 R6 · WP-208 R7** · WP-209 motors, mute, LED | WP-502 script · **WP-503 video by 26th** | **RR-3** (25th) · **G6 FREEZE** (26th) |
| **W5** | Mon 28 Sep – Thu 1 Oct | WP-504 dry runs, failure drills | WP-210 transport test · WP-504 | WP-504 panel rehearsal · WP-505 | **DEFENSE** (1 Oct) |

### 4.2 Milestone and gate definitions

A gate is a binary decision with a named decision authority and a defined no-go action. **A missed
gate changes the plan on the same day.** It does not roll silently into the following week.

| Gate | Date | Entry criteria | Decision question | Authority | Exit — go | Exit — no-go |
|:---|:---|:---|:---|:---|:---|:---|
| **G1** | Sun 23 Aug | Host machine available; Ollama installed | Does `ollama run llama3.1:8b` run at usable speed on the RTX 4060, inside the VRAM budget at `SYNCRO-redesign-15k.md` §6.1 (~6.5-7.4 GB of 8 GB)? | Marimla | Proceed with WP-102 | **Stop. The architecture is invalid.** Re-triage before any expenditure — RSK-02 |
| **G1b** | Sun 23 Aug | Adviser meeting held in person | Has the adviser confirmed the privacy claim can change? | Espinosa | Proceed on the current architecture | Escalate the same day — RSK-01, §8.1 |
| **G2** | Sun 30 Aug | Boards in hand; WP-202 complete | Does full-duplex I2S work under ESPHome with no C written? | Marimla | Proceed to WP-205 | Diagnose per RSK-04; fall back to the classic ESP32 per RSK-03 if the cause is procurement |
| **G3** | Sun 6 Sep | WP-102, WP-103, WP-104 substantially complete | Is Half A demonstrable end to end, and is the macro-F1 figure known? | Almedejar | Proceed to WP-105 | Reduce Node 4 depth and preserve the pipeline. **The macro-F1 figure is not optional** — RSK-05 |
| **G4** | Sun 13 Sep | WP-105 and WP-205 complete | Does audio move board → host → board? | Both leads | Proceed to WP-401 | DEL-11 drops to stretch-only; both halves still demonstrate independently |
| **G5** | Sun 20 Sep | WP-401 attempted | Has the full loop run once, in any quality? | Both leads | Retain DEL-11 in the running order at position 8 | Accept the two-halves demonstration. **Close WP-401** — RSK-06 |
| **G6** | Sat 26 Sep | All W4 work packages complete | **FREEZE** | All | Not a decision. Change control per §10 applies from this date | — |

**External firmware review rounds.** RR-1 (Fri 11 Sep), RR-2 (Fri 18 Sep) and RR-3 (Fri 25 Sep)
run alongside the gates but are not schedule gates: they gate **merge quality**, not the schedule.
Scope and rationing are defined in §6.4.

### 4.3 Fixed-date constraints

Three dates do not move. Everything between them is negotiable against them.

| Date | Constraint | Consequence of slip |
|:---|:---|:---|
| Sun 23 Aug | G1 and G1b, both on day one | Every downstream decision rests on these two answers; a slip propagates through the whole plan |
| Sat 26 Sep | G6 feature freeze, and WP-503 video backup | Post-freeze feature work is the most common cause of a failed fixed-date demonstration |
| Thu 1 Oct | Defense | External |

### 4.4 Weekly execution detail

Work packages, owners, windows and exit conditions are in §3 and are not restated here. This section
states each week's objective, its gates, and anything that is not derivable from §3.

**W0 · 23-30 Aug — confirm or invalidate the architecture. Gates: G1, G1b (23rd) · G2 (30th).**
Four activities in flight by the end of day one; no item waits on any other. G1 is roughly fifteen
minutes. WP-201 orders **both** board tracks in a single order the same day. G1b is in person, not
by email. At WP-202, `ESP.getPsramSize()` returning zero means the wrong SKU arrived — RSK-12.
*Exit: architecture confirmed, hardware on the bench, privacy question answered, Half A produces
speech.*

**W1 · 31 Aug-6 Sep — Half A becomes real. Gate: G3 (6th).**
WP-104 is scheduled here because it is the single highest-value artifact of the sprint: it addresses
the risk the team rates largest, needs no hardware, and a result below macro-F1 0.70 is worth six
weeks of warning rather than six days (RSK-05). The `GroupKFold` constraint is what makes the number
defensible — a random split leaks speaker identity between folds and produces a figure that does not
generalise. *Exit: Half A demonstrates end to end and the macro-F1 figure exists.*

**W2 · 7-13 Sep — establish the protocol boundary. Gates: RR-1 (Fri 11th) · G4 (Sun 13th).**
WP-105 uses plain WebSocket for the demonstration; TLS and per-device tokens are BL-03. WP-106
produces the ring-buffer and FSM module specifications, which are RC-A and are written to the
standard in §6.4. Framing, audio format and the downlink contract are fixed by
`../realsearch/transport-framing-decision.md` and are not open at this point. RR-1 covers the ring
buffer and ISR-shared state. *Exit: audio moves board -> host -> board.*

**W3 · 14-20 Sep — integration, classified stretch. Gates: RR-2 (Fri 18th) · G5 (Sun 20th).**
First success is expected to be unpolished; that is within the DEL-11 acceptance criterion. WP-107
measures false accepts and false rejects in a real room — the panel is expected to ask. WP-206
physical robustness is an acceptance criterion of DEL-09, not a finishing touch. RR-2 covers the FSM
transition function, transport and reconnect. **If the loop has not run by Sunday 20th, WP-401
closes** and Week 4 goes to bringing both halves to a high standard — RSK-06. *Exit: the full loop
has run once; quality is not assessed at this gate.*

**W4 · 21-27 Sep — complete the differentiating deliverables, then freeze. Gates: RR-3 (Fri 25th) ·
G6 FREEZE (Sat 26th).**
WP-207 and WP-208 must be *performable on demand*: pull the cable and the timer still fires;
disconnect, interact, reconnect, show the queue drain. WP-503 video backup is recorded by Saturday
26th — hard date, §4.3. RR-3 is a final pass over RC-A and RC-B together. *Exit: 26 September,
feature freeze; change control per §10 applies from this point.*

**W5 · 28 Sep-1 Oct — rehearse. No new functionality is built this week.**
Mon 28: full timed dry run, Espinosa acting as the panel; record every question that could not be
answered. Tue 29: close those questions; fix demo-blocking defects only — anything else is
reclassified as a known limitation and declared per §10.3. Wed 30: second dry run plus failure
drills (network drops, wake word misfires, model stalls); WP-210 pack and test the kit in transport
state. Thu 1 Oct: arrive early, verify in the actual room on the actual network before the panel is
seated.

---

## 5. Organisation and roles

### 5.1 Team and roles

Role assignments follow those recorded in `../archive/REVIEWPANELENGG-TEAM9.md`. The D1–D8 dispositions
those assignments serve are now signed — `SYNCRO-panel-dispositions-signed.md`.

| Name | Role | Accountable for | Gates owned | Peak load |
|:---|:---|:---|:---|:---|
| **Almedejar** | AI/software lead | Workstream 1 in full · firmware **specification** and review · the protocol boundary · the latency budget | G3 | W1 |
| **Marimla** | Hardware lead | Workstream 2 in full — board, wiring, bench debugging, firmware integration, chassis, power | G1, G2 | W4 |
| **Espinosa** | Methods lead | Workstream 3 and 5 — ethics amendment, consent materials, D8 stub, defense materials, the study-design half of the defense | G1b | W4 |
| **Morgan** | External firmware reviewer (NASA) | Firmware review at three scheduled rounds, approximately six hours in total. **Not a build resource** | — | — |
| **Adviser** | Project adviser | A-01 privacy claim · A-07 prototype-scope rubric | — | — |

**The division that matters.** Almedejar writes the firmware specification and reviews the result;
Marimla owns the board and everything physical. Neither writes embedded C from a blank file.

*Rationale: this keeps R6 and R7 — which are Almedejar's requirements — designed by their owner,
while bench work stays with the person who has the hardware in front of them.*

### 5.2 Accountability

**Every work package in §3 carries exactly one accountable owner, and every deliverable in §2
carries exactly one.** That is the accountability record; no separate matrix is maintained. Where
two names appear on one package (WP-401, WP-504) the work is genuinely joint and the accountable
party is the gate authority named in §4.2.

### 5.3 External reviewer engagement model

The external reviewer is a **fixed, non-expandable resource**: approximately six hours across three
scheduled rounds, batched, not on-demand. The engagement rules are:

1. Reviews are **batched into the three scheduled rounds** — RR-1, RR-2, RR-3. No ad-hoc requests.
2. **No first draft is ever submitted.** Every module reaches the reviewer having already passed
   self-review by Almedejar and a bench run by Marimla.
3. Review effort is spent on correctness that testing cannot reach. Anything a compiler or a bench
   run would have caught is out of scope for the round.
4. Reviewer availability is a dependency (D-03), not a commitment the team controls. Contingency is
   RSK-08.

---
---

# Part III — Method

## 6. Delivery approach

### 6.1 Two-workstream strategy

**The demonstration does not depend on end-to-end integration landing.** Workstreams 1 and 2 are
independently demonstrable, and each carries a defensible portion of the contribution on its own.

| | **Half A — the AI pipeline (WS1)** | **Half B — the edge unit (WS2)** |
|:---|:---|:---|
| Runs on | The host, with a USB microphone and speaker | The ESP32-S3, on a bench |
| Contains | Wake word, STT, openSMILE, Nodes 1–4, LLM, Piper | Full-duplex I2S, timer cache, degradation path, motors, mute and LED |
| Language | Python — the team's existing competence | Embedded C — AI-authored, expert-gated |
| Hardware risk | None | High |
| Demonstrates | The thesis contribution in full | R2, R5, R6, R7, R8 |
| Ready by | **6 September** (G3) | **20 September** (G5) |

If the halves meet by the freeze, the integrated system is demonstrated. If they do not, the
demonstration is two working halves plus a measured latency budget, and the account remains coherent
and complete.

*Rationale: integration is where fixed-date demonstrations most commonly fail, and it is the element
that cannot be scheduled with confidence. Structuring the deliverable set so that integration is
additive rather than load-bearing is what makes the 1 October date a plan rather than a gamble.*

### 6.2 Firmware development model: AI-authored, expert-gated

The constraint that invalidated the previous schedule was that a Python team cannot acquire embedded
C competence inside a plan with no slack. That constraint is accepted. It is addressed by changing
**who writes the C**, not by compressing the learning.

The claim for this model is not that it saves hours — it saves some — but that it **collapses
variance**. "Become competent enough to write correct ISR-safe ring-buffer code" takes 40 hours or
200 depending on the individual, and a 39-day sprint cannot absorb that spread. The model converts
an open-ended *learning* risk into a bounded *specify-review-verify* cost, which can be placed on a
calendar.

**What the model does not remove**, all three of which are scheduled explicitly:

| Retained cost | Where it is scheduled |
|:---|:---|
| Reading fluency — the team must be able to debug this code under time pressure | WP-106 specification work; RC-A self-review |
| Bench debugging — an oscilloscope and a mis-wired microphone do not compress | WP-204, WP-205 |
| Raised verification burden — code the team did not write must be tested harder | Appendix B checklist; RR-1 to RR-3 |

### 6.3 Development workflow

```
  Almedejar writes a module specification    requirement, interface, invariants, failure modes
        |
        v
  AI authors the C                           NASA/JPL Power of 10, house style per ../sandbox/
        |
        v
  Almedejar reads and self-reviews           no first draft is forwarded
        |
        v
  Marimla builds and bench-tests             real hardware, real audio
        |
        v
  External reviewer gates RC-A only          blocking; batched into RR-1, RR-2, RR-3
        |
        v
  Merge
```

### 6.4 Review classes

| Class | Modules | Treatment |
|:---|:---|:---|
| **RC-A** | Audio ring buffer and its invariant · anything an ISR touches or shares · the FSM transition function · transport and reconnect | **Blocking merge.** Reviewed at RR-1 (11 Sep), RR-2 (18 Sep), RR-3 (25 Sep) |
| **RC-B** | Motor control · mute and LED · NVS schema · logging | Batched with RC-A submissions; no merge dependency |
| **RC-C** | Build files · serial formatting · test harness | Team review only |

The RC-A scope is defined by Appendix B: a module belongs to RC-A when its failure modes are ones
that survive a clean compile and a happy-path bench run.

### 6.5 Coding standard

**NASA/JPL "Power of 10."** Ten rules on one page. `../sandbox/` is already written to it, and the
standard exists specifically to make embedded C reviewable by an engineer who did not write it.

| Rule applied | Effect |
|:---|:---|
| No dynamic allocation after initialization | Removes an entire class of runtime failure from the review surface |
| No recursion; fixed loop bounds | Stack usage is statically bounded |
| Every return value checked | I2S and NVS failures become loud rather than silent |
| Assertions retained in the delivered build | Invariant violations surface on the bench, not in the field |
| All data declared at the smallest scope | Reduces the shared state an ISR review must consider |

*Rationale: mandating this standard is what makes a six-hour external review budget sufficient
rather than notional. Without it, the review cost per module is unbounded.*

### 6.6 Platform and framework decisions

| Decision | Selection | Basis |
|:---|:---|:---|
| G2 validation path | **ESPHome**, then discarded | Proves the audio path in days with no C written, which is precisely what a hardware-validation gate requires |
| Delivered firmware | **Arduino framework**, dropping to ESP-IDF calls (`i2s_std`, `esp_timer`, NVS) where control is required | It is the only one of the three candidate paths that preserves **Picovoice Porcupine**, the wake-word engine already specified and defended |
| Wake-word engine | **Porcupine** (openWakeWord as fallback per R1) | Retaining it avoids a second wake-word change on top of Objective 3's third platform revision, which the manuscript would otherwise have to absorb |
| Target board | **ESP32-S3 N16R8 / N8R8** | PSRAM is mandatory. A part number without the `R8` suffix carries 512 KB and does not meet the requirement — RSK-12 |

---

## 7. Requirements traceability matrix

All ten system requirements from `SYNCRO-edge-compute-alternatives.md` §3, mapped to deliverables,
work packages, verification gates and evidence. Each requirement is restated in full below, so this
table is readable without the source document. Requirements not satisfied in the prototype are
listed with their deferral reference — this table is the source for the declaration at Appendix A,
item 10.

| Req | Requirement | Deliverable | Work package | Verified at | Evidence | Prototype status |
|:---|:---|:---|:---|:---|:---|:---|
| **R1** | Always-on wake-word detection (Porcupine primary, openWakeWord fallback) | DEL-01, DEL-11 | WP-102, WP-107 | G3 (host), G5 (device) | Measured false-accept and false-reject rates in a real room | **Satisfied on host; on-device subject to G5** |
| **R2** | Full-duplex I2S — 2 × INMP441 in, MAX98357A out | DEL-05 | WP-203, WP-205 | G2 | Sustained simultaneous capture and playback | **Satisfied** |
| **R3** | Wi-Fi to the shared host over an encrypted mesh (Tailscale/WireGuard) | — | WP-105 | — | — | **Deferred — BL-03.** Plain WebSocket on a controlled network for the demonstration. The security property must be restated in the manuscript |
| **R4** | Stream audio up, play synthesized audio back, within a 1–3 s end-to-end budget | DEL-04, DEL-01 | WP-105, WP-108 | G6 | Per-stage measured latency table | **Satisfied and measured** |
| **R5** | Motor actuation — TB6612FNG PWM, 2 × JGA12-N20 | DEL-08 | WP-209 | G6 | Live actuation | **Satisfied** |
| **R6** | Cache the day's task list and timer schedule locally; timers fire with no network | DEL-06 | WP-207 | G6 | Live demonstration with the cable disconnected | **Satisfied** |
| **R7** | Degrade to the D7 pop-up path when the host is unreachable; log `degradation_reason`, queue interactions, log outages | DEL-07 | WP-208 | G6 | Live demonstration; queue drain on reconnection | **Satisfied** |
| **R8** | Hardware mute switch and status LED | DEL-08 | WP-209 | G6 | Live demonstration | **Satisfied** |
| **R9** | Low power (1–2 W), passive cooling, safe unattended in a participant's home | DEL-09 (partial) | WP-206 | — | Enclosure and power arrangement only | **Partially satisfied.** Unattended-safety verification requires BL-02 |
| **R10** | Survive a 10-day unattended deployment without a service visit | — | — | — | — | **Deferred — BL-02.** Cannot be compressed; the test takes ten days |

**Concurrency.** The 8-client figure in `SYNCRO-redesign-15k.md` §6.2 is an **analytic bound, not a
measurement**. With one kit the measured ceiling is 1. It is presented at the defense as a
projection, with the measurement scheduled — see BL-09 and RSK-11.

---
---

# Part IV — Control

## 8. Risk register

Exposure is the product of likelihood and impact, expressed as High / Medium / Low. Response types
follow the standard set: **Avoid · Mitigate · Transfer · Accept**.

| ID | Risk | L | I | Exp | Owner | Trigger / detection | Response | Contingency |
|:---|:---|:---:|:---:|:---:|:---|:---|:---|:---|
| **RSK-01** | The adviser does not approve the change to the privacy claim, invalidating the architecture being built | M | **Critical** | **H** | Espinosa | G1b answered "no" on 23 Aug | **Avoid** — resolve on day one, in person, before any expenditure | §8.1 |
| **RSK-02** | The host GPU cannot run an 8B model within the VRAM budget | L | **Critical** | **M** | Marimla | G1 timing or VRAM measurement on 23 Aug | **Avoid** — validate before ordering | Architecture is invalid; stop and re-triage before spending |
| **RSK-03** | Procurement slips; boards not in hand by 29 Aug | M | H | **H** | Marimla | Supplier confirmation not received, or delivery not made by 29 Aug | **Mitigate** — order both tracks on day one, single order | §8.2 |
| **RSK-04** | Full-duplex I2S fails at G2 | L | H | **M** | Marimla | G2 answered "no" on 30 Aug | **Mitigate** — validate on a no-code path so the failure isolates to hardware | §8.3 |
| **RSK-05** | The affect classifier returns macro-F1 below 0.70 | M | M | **M** | Almedejar | WP-104 result, Week 1 | **Mitigate** — schedule earliest, report the method honestly | §8.4 |
| **RSK-06** | Integration does not land by G5 | **H** | L | **M** | Both leads | G5 answered "no" on 20 Sep | **Accept** — DEL-11 is classified stretch precisely for this reason | §8.5 |
| **RSK-07** | The live demonstration fails in the room, on unfamiliar network and acoustics | M | M | **M** | Espinosa | Observed at WP-505 or during the defense | **Mitigate** — WP-503 video backup by 26 Sep | §8.6 |
| **RSK-08** | The external reviewer becomes unavailable for one or more rounds | M | M | **M** | Almedejar | Round not scheduled or not delivered | **Accept with disclosure** — the rounds gate merge quality, not the schedule | §8.7 |
| **RSK-09** | A defect class in AI-authored firmware repeatedly escapes review | L | H | **M** | Almedejar | The same defect class recurs across two review rounds | **Mitigate** — widen RC-A scope, add bench tests from Appendix B, escalate the schedule | Move affected modules to team-authored code with reviewer pairing |
| **RSK-10** | The defense rubric requires a complete system rather than a prototype | L | **Critical** | **M** | Espinosa | Rubric published or confirmed by the adviser | **Avoid** — confirm A-07 explicitly with the adviser; it is one question | Re-scope immediately. §2 and §12 both rest on this distinction |
| **RSK-11** | The analytic concurrency bound is read by the panel as a measurement | M | H | **M** | Almedejar | Any slide or statement presenting the 8-client figure without qualification | **Avoid** — state it as a projection with the measurement scheduled | Correct on the spot and cite BL-09 |
| **RSK-12** | ESP32-S3 boards arrive without PSRAM (part number lacking the `R8` suffix) | M | H | **M** | Marimla | `ESP.getPsramSize()` returns zero at WP-202 | **Avoid** — require `R8` in the listing at order time | Treat as RSK-03; fall back to the classic ESP32 path |
| **RSK-13** | The panel rules against one or more of the three reconsiderations (D4, D6, D7), or declares an item a *condition of approval* rather than a recommendation | M | H | **M** | Espinosa | Panel response to the letter of 20 Aug, or no response before 1 Oct | **Mitigate** — the letter asks the question explicitly and offers a discussion before the prototype defense | §8.4 |

### 8.1 RSK-01 — the privacy claim is not approved (G1b)

**The highest-consequence risk in this plan, and it is not a technical one.**
`SYNCRO-redesign-15k.md` §10 item 1 establishes that moving audio across a network boundary is a
thesis-level decision on which everything else rests. If the adviser declines, the architecture
under construction is the wrong one, and 39 days would be spent demonstrating a system that cannot
ship.

**Response:** this is a day-one, in-person conversation. It is not delegated to email, and no
expenditure is committed before it is answered.

> **The signed panel-disposition letter does not close this risk.** The adviser's signature on
> `SYNCRO-panel-dispositions-signed.md` (20 Aug 2026) approves the **D1–D8 dispositions** and
> nothing else. That letter never raises the privacy claim. A-01 is a separate question, G1b
> still runs on 23 August, and RSK-01 remains the highest-consequence risk in this plan.

### 8.2 RSK-03 — boards do not arrive by 29 August

| Slip | Response |
|:---|:---|
| 1–5 days | Absorbed. Week 1 is bench-proving work and compresses |
| More than one week | Build Half B on the **classic ESP32**. It also carries two I2S peripherals, so full-duplex remains available. What it lacks is PSRAM, which matters for a production configuration of wake-word model plus TLS plus buffers, and much less on a bench with small buffers and no TLS. The defense states plainly that the production board is the S3, and why |
| Nothing arrives | Half A demonstrates alone; Half B is presented as design and specification. A weak outcome, but not a failing one for a *prototype* defense |

### 8.3 Notes on the remaining risks

- **RSK-04, I2S at G2.** G2 deliberately uses a no-code path so a failure isolates to hardware.
  **Check the microphone L/R channel-select pins first.** If the failure is genuinely on the S3 the
  platform decision was wrong, and `SYNCRO-edge-compute-alternatives.md` §9 step 5 (Orange Pi Zero
  2W / Radxa Zero 3W, retaining Linux and Python) becomes live — but not inside 39 days. For this
  defense: demonstrate Half A and report the finding.
- **RSK-05, macro-F1 below 0.70.** Not a demonstration failure — a finding, and a legitimate one to
  present. `../archive/REVIEWPANELENGG-TEAM9.md` already names this the largest project risk and
  already specifies the mitigation: the D2 idle-time signal as a second, low-cost,
  language-independent context signal. Present the figure, the speaker-independent method that
  produced it, and the mitigation path. A measured negative result carries more weight with a panel
  than an unmeasured claim.
- **RSK-06, integration.** Planned for. WP-401 closes at a G5 no-go; Week 4 is not spent pursuing it.
- **RSK-07, the room.** Video backup recorded 26 September (WP-503). Narrate the intended behaviour,
  play the recording, continue. **Do not debug in front of the panel** — Appendix A.3.
- **RSK-08, reviewer availability.** The rounds gate merge quality, not the schedule. If a round
  slips, firmware merges on the team's own testing — but **RC-A modules that have not been externally
  reviewed are named as such in the defense**, not presented as verified.

---

### 8.4 RSK-13 — the panel rules against a reconsideration, or names a condition of approval

The letter of 20 August 2026 disposes of all eight panel recommendations and asks the panel to
reconsider three: **D4** (email notifier — declined, substitute built), **D6** (hardware ambience
and music — deferred to the follow-up robotics study) and **D7** (pop-up notification — adopted as
a fallback channel only, not as the primary one).

**The adviser's signature is not the panel's ruling.** It approves the dispositions as Team 9's
position and authorises their transmission. The panel has not answered.

**The consequential half of this risk is the second question the letter asks:** whether any of the
eight items was a *condition of approval* rather than a recommendation. Only D4 and D7 change if
so — but they change a great deal. If screen delivery were mandated as the **primary** channel,
that contradicts the attention-preservation argument which is the study's primary thesis, and it
is a conversation about the thesis rather than about the build.

| Panel outcome | Consequence for this plan |
|:---|:---|
| No response before 1 Oct | Build proceeds on the signed dispositions. State the position plainly at the defense and note the letter is outstanding |
| D6 or D4 decline upheld | No change. Both are already declined or deferred with a substitute recorded |
| D7 mandated as primary channel | **Thesis-level.** WP-208 changes from a degradation path to a delivery channel, and §6.1's attention-preservation argument must be re-stated. Escalate to the adviser the same day |
| D4 mandated as a deployed mail connector | Out of scope for the study on authorization grounds, not technical ones — the letter's reasoning stands. Escalate; do not build |

**Response:** Espinosa tracks the panel response. The distinction is already requested in writing,
which is the mitigation — an unasked question cannot be answered before the defense.

---

## 9. Assumptions, dependencies and constraints

### 9.1 Assumptions

An assumption is a condition treated as true for planning purposes. Each carries an invalidation
trigger and a response.

| ID | Assumption | Invalidated by | Response | Risk |
|:---|:---|:---|:---|:---|
| **A-01** | The adviser approves the change to the privacy claim | A "no" at G1b | §8.1 — stop and re-scope | RSK-01 |
| **A-02** | The RTX 4060 runs an 8B model within the VRAM budget | A "no" at G1 | Architecture is invalid; re-triage | RSK-02 |
| **A-03** | Procurement succeeds; boards in hand by 29 Aug | Stock or shipping failure | §8.2 | RSK-03 |
| **A-04** | The ESP32-S3 supports full-duplex I2S across two controllers | A "no" at G2 | §8.3 | RSK-04 |
| **A-05** | The external reviewer is available for approximately six hours across three rounds | Her schedule | §8.7 | RSK-08 |
| **A-06** | AI-authored firmware plus expert review is sound for RC-A modules | A defect class the review misses repeatedly | Widen RC-A, add bench tests from Appendix B, escalate the schedule | RSK-09 |
| **A-07** | 1 October is a **prototype** defense, not a final one | A rubric requiring a complete system | Re-scope immediately | RSK-10 |
| **A-08** | The panel accepts the three reconsiderations (D4, D6, D7), or does not rule before 1 Oct | A panel ruling against any of the three, or any item named a *condition of approval* | §8.4 | RSK-13 |

**A-07 and A-01 each require an explicit answer from the adviser.** A-07 is one question and the
entire scope division in Part I rests on it. A-01 is not covered by the signed disposition letter —
that letter covers D1-D8 only — and is decided at G1b on 23 August, §8.1.

### 9.2 Dependencies

| ID | Dependency | Owner of the dependency | Needed by | If unmet |
|:---|:---|:---|:---|:---|
| **D-01** | Adviser availability for an in-person conversation on 23 Aug | Adviser | 23 Aug | G1b slips; RSK-01 exposure rises daily |
| **D-02** | Supplier stock for ESP32-S3 N16R8/N8R8 and the audio parts | Suppliers | 23 Aug order, 29 Aug delivery | RSK-03, §8.2 |
| **D-03** | External reviewer availability, ~6 h across RR-1 to RR-3 | External reviewer | 11, 18, 25 Sep | RSK-08, §8.7 |
| **D-04** | Host machine with the RTX 4060, available for the full window | Team | 23 Aug onward | Workstream 1 stops; no fallback within budget |
| **D-05** | Picovoice Porcupine access key | Almedejar | W3 (WP-107) | openWakeWord fallback per R1; wake-word claim in the manuscript changes |
| **D-06** | Defense venue and network access before the panel is seated | Institution | 1 Oct | WP-505 cannot run; RSK-07 exposure rises |

### 9.3 Constraints

| ID | Constraint | Consequence for the plan |
|:---|:---|:---|
| **C-01** | Defense date 1 October 2026 is externally fixed | The schedule is date-driven; scope is the only adjustable variable |
| **C-02** | Budget approximately ₱15,000, self-funded, no institutional support | One kit only; no spare high-value parts beyond the dual-track board order |
| **C-03** | One assembled kit | The concurrency result cannot be measured — BL-09, RSK-11 |
| **C-04** | Three-person team, part-time, carrying concurrent coursework | Effort is expressed as calendar windows, not hours; no capacity for parallel recovery work |
| **C-05** | Ethics approval budgets 45 days drafting plus 60 days review | Ethics approval cannot land before December regardless of plan changes — BL-07 |
| **C-06** | Embedded C is outside the team's existing competence | Drives the firmware model in §6.2 and the review budget in §5.3 |

---

## 10. Change control and feature freeze

### 10.1 Before the freeze (23 Aug – 26 Sep)

Scope changes within a workstream are decided by that workstream's accountable owner and recorded in
the decision log (§11.3). Changes that affect a gate date, a deliverable's acceptance criteria, or
another workstream require agreement from all three leads and a log entry.

Changes to the three fixed dates in §4.3 require plan-owner approval.

### 10.2 The freeze — G6, Saturday 26 September

From 26 September, **no new functionality is added**. This applies to all workstreams without
exception.

### 10.3 Post-freeze defect handling

Defects found after the freeze are classified on discovery:

| Class | Definition | Action |
|:---|:---|:---|
| **P1 — demo-blocking** | The defect prevents an Appendix A runbook item from completing | Fix permitted. Requires agreement from both leads and a decision-log entry. Re-run the affected runbook item afterwards |
| **P2 — known limitation** | The defect does not block any runbook item | **No fix.** Recorded as a known limitation and declared at the defense if relevant |

The P2 classification is deliberate. A known, stated limitation is an acceptable outcome for a
prototype; an untested last-minute change is not.

---

## 11. Communications, reporting and decision log

### 11.1 Cadence and escalation

A ten-minute stand-up daily: what moved, what is blocked, whether the next gate is still green.
Gate reviews happen at each gate in §4.2 with the gate authority present, and produce a written
decision-log entry the same day. External review rounds are batched — RR-1, RR-2, RR-3. Two timed
dry runs in W5.

Anything blocked for more than one working day goes to the workstream owner; anything that puts a
gate at risk or spans workstreams goes to all three leads at the stand-up; an invalidated assumption
(§9.1) or a threatened fixed date (§4.3) goes to the adviser and the plan owner.

**The gate table in §4.2 is the project tracker.** No additional tooling is warranted for a 39-day
plan with three participants.

### 11.3 Decision log

**At each gate, the answer is written down on the day it is taken:** date, question, decision, and
the action that followed. WP-506 owns this record.

*Rationale: the accumulated log is the project's build log. A prototype defense that can present its
own decision history — including the decisions that went against the plan — is in a materially
stronger position than one that cannot.*

---

## 12. Deferred scope — product backlog

Each item carries a target date. **The date is what distinguishes deferred scope from missing
scope**, and each item is declared proactively at the defense (Appendix A, item 10).

| ID | Item | Req | Reason for deferral | Target |
|:---|:---|:---|:---|:---|
| **BL-01** | OTA update | — | Not required on a bench; mandatory before any deployment | October |
| **BL-02** | 10-day unattended reliability soak | R10, R9 | Cannot be compressed — the test takes ten days | November |
| **BL-03** | TLS, pinned certificate, per-device tokens | R3 | Plain WebSocket is sufficient on a controlled bench network. **The security property must be restated in the manuscript regardless** | October |
| **BL-04** | Kit 2 | — | One kit demonstrates; two are required for fieldwork | November |
| **BL-05** | D8 PWA console, full implementation | — | Stub only in the prototype. 13–20 days per `../archive/REVIEWPANELENGG-TEAM9.md` | November |
| **BL-06** | Full SQLite schema | — | Minimal tables for the demonstration; the fieldwork schema is a separate design activity | October |
| **BL-07** | **Ethics approval** | — | Drafting starts 24 Aug. C-05 budgets 45 days drafting plus 60 days review. **No plan change alters this date** | **December** |
| **BL-08** | Any fieldwork data | — | Requires ethics approval (BL-07) and two kits (BL-04) | January 2027 |
| **BL-09** | **The concurrency result** | — | **With one kit the measured ceiling is 1, not 8** (C-03). The 8-client figure in `SYNCRO-redesign-15k.md` §6.2 is an analytic bound | Fieldwork |

**BL-09 requires particular care in presentation.** It is the contribution that replaces the claim
given up in `SYNCRO-redesign-15k.md` §4.1. Presenting a modelled bound as a measurement is the
category of error over which a panel discards an entire result. It is stated as a projection, with
the measurement scheduled — see RSK-11.

---
---

# Appendices

## Appendix A — Defense demonstration runbook

### A.1 Running order

Fifteen minutes, sequenced so that no high-risk item occupies an early position.

| # | Item | Deliverable | Placement rationale |
|---:|:---|:---|:---|
| 1 | Architecture and the edge/host split | — | Frames everything that follows. Two minutes, no hardware involved |
| 2 | **Half A live** — speak to the USB microphone; the pipeline responds | DEL-01 | Zero hardware risk. If nothing else runs, the contribution has been demonstrated |
| 3 | **The decision trace** for that interaction | DEL-03 | Establishes auditability; an adopted panel item |
| 4 | **The macro-F1 result**, with the speaker-independent method stated | DEL-02 | The largest project risk, answered with a number |
| 5 | **R6 live** — disconnect the network cable; the timer still fires | DEL-06 | Simple, physical, memorable, and the requirement a panel is most likely to assume was simulated |
| 6 | **R7 live** — interact while disconnected, reconnect, show the queue drain | DEL-07 | The degradation behaviour, performed rather than asserted |
| 7 | Motors, mute switch, status LED | DEL-08 | Fast |
| 8 | **Full integration**, if G5 held | DEL-11 | Last, because it carries the highest failure probability |
| 9 | The latency budget table | DEL-04 | Real measurements, per stage |
| 10 | **Deferred scope with dates** (§12) | — | Closes by naming what is not built, before the panel identifies it |

### A.2 Video backup

**Items 5, 6 and 8 are recorded by 26 September** (WP-503).

### A.3 Failure response

| Situation | Response |
|:---|:---|
| A live item fails | State the intended behaviour, play the recording, continue the running order |
| A question cannot be answered | Say so, state what would answer it and when it is scheduled |
| Any item overruns | Drop item 7, then item 8. Items 1–6 and 10 are not droppable |

**Do not debug in front of the panel.** Diagnosis on stage consumes the time budget and converts a
single failed item into a failed demonstration.

---

## Appendix B — Firmware review checklist

These are the failure modes that survive a clean compile and a happy-path bench run. **This list is
simultaneously the test-harness specification and the operative definition of the RC-A tier** (§6.4):
a module belongs to RC-A when it can fail in any of these ways.

| # | Failure mode | Why testing misses it |
|---:|:---|:---|
| 1 | **Ring-buffer wrap arithmetic that is plausible and wrong** — full and empty indistinguishable at the boundary; off-by-one on the spare slot | Manifests only at the wrap boundary, which a short bench run may never reach |
| 2 | **Missing `volatile`** on state shared with an interrupt handler | Correct until the optimizer changes its decision; a rebuild can introduce the failure |
| 3 | **Silent integer promotion or overflow** in sample arithmetic and tick counters | Produces plausible values rather than an error |
| 4 | **Unchecked return codes** on I2S and NVS calls | The failure is silent, not loud; the system continues in an invalid state |
| 5 | **Heap allocation introduced through a convenience library** | Violates the Power of 10 rule invisibly; fails under sustained load, not on the bench |
| 6 | **A blocking call in the audio path** | 200 ms in the wrong place is an audible click that the panel will hear |
| 7 | **Hallucinated API signatures for the wrong ESP-IDF version** | The compiler catches this. Listed so that no external review round is spent on it |

Items 1 through 6 define the RC-A review scope. Item 7 is explicitly out of scope for external
review and is caught in the build.

---

## Appendix C — Glossary

Only terms that carry a decision, a part number or a constraint. Standard pipeline components
(openSMILE, faster-whisper, Piper, Ollama, LangGraph, STT/TTS) are named in place where used.

| Term | Definition |
|:---|:---|
| **D1-D8** | Panel dispositions from the proposal defense, signed by the adviser in `SYNCRO-panel-dispositions-signed.md` and reasoned in `../archive/REVIEWPANELENGG-TEAM9.md`. D2 is the idle-time context signal; D7 the pop-up fallback path; D8 the participant console |
| **ESPHome** | A configuration-driven firmware generator for ESP32 devices. Used for G2 validation only, then discarded |
| **FSM** | Finite state machine. Here, the edge unit's interaction state controller; an RC-A module |
| **`GroupKFold`** | A scikit-learn cross-validation strategy that keeps all samples from one group — here, one speaker — within a single fold, producing speaker-independent evaluation |
| **I2S** | Inter-IC Sound. The digital audio bus connecting the microphones and amplifier. The S3 provides two independent controllers, I2S0 and I2S1, which is what makes full duplex possible |
| **INMP441** | Digital MEMS microphone with an I2S interface. Two are used, on I2S0 |
| **ISR** | Interrupt service routine. Code that runs in interrupt context; state shared with an ISR is the primary RC-A review surface |
| **JGA12-N20** | Geared DC motor used for actuation under R5 |
| **macro-F1** | The unweighted mean of per-class F1 scores. Chosen over accuracy because it does not reward a classifier that ignores minority classes |
| **MAX98357A** | I2S class-D audio amplifier driving the speaker, on I2S1 |
| **N16R8 / N8R8** | ESP32-S3 module part numbers. The digits are flash / PSRAM in megabytes. **The `R8` suffix indicates 8 MB PSRAM and is mandatory** |
| **NVS** | Non-volatile storage. The ESP32 key-value store on flash; holds the R6 task cache and the R7 queue |
| **Porcupine** | Picovoice wake-word engine. Primary under R1; its retention drives the framework decision in §6.6 |
| **Power of 10** | The NASA/JPL rules for developing safety-critical code. Ten rules, one page; the mandated coding standard for delivered firmware |
| **PSRAM** | Pseudo-static RAM. External memory on the S3 module; required for wake-word model, TLS and buffers in a production configuration |
| **TB6612FNG** | Dual motor driver used under R5 |
