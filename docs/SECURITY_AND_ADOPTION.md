# Security boundary and adoption path

AEGIS 3.0 is a **simulation-only research prototype and decision-support concept**. It does not connect to, read from
or control any real utility equipment, and this document does not describe an existing live-data capability. It sets
out what would have to be true before any of that could happen. Nothing here claims regulatory compliance,
certification or real-world safety.

## Current security posture (as built)

- **Offline.** The core application runs on `127.0.0.1` with no outbound calls. The only exception is the optional LLM
  (explanations and the opt-in tool controller), which is used only if an `ANTHROPIC_API_KEY` is set. With no key,
  nothing leaves the machine.
- **Inputs.** The only data source is the in-process simulator. There are no network telemetry clients, no SCADA,
  Modbus or DNP3 code, and no credentials for infrastructure.
- **Actions.** The executor can only call `World.execute` in the simulator. There is no actuator interface.
- **LLM boundary.** The LLM receives agent-side observations and tool results only. It cannot change constraints,
  bypass the gate, skip human approval, or execute anything directly. This is enforced in code and by tests.
- **Not yet implemented:** there is no authentication on the local API. It is a single-user demo bound to localhost
  and must not be exposed on a network as it stands.

## Future read-only telemetry adapter (design only, not built)

If AEGIS were ever given real data, it would go through a separate adapter with these properties:

| Control | Requirement |
|---|---|
| Direction | **Read-only.** Data flows one way from historians or a data diode into AEGIS. No write path to control systems exists in the adapter's code or network rules. |
| Placement | Outside the control network: an IT/OT DMZ consuming replicated historian data, never direct OT polling, with network isolation and allow-listed flows only. |
| Least privilege | A dedicated service identity with read access to only the tags AEGIS needs. Short-lived credentials from a secrets manager, never stored in code or config files. |
| Authentication | Mutual TLS to the data source. Operator SSO with MFA for the AEGIS UI and API, with roles for viewer, approver and administrator. Approval actions are tied to named users. |
| Audit logging | Append-only logs of every reading ingested, every decision record, every approval or rejection and every configuration change, with clock sync. The existing Decision Proof Record is the starting point. |
| Data minimization | Only the tags required for recovery decisions, retained for a defined period, with no personal data. LLM use, if any, is restricted to approved deployments, with prompts containing only what the controller context already holds. |
| Input integrity | Treat telemetry as untrusted: validate ranges, freshness and consistency. A spoofed or biased sensor can mislead AEGIS (see the stress results), so independent sensors or cross-checks are needed before relying on it. |
| Review | Threat model and operational-security review by the utility's security team, plus penetration testing of the adapter and UI, before any connection is made. |

## Staged adoption path

AEGIS should be treated as **decision support** until it has been independently validated. It should never act
autonomously on equipment without formal approval.

| Stage | What happens | Exit criteria (examples) |
|---|---|---|
| 1. Synthetic simulation (**current**) | Seeded scenarios, stress suites, generated dev and held-out sets | Reproducible results; known failure modes documented (e.g. optimistic SoC bias) |
| 2. Historical-data replay | Run AEGIS offline on recorded incident data from a real site, compared with what operators actually did | Domain experts review the decisions; the battery and plan models are recalibrated from real data; scenarios written by people other than the authors |
| 3. Shadow mode | Read-only adapter (above); AEGIS recommends, operators decide, nothing is executed by AEGIS | Agreement and disagreement analysis over an agreed period; no unsafe recommendation reaches an approval step without being caught |
| 4. Supervised pilot | A limited scope, e.g. advisory alerts or pre-filled approval requests on one non-critical system, with operators in control | Formal hazard analysis, management-of-change approval, and sign-off from safety and security owners |
| 5. Any operational control | Only after formal approvals under the operator's safety and cybersecurity frameworks, including procurement, assurance and certification where applicable | Independent assessment and ongoing monitoring |

**Barriers to acknowledge.** Utilities have long procurement cycles, safety-case requirements, and regulatory and
cybersecurity obligations, which differ by country and sector. AEGIS has not been assessed against any of them.
Stages 2–5 depend on a utility partner, real data, and independent reviewers, none of which this project has.
