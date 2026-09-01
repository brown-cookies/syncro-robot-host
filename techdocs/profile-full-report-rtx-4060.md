# GPU Residency and Latency Report

Run `20260817T024334Z`, generated 2026-08-17T02:46:52.717921Z, profile `full`.

## Detected card

NVIDIA GeForce RTX 4060 (device index 0), nameplate 8188 MiB, driver 596.21.
Laptop-part determination: no - heuristic (device name plus battery presence): no laptop keyword in the device name and no battery was detected

Every verdict in this report refers to this card and no other.

## Claims

| Claim | Measured value | Threshold | Source citation | Verdict | Procurement implication |
| --- | --- | --- | --- | --- | --- |
| GPU residency of the language model (ADDED) [DIRECT] | 100 percent of model bytes resident in VRAM | >= 100 percent of model bytes resident in VRAM | ADDED by this harness: no source in the reference documents. The proposal asserts that the model runs on the GPU but never states a residency test, so execution success was the only available signal. This metric replaces it: residency, not completion, is the pass condition. | PASS | Anything below full residency means part of the model is running on the CPU on this card, so the quoted GPU sizing does not hold and the interactive latency figures cannot be relied on for procurement. |
| Usable VRAM after desktop reserve (ADDED) [DERIVED] | 7563.5 MiB | no threshold (REPORTED) | ADDED by this harness: no source in the reference documents. The corpus budget assumes a full 8.0 GB is available to the workload; it makes no allowance for the VRAM the display driver reserves for the desktop. This value is nameplate VRAM minus the measured idle reserve on the detected card, and every budget verdict is computed against it. | REPORTED | This is the VRAM the workload can actually use on the card that was measured; the budget in the proposal is written against nameplate capacity and is therefore optimistic by the size of the desktop reserve. |
| Model weights resident (Q4_K_M) [DIRECT] | 4769.5 MiB | 4812.8-5017.6 MiB | VRAM budget figure, line item 'model weights at Q4_K_M': 4.7-4.9 GB. | FAIL | The quantised weights are the fixed floor of the budget; if they land above the quoted range the remaining headroom on an 8 GB card is smaller than the proposal assumes. |
| KV cache at context 2048 [DERIVED] | 285.112 MiB | about 256 MiB (tolerance +/-102.4) | VRAM budget figure, line item 'KV cache at context 2048': about 0.25 GB. Tolerance of 0.1 GB is an operational allowance around the word 'about' and is not itself a corpus figure. | PASS | The KV cache is the part of the budget that grows with conversation length; a larger figure here means the usable context on this card is shorter than planned. |
| CUDA runtime plus compute buffers [DERIVED] | 197.146 MiB | 819.2-1228.8 MiB | VRAM budget figure, line item 'CUDA runtime + compute buffers': 0.8-1.2 GB. | FAIL | This overhead is paid before any model bytes are loaded, so it is unavoidable capacity that cannot be recovered by changing the quantisation. |
| Speech-to-text model resident (small, int8) [DIRECT] | 362.68 MiB | 512-1024 MiB | VRAM budget figure, line item 'faster-whisper small int8': 0.5-1.0 GB. | FAIL | The speech model has to be co-resident with the language model for a voice turn to avoid a reload, so this figure competes directly with the language model for the same card. |
| openSMILE eGeMAPS feature extraction [DIRECT] | n/a | about 0 MiB (tolerance +/-16) | VRAM budget figure, line item 'openSMILE eGeMAPS': 0 GB (CPU-only by design). Tolerance of 16 MiB is an operational allowance for measurement noise in the VRAM delta and is not a corpus figure. | NOT MEASURED | Not available for procurement judgment this run: the opensmile module is not installed (No module named 'opensmile') |
| Piper speech synthesis [DIRECT] | n/a | about 0 MiB (tolerance +/-16) | VRAM budget figure, line item 'Piper TTS': 0 GB (CPU-only by design). Tolerance of 16 MiB is an operational allowance for measurement noise in the VRAM delta and is not a corpus figure. | NOT MEASURED | Not available for procurement judgment this run: the piper module is not installed (No module named 'piper') |
| Total resident VRAM during a request [DERIVED] | 5876.26 MiB | 6656-7577.6 MiB | VRAM budget figure, line item 'total resident during a request': 6.5-7.4 GB. | FAIL | This is the peak the card must absorb while a voice turn is in flight; if it exceeds usable VRAM on the target card the deployment spills to CPU and the interactive budget is gone. |
| Remaining VRAM margin during a request [DERIVED] | 1687.24 MiB | 614.4-1536 MiB | VRAM budget figure, line item 'margin': 0.6-1.5 GB. | FAIL | The margin is the buffer absorbing driver growth, a longer context, or a second concurrent allocation; a margin below the quoted range means the configuration has no room for variation in service. |
| Peak residency fits in usable VRAM [DERIVED] | true | >= 1 boolean (1.0 = peak residency fits in usable VRAM, 0.0 = it does not) | VRAM budget figure: the budget is presented as fitting inside the card, with total resident 6.5-7.4 GB against the assumed 8.0 GB capacity. | PASS | If the peak does not fit in the VRAM actually available on the detected card, the single-card assumption behind the quoted hardware cost does not hold. |
| A second full residency does not fit [DERIVED] | true | >= 1 boolean (1.0 = a second full residency does not fit, 0.0 = it would fit) | VRAM budget figure: the budget claim that the workload fits once and does not fit twice on the card. | PASS | Confirming that a second copy does not fit means one card serves one resident workload, so scaling to a second concurrent workload is a second card and not a configuration change. |
| Additional VRAM at context 8192 versus context 2048 [DERIVED] | 855.336 MiB | about 768 MiB (tolerance +/-153.6) | VRAM budget figure: raising the context window to 8192 costs about 0.75 GB of additional VRAM. Tolerance of 0.15 GB is an operational allowance around the word 'about' and is not a corpus figure. | PASS | This is the price of a longer conversation window; on a card with a small margin it is the difference between a working configuration and a spilled one, so the context size is a procurement-relevant setting, not a tuning detail. |
| Warm end-to-end latency for the fixed probe interaction [DIRECT] | 2.60534 seconds | 1-3 seconds | Gate 0 acceptance criteria: the assistant returns a short response within the 1-3 s budget. The corpus does not fix the response length behind that figure; this harness applies the verdict to warm latency at a fixed interaction shape of about 350 input and about 120 output tokens, and reports the cold figure separately. | PASS | Warm latency is what a user experiences once the model is already loaded; a figure above the band means the interaction feels slow on this hardware, and a figure below it means the card is faster than the budget assumed. |
| Cold end-to-end latency including model load [DIRECT] | 5.20928 seconds | no threshold (REPORTED) | Gate 0 acceptance criteria: the 1-3 s budget does not state whether model load time is included, so the load-inclusive figure is reported without a verdict. | REPORTED | This is what the first interaction after an idle period costs; it sets the expectation for the first turn of a session rather than for the conversation. |
| GPU service time, speech-to-text stage [DIRECT] | 0.343 seconds | no threshold (REPORTED) | Concurrency-model figure, instrument list: per-stage GPU service time. No threshold is stated in the corpus. | REPORTED | Per-stage service time shows which stage owns the response budget, which is where added hardware or a smaller model would actually buy time. |
| GPU service time, language model stage [DERIVED] | 2.47234 seconds | no threshold (REPORTED) | Concurrency-model figure, instrument list: per-stage GPU service time. No threshold is stated in the corpus. | REPORTED | Per-stage service time shows which stage owns the response budget, which is where added hardware or a smaller model would actually buy time. |
| Generation rate [DERIVED] | 50.6297 tokens per second | no threshold (REPORTED) | Concurrency-model figure, instrument list: generation rate in tokens per second. No threshold is stated in the corpus. | REPORTED | Generation rate sets how long a longer answer takes on this card, so it bounds any future decision to lengthen the assistant's responses. |
| Speech-to-text real-time factor (ADDED) [DIRECT] | 0.0114333 ratio of processing wall time to audio duration | no threshold (REPORTED) | ADDED by this harness: no source in the reference documents and no target exists in the corpus. Measured over deterministic synthetic audio, not speech, so it is published as an instrument reading and never as a pass or fail. | REPORTED | A factor well below one means transcription keeps up with speech on this card; the figure is indicative only because the input was synthetic rather than real speech. |
| Maximum GPU temperature under sustained load [DIRECT] | 69 degrees Celsius | no threshold (REPORTED) | Gate 0 acceptance criteria: the card runs thermally unthrottled. No numeric threshold is stated in the corpus, and thermal behaviour depends on chassis and ambient conditions. | REPORTED | Temperature under sustained load indicates whether the quoted latency survives a busy period or only holds on a cold card. |
| SM clock range under sustained load [DIRECT] | 2190 MHz | no threshold (REPORTED) | Gate 0 acceptance criteria: the card runs thermally unthrottled. No numeric threshold is stated in the corpus. | REPORTED | A clock that falls away during the sustained window is the mechanism by which a thermally limited chassis turns an acceptable latency into an unacceptable one. |
| Generation-rate change across the sustained window [DERIVED] | 0.766164 tokens per second | no threshold (REPORTED) | Gate 0 acceptance criteria: the card runs thermally unthrottled. No numeric threshold is stated in the corpus. | REPORTED | A large drop between the start and the end of the sustained window means the measured latency is not sustainable in continuous service on this hardware. |

