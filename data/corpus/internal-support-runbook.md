---
id: internal-support-runbook
title: Internal support runbook for POS telemetry codes (mock)
source_url: internal://support-runbook
origin: internal_runbook_mock
retrieved_at: 2026-11-13
---
## Telemetry status OFFLINE_GPRS_TIMEOUT (machine will not connect to the internet)
Synthetic runbook for the mock back office, not official Getnet content. OFFLINE_GPRS_TIMEOUT means the terminal's mobile data session stalled. First-line steps for the merchant, in order: 1) restart the terminal and wait for the network indicator; 2) if Wi-Fi is available, connect the terminal to the store Wi-Fi; 3) with the terminal off, reseat the SIM chip and power it back on; 4) run the communication test described in the Getnet FAQ. If the terminal is still offline on both mobile data and Wi-Fi after these steps, open a ticket with a human specialist for a chip or terminal swap.

## Decline codes ERR_51_ISSUER_DECLINE and POS_KEY_SYNC_WARN
Synthetic runbook for the mock back office, not official Getnet content. ERR_51_ISSUER_DECLINE alone is an issuer-side refusal: ask the buyer to try another card or contact their bank. When it appears together with POS_KEY_SYNC_WARN, the terminal's PIN-pad keys are out of sync; this cannot be fixed by the merchant and requires a remote re-key or terminal swap (action code terminal_rekey_or_swap), which must be approved by a human L2 specialist before it is scheduled. Until then the merchant can keep selling with Pix or a Payment Link.
