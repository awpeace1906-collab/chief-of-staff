# AI providers and routing

**Status:** live. Claude serves every route. Since v0.4.1, a local OpenAI-compatible provider (Ollama, llama.cpp server, vLLM, LM Studio) can serve the structured routes (`triage` for capture, `plan` for the brief), using JSON-schema output. The tool-using routes stay on Claude: `draft` carries out approvals and `chat` answers messages; pointing them at a local model fails visibly. Local usage is logged with no cost estimate.

Every AI task goes through a named **route**, and each route picks a provider and model. Users change them in **Settings → Advanced → AI**.

| Route | What it does | Default | Effort | Why |
|---|---|---|---|---|
| `triage` | Sort mail and digests, spot commitments, classify | Claude Haiku 5.5 | low | High volume, simple judgments; Haiku is very cheap |
| `plan` | Morning brief, coverage check, proposals | Claude Opus 5.5 | high | Reasoning across calendars, travel and rules; mistakes are costly |
| `draft` | Emails and messages for approval | Claude Opus 5.5 | medium | Quality of writing that goes out under your name |
| `chat` | Texts, voice notes, calls | Claude Opus 5.5 | medium | Has to understand loose speech and act correctly |

How calls are made: structured JSON output, stable instructions and rules in a cached system block, and server-side refusal fallback (`fallbacks: "default"`) on Opus and Sonnet routes. A refusal or truncated answer fails visibly; it is never silently retried on a different provider.

Providers:
- **`anthropic`**: Claude API (Anthropic SDK).
- **`openai-compatible`**: a local model behind Ollama, llama.cpp, LM Studio or vLLM, at a `baseUrl` on your own machine. Off by default.

## Should Chief of Staff run its own AI?

Short answer: **support it, but don't expect it to save much at personal scale.** It's mainly a privacy and offline option.

### What Claude costs for one person

Estimates from list prices (Anthropic, Oct 2026: Haiku 5.5 $0.10 / $0.50, Sonnet 5.5 $2 / $10, Opus 5.5 $4 / $20 per million input / output tokens; cached input on Opus 5.5 and Sonnet 5.5 $0.20). Usage assumptions: about 100 emails and digests a day, one brief, about 20 text or voice exchanges. v0.3 logs real token usage so these get replaced with measured numbers.

| Route | Daily volume (rough) | Haiku 5.5 | Sonnet 5.5 | Opus 5.5 |
|---|---|---|---|---|
| triage | ~150K in, ~10K out | **~$0.50/mo** | ~$10/mo | ~$20/mo |
| plan (brief) | ~60K in, ~5K out | — | ~$5/mo | **~$10/mo** |
| chat | ~160K in (mostly cached), ~10K out | — | ~$5/mo | **~$10/mo** |

- **Default routing (Haiku triage, Opus everything else): about $20/month.**
- Switching `plan` and `chat` to Sonnet 5.5: about $10/month.
- Prompt caching (keeping the stable rules and calendar context at the front of each request) is the biggest free saving and is built into v0.3.

### What local AI costs

| | Local model |
|---|---|
| Per-request cost | $0 |
| Hardware | A 16GB Mac mini runs ~8B-parameter models; 32GB+ (~$1,000+) for ~30B-class models |
| Power | ~$1–5/month |
| Quality | Fine for triage-style classification. Noticeably weaker at multi-step planning, reliable tool use and drafting, which are the jobs that matter most here |
| Speed | Slower than the API on small hardware, especially for long inputs like a day of email |

### Recommendation

1. **Keep Claude for `plan`, `draft` and `chat`.** Those are where quality matters and where a weaker model costs you more in mistakes than it saves.
2. **Triage on Claude Haiku 5.5 is already about $0.50/month.** Moving it local saves almost nothing, but it keeps email contents on your own hardware. That's the real reason to do it.
3. **The real cost lever is Opus vs Sonnet** for `plan` and `chat`, plus caching. Decide after a month of measured usage.
4. **Companies and practices** with privacy requirements can route everything to a local or self-hosted endpoint; the routes make that a settings change, not a code change.

## Rules for any provider

- No clinical or patient details in prompts, regardless of provider.
- Every AI call is logged with route, provider, model and token counts (`ai_usage` table; `cos usage` shows estimated cost).
- If a route's provider is unavailable, the task fails visibly in the brief; it never silently switches to a different provider.