## Derivations

- **Usable VRAM after desktop reserve (ADDED)**: usable_vram_mb = device_nameplate_vram_mib - idle_desktop_reserve_mib
- **KV cache at context 2048**: kv_cache_ctx2048_mib = context8192_penalty_mib / (8192 - 2048) * 2048, assuming KV cache grows linearly with context length from a zero-context baseline
- **CUDA runtime plus compute buffers**: cuda_runtime_overhead_mib = total_resident_mib(ctx=2048) - idle_desktop_reserve_mib - model_weights_mib - kv_cache_ctx2048_mib
- **Total resident VRAM during a request**: total_resident_mib = peak(used_mib) over the GPU poll ticks collected while a request was in flight at context 2048
- **Remaining VRAM margin during a request**: margin_mib = usable_vram_mb - total_resident_mib(ctx=2048)
- **Peak residency fits in usable VRAM**: fits_in_usable_vram = 1.0 if total_resident_mib(ctx=2048) <= usable_vram_mb else 0.0
- **A second full residency does not fit**: does_not_fit_twice = 1.0 if 2 * total_resident_mib(ctx=2048) > usable_vram_mb else 0.0
- **Additional VRAM at context 8192 versus context 2048**: context8192_penalty_mib = total_resident_mib(ctx=8192) - total_resident_mib(ctx=2048)
- **GPU service time, language model stage**: llm_stage_service_s = prompt_eval_duration_s + eval_duration_s
- **Generation rate**: generation_rate_tps = eval_count / eval_duration_s
- **Generation-rate change across the sustained window**: sustained_gen_rate_delta_tps = generation_rate at the end of the sustained window - generation_rate at the start of the sustained window

