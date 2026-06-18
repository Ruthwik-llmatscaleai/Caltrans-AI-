# CM/GC Code Generation — Full System Flow

```
╔═══════════════════════════════════════════════════════════════════════════════╗
║                                                                               ║
║                              USER INTERFACE                                   ║
║                                                                               ║
║   ┌─────────────────────────────────────────────────────────────────────┐    ║
║   │                                                                     │    ║
║   │   User provides project context / requirements / parameters         │    ║
║   │                                                                     │    ║
║   └──────────────────────────────────┬──────────────────────────────────┘    ║
║                                      │                                        ║
╚══════════════════════════════════════╪════════════════════════════════════════╝
                                       │
                                       ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║                           PLANNING AGENT                                     ║
║                                                                              ║
║   ┌────────────────────────────────────────────────────────────────────┐    ║
║   │                                                                    │    ║
║   │   • Receives raw user input                                        │    ║
║   │   • Parses intent and requirements                                 │    ║
║   │   • Validates input completeness                                   │    ║
║   │   • Structures input into a normalized format                      │    ║
║   │   • Passes structured input to Orchestrator                        │    ║
║   │                                                                    │    ║
║   └────────────────────────────────────┬───────────────────────────────┘    ║
║                                        │                                     ║
╚════════════════════════════════════════╪═════════════════════════════════════╝
                                         │
                                         ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║                         ORCHESTRATOR AGENT                                   ║
║                                                                              ║
║   ┌────────────────────────────────────────────────────────────────────┐    ║
║   │                                                                    │    ║
║   │   • Receives structured input from Planning Agent                  │    ║
║   │   • Manages the two-stage pipeline                                 │    ║
║   │   • Computes fingerprints                                          │    ║
║   │   • Checks Result Store at each stage                              │    ║
║   │   • Routes to generation agents only on miss                       │    ║
║   │                                                                    │    ║
║   └────────────────────────────────────┬───────────────────────────────┘    ║
║                                        │                                     ║
╚════════════════════════════════════════╪═════════════════════════════════════╝
                                         │
                                         │
         ┌───────────────────────────────┘
         │
         │
         ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║                    STAGE 1 — PROMPT GENERATION                               ║
║                                                                              ║
║   ┌────────────────────────────────────────────────────────────────────┐    ║
║   │                                                                    │    ║
║   │   Orchestrator computes fingerprint of structured input            │    ║
║   │                                                                    │    ║
║   └────────────────────────────────────┬───────────────────────────────┘    ║
║                                        │                                     ║
║                                        ▼                                     ║
║                             ┌─────────────────────┐                          ║
║                             │                     │                          ║
║                             │  Input fingerprint  │                          ║
║                             │  in Result Store?   │                          ║
║                             │                     │                          ║
║                             └──────┬────────┬─────┘                          ║
║                                    │        │                                ║
║                              YES   │        │   NO                           ║
║                                    │        │                                ║
║                ┌───────────────────┘        └───────────────────┐            ║
║                │                                                │            ║
║                ▼                                                ▼            ║
║   ┌────────────────────────┐          ┌─────────────────────────────────┐   ║
║   │                        │          │                                 │   ║
║   │  Retrieve stored       │          │    PROMPT GENERATION AGENT      │   ║
║   │  system prompt         │          │                                 │   ║
║   │  from Result Store     │          │    • Takes structured input     │   ║
║   │                        │          │    • Generates system prompt    │   ║
║   │                        │          │    • Structures instructions    │   ║
║   │                        │          │      for code generation       │   ║
║   │                        │          │                                 │   ║
║   └────────────┬───────────┘          └────────────────┬────────────────┘   ║
║                │                                       │                     ║
║                │                                       ▼                     ║
║                │                       ┌───────────────────────────────┐     ║
║                │                       │                               │     ║
║                │                       │  Store generated prompt       │     ║
║                │                       │  in Result Store              │     ║
║                │                       │                               │     ║
║                │                       │  Key: input fingerprint       │     ║
║                │                       │  Value: system prompt         │     ║
║                │                       │                               │     ║
║                │                       └───────────────┬───────────────┘     ║
║                │                                       │                     ║
║                └───────────────────┬───────────────────┘                     ║
║                                    │                                         ║
║                                    ▼                                         ║
║                         ┌─────────────────────┐                              ║
║                         │                     │                              ║
║                         │   System Prompt     │                              ║
║                         │   (stored or new)   │                              ║
║                         │                     │                              ║
║                         └──────────┬──────────┘                              ║
║                                    │                                         ║
╚════════════════════════════════════╪═════════════════════════════════════════╝
                                     │
                                     │
                                     ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║                    STAGE 2 — CODE GENERATION                                 ║
║                                                                              ║
║   ┌────────────────────────────────────────────────────────────────────┐    ║
║   │                                                                    │    ║
║   │   Orchestrator computes fingerprint of system prompt               │    ║
║   │                                                                    │    ║
║   └────────────────────────────────────┬───────────────────────────────┘    ║
║                                        │                                     ║
║                                        ▼                                     ║
║                             ┌─────────────────────┐                          ║
║                             │                     │                          ║
║                             │  Prompt fingerprint │                          ║
║                             │  in Result Store?   │                          ║
║                             │                     │                          ║
║                             └──────┬────────┬─────┘                          ║
║                                    │        │                                ║
║                              YES   │        │   NO                           ║
║                                    │        │                                ║
║                ┌───────────────────┘        └───────────────────┐            ║
║                │                                                │            ║
║                ▼                                                ▼            ║
║   ┌────────────────────────┐          ┌─────────────────────────────────┐   ║
║   │                        │          │                                 │   ║
║   │  Retrieve stored       │          │    CODE GENERATION AGENT        │   ║
║   │  code from             │          │                                 │   ║
║   │  Result Store          │          │    • Receives system prompt     │   ║
║   │                        │          │    • Sends to Claude Opus 4.6   │   ║
║   │                        │          │    • Receives generated code    │   ║
║   │                        │          │    • Validates output format    │   ║
║   │                        │          │                                 │   ║
║   └────────────┬───────────┘          └────────────────┬────────────────┘   ║
║                │                                       │                     ║
║                │                                       ▼                     ║
║                │                       ┌───────────────────────────────┐     ║
║                │                       │                               │     ║
║                │                       │  Store generated code         │     ║
║                │                       │  in Result Store              │     ║
║                │                       │                               │     ║
║                │                       │  Key: prompt fingerprint      │     ║
║                │                       │  Value: generated code        │     ║
║                │                       │                               │     ║
║                │                       └───────────────┬───────────────┘     ║
║                │                                       │                     ║
║                └───────────────────┬───────────────────┘                     ║
║                                    │                                         ║
║                                    ▼                                         ║
║                         ┌─────────────────────┐                              ║
║                         │                     │                              ║
║                         │   Generated Code    │                              ║
║                         │   (stored or new)   │                              ║
║                         │                     │                              ║
║                         └──────────┬──────────┘                              ║
║                                    │                                         ║
╚════════════════════════════════════╪═════════════════════════════════════════╝
                                     │
                                     │
                                     ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║                          DELIVERY AGENT                                      ║
║                                                                              ║
║   ┌────────────────────────────────────────────────────────────────────┐    ║
║   │                                                                    │    ║
║   │   • Receives generated code                                        │    ║
║   │   • Formats output for display                                     │    ║
║   │   • Attaches metadata (status, timestamp)                          │    ║
║   │   • Sends structured response to UI                                │    ║
║   │                                                                    │    ║
║   └────────────────────────────────────┬───────────────────────────────┘    ║
║                                        │                                     ║
╚════════════════════════════════════════╪═════════════════════════════════════╝
                                         │
                                         ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║                              USER INTERFACE                                  ║
║                                                                              ║
║   ┌────────────────────────────────────────────────────────────────────┐    ║
║   │                                                                    │    ║
║   │   • Displays generated code (syntax highlighted)                   │    ║
║   │   • Shows status: STORED or NEW                                    │    ║
║   │   • Shows generation timestamp                                     │    ║
║   │                                                                    │    ║
║   └────────────────────────────────────────────────────────────────────┘    ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝



═══════════════════════════════════════════════════════════════════════════════
                            RESULT STORE
═══════════════════════════════════════════════════════════════════════════════

┌──────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│   STAGE 1 ENTRIES                        STAGE 2 ENTRIES                     │
│                                                                              │
│   ┌────────────────────────────┐        ┌────────────────────────────┐      │
│   │  Key: input fingerprint    │        │  Key: prompt fingerprint   │      │
│   │  Value: system prompt      │        │  Value: generated code     │      │
│   │  Created: timestamp        │        │  Created: timestamp        │      │
│   └────────────────────────────┘        └────────────────────────────┘      │
│                                                                              │
│   ┌────────────────────────────┐        ┌────────────────────────────┐      │
│   │  Key: input fingerprint    │        │  Key: prompt fingerprint   │      │
│   │  Value: system prompt      │        │  Value: generated code     │      │
│   │  Created: timestamp        │        │  Created: timestamp        │      │
│   └────────────────────────────┘        └────────────────────────────┘      │
│                                                                              │
│   ...                                    ...                                 │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘



═══════════════════════════════════════════════════════════════════════════════
                         AGENT RESPONSIBILITIES
═══════════════════════════════════════════════════════════════════════════════

┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│                  │   │                  │   │                  │   │                  │   │                  │
│  PLANNING        │   │  ORCHESTRATOR    │   │  PROMPT          │   │  CODE            │   │  DELIVERY        │
│  AGENT           │──►│  AGENT           │──►│  GENERATION      │──►│  GENERATION      │──►│  AGENT           │
│                  │   │                  │   │  AGENT           │   │  AGENT           │   │                  │
│  ────────────    │   │  ────────────    │   │  ────────────    │   │  ────────────    │   │  ────────────    │
│                  │   │                  │   │                  │   │                  │   │                  │
│  • Parse raw     │   │  • Manage        │   │  • Convert user  │   │  • Send prompt   │   │  • Format code   │
│    user input    │   │    pipeline      │   │    input into    │   │    to Opus 4.6   │   │    for display   │
│                  │   │                  │   │    system prompt │   │                  │   │                  │
│  • Validate      │   │  • Compute       │   │                  │   │  • Receive       │   │  • Attach        │
│    completeness  │   │    fingerprints  │   │  • Structure     │   │    generated     │   │    metadata      │
│                  │   │                  │   │    instructions  │   │    code          │   │                  │
│  • Normalize     │   │  • Check         │   │    for code gen  │   │                  │   │  • Return to     │
│    input format  │   │    Result Store  │   │                  │   │  • Validate      │   │    UI            │
│                  │   │                  │   │                  │   │    output format │   │                  │
│  • Determine     │   │  • Route to      │   │                  │   │                  │   │                  │
│    intent        │   │    agents or     │   │                  │   │                  │   │                  │
│                  │   │    stored result │   │                  │   │                  │   │                  │
│                  │   │                  │   │                  │   │                  │   │                  │
└──────────────────┘   └──────────────────┘   └──────────────────┘   └──────────────────┘   └──────────────────┘



═══════════════════════════════════════════════════════════════════════════════
                              SCENARIOS
═══════════════════════════════════════════════════════════════════════════════


SCENARIO 1: Nothing changed
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  User Input ──► Planning Agent ──► Orchestrator
                                        │
                                        ▼
                                   Input fingerprint found
                                   in Result Store
                                        │
                                        ▼
                                   Stored prompt retrieved
                                        │
                                        ▼
                                   Prompt fingerprint found
                                   in Result Store
                                        │
                                        ▼
                                   Stored code retrieved
                                        │
                                        ▼
                                   Delivery Agent ──► User sees code

  Generation Agent calls: 0


SCENARIO 2: User input changed, new prompt, new code
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  User Input ──► Planning Agent ──► Orchestrator
                                        │
                                        ▼
                                   Input fingerprint NOT found
                                        │
                                        ▼
                                   Prompt Generation Agent
                                   generates new system prompt
                                        │
                                        ▼
                                   New prompt stored
                                        │
                                        ▼
                                   Prompt fingerprint NOT found
                                        │
                                        ▼
                                   Code Generation Agent
                                   calls Opus 4.6
                                        │
                                        ▼
                                   New code stored
                                        │
                                        ▼
                                   Delivery Agent ──► User sees code

  Generation Agent calls: 2 (prompt + code)


SCENARIO 3: User input changed, but generates same prompt
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  User Input ──► Planning Agent ──► Orchestrator
                                        │
                                        ▼
                                   Input fingerprint NOT found
                                        │
                                        ▼
                                   Prompt Generation Agent
                                   generates system prompt
                                   (happens to be same as before)
                                        │
                                        ▼
                                   New input→prompt mapping stored
                                        │
                                        ▼
                                   Prompt fingerprint FOUND
                                   in Result Store
                                        │
                                        ▼
                                   Stored code retrieved
                                        │
                                        ▼
                                   Delivery Agent ──► User sees code

  Generation Agent calls: 1 (prompt only, code reused)
```