## Negative disclosures

- WER / ASR accuracy: NOT MEASURED (no ground-truth corpus available).
- Affect macro-F1 >= 0.70: NOT MEASURED (out of scope; remains the largest unretired risk).
- openSMILE eGeMAPS 0 GB: ASSUMED (the opensmile module is not installed (No module named 'opensmile')).
- Piper TTS 0 GB: ASSUMED (the piper module is not installed (No module named 'piper')).
- Edge unit (Raspberry Pi Zero 2 W): NOT TESTED (no hardware; I2S full-duplex risk untouched).

## Variance across repetitions

Every verdict above is computed from the median of the retained repetitions for its metric, never from a single reading.

| Metric | n | Median | Min | Max | Dispersion (CV%) | Flag |
| --- | --- | --- | --- | --- | --- | --- |
| gpu_offload_pct | 3 | 100 | 100 | 100 | 0 |  |
| total_resident_mib | 3 | 5876.26 | 5876.26 | 5876.32 | 0.000614069 |  |
| model_weights_mib | 3 | 4769.5 | 4769.5 | 4769.5 | 0 |  |
| llm_stage_service_s | 3 | 2.47234 | 2.36387 | 2.56284 | 4.03928 |  |
| generation_rate_tps | 3 | 50.6297 | 48.9363 | 51.2016 | 2.34395 |  |
| warm_latency_s | 2 | 2.60534 | 2.55116 | 2.65952 | 2.94116 |  |
| sweep_e2e_s_n1 | 1 | 5.984 | 5.984 | 5.984 | n/a |  |
| sweep_e2e_s_n2 | 2 | 4.1095 | 2.688 | 5.531 | 48.9185 | UNSTABLE |
| sweep_e2e_s_n4 | 4 | 7.1645 | 2.907 | 11.547 | 51.6352 | UNSTABLE |
| sweep_e2e_s_n8 | 8 | 12.8515 | 2.86 | 22.844 | 54.3792 | UNSTABLE |
| sweep_queue_wait_s_n1 | 1 | 0 | 0 | 0 | n/a |  |
| sweep_queue_wait_s_n2 | 2 | 1.344 | 0 | 2.688 | 141.421 | UNSTABLE |
| sweep_queue_wait_s_n4 | 4 | 4.321 | 0 | 8.594 | 85.718 | UNSTABLE |
| sweep_queue_wait_s_n8 | 8 | 10 | 0 | 20 | 69.9464 | UNSTABLE |

## Comparison against the previous run

Compared against the previous run `20260817T024232Z`.

| Metric | Current median | Previous median | Delta | Delta % |
| --- | --- | --- | --- | --- |
| cold_latency_s | 5.20928 | n/a | n/a | n/a |
| context8192_penalty_mib | 855.336 | 854.988 | 0.347656 | 0.0406621 |
| cuda_runtime_overhead_mib | 197.146 | 211.699 | -14.5534 | -6.87456 |
| device_nameplate_vram_mib | 8188 | 8188 | 0 | 0 |
| does_not_fit_twice | 1 | 1 | 0 | 0 |
| fits_in_usable_vram | 1 | 1 | 0 | 0 |
| generation_rate_tps | 50.6297 | 50.4373 | 0.192373 | 0.38141 |
| gpu_offload_pct | 100 | 100 | 0 | 0 |
| idle_desktop_reserve_mib | 624.5 | 599.73 | 24.7695 | 4.13011 |
| kv_cache_ctx2048_mib | 285.112 | 284.996 | 0.115885 | 0.0406621 |
| llm_stage_service_s | 2.47234 | 2.61234 | -0.139996 | -5.35902 |
| margin_mib | 1687.24 | 1722.34 | -35.1016 | -2.03801 |
| model_weights_mib | 4769.5 | 4769.5 | 0 | 0 |
| stt_realtime_factor | 0.0114333 | 0.0520667 | -0.0406333 | -78.041 |
| stt_stage_service_s | 0.343 | 1.562 | -1.219 | -78.041 |
| sustained_gen_rate_delta_tps | 0.766164 | n/a | n/a | n/a |
| sustained_max_temp_c | 69 | n/a | n/a | n/a |
| sustained_sm_clock_mhz | 1680 | n/a | n/a | n/a |
| total_resident_ctx_alt_mib | 6731.59 | n/a | n/a | n/a |
| total_resident_mib | 5876.26 | 6293.42 | -417.162 | -6.62854 |
| usable_vram_mb | 7563.5 | 7588.27 | -24.7695 | -0.326419 |
| warm_latency_s | 2.60534 | n/a | n/a | n/a |
| whisper_small_int8_mib | 362.68 | 371.234 | -8.55469 | -2.30439 |

## Warm-versus-cold latency interpretation

Gate 0's 1-3 s budget is applied here to warm end-to-end latency (excludes model load) for the fixed probe interaction of about 350 input and about 120 output tokens. The cold figure (includes model load) is reported separately with no verdict, because the source documents do not themselves fix the response length behind the 1-3 s figure; this interpretation is the harness's own and is stated here rather than assumed silently.

## Concurrency sweep

The concurrency sweep exists to force both models to be resident on the card at the same time, not to establish a throughput result. N=2 is labelled observed because it was measured directly; N=8 is labelled modelled because it is a calculated envelope rather than an observed concurrency level.

| N | Label | Queue wait median (s) | End-to-end median (s) |
| --- | --- | --- | --- |
| 1 | observed | 0 | 5.984 |
| 2 | observed | 1.344 | 4.1095 |
| 4 | modelled | 4.321 | 7.1645 |
| 8 | modelled | 10 | 12.8515 |

## Excluded samples and incomplete phases

No samples were excluded from aggregation in this run.

- occupancy and baseline: occupancy reported and the idle baseline was established
- occupancy and baseline: foreign VRAM warning: 6753.7 MiB is in use before the harness has loaded anything, at or above the configured threshold of 512 MiB; every number this run produces is polluted by whatever else is holding that VRAM
- occupancy and baseline: per-process VRAM accounting is unavailable on this platform (the platform reports which processes hold VRAM but withholds the amount for at least one of them (the common case on a Windows WDDM display driver); falling back to total occupancy); falling back to total-occupancy reporting only
- residency and latency: 3 repetition(s) measured at context 2048
- context penalty: context 2048 versus context 8192 measured
- line-item decomposition: the VRAM budget line items were decomposed from the differential measurements
- spill-proof probe: spill reproduced at context size 16384: measured offload 87.0 percent, verdict FAIL
- spill-proof probe: spill first occurred at num_ctx=16384
- concurrency sweep: the 1, 2, 4, 8 concurrency sweep completed through a single-worker FIFO with both models held resident throughout
- concurrency sweep: concurrency 1 (observed): 1/1 request(s) usable, median queue wait 0.0, median end-to-end 5.984000000000037
- concurrency sweep: concurrency 2 (observed): 2/2 request(s) usable, median queue wait 1.343999999999994, median end-to-end 4.109499999999969
- concurrency sweep: concurrency 4 (modelled): 4/4 request(s) usable, median queue wait 4.321000000000026, median end-to-end 7.164500000000032
- concurrency sweep: concurrency 8 (modelled): 8/8 request(s) usable, median queue wait 10.0, median end-to-end 12.851500000000044
- sustained load: sustained load ran for 121.4 s (configured 120 s)
- sustained load: throttle reasons observed during the sustained window: gpu_idle
- sustained load: 45 request(s) were sent during the sustained window

## Limits of this harness

This harness measures GPU VRAM residency and the Figure 17 budget line items, request latency and generation rate, and thermal behaviour under sustained load, all against the detected card. It does not measure and does not establish: the quality or correctness of any model output, ASR transcription accuracy, affect or emotion classification accuracy, network reliability or service uptime behaviour, or the behaviour of the edge unit. A PASS verdict in this report is a hardware residency and budget result only; it is never evidence about what the model produces.
