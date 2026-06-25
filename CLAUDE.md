# Memory — ServiceScope Research Project

## Active Project
**ServiceScope v2** — FTC 2026 research paper + working system
Deadline: **1 July 2026** (Late Breaking Round submission)
→ Full detail: memory/projects/servicescope-paper.md

## Terms
| Term | Meaning |
|------|---------|
| FTC | Future Technologies Conference 2026, Berlin, 15–16 Oct |
| HOB/HOL | Head-of-Batch / Head-of-Line blocking |
| P/R/F1 | Precision / Recall / F1-score |
| GT | Ground truth |
| dynamic URL | `<dynamic:VAR_NAME>` — variable name, not a literal string |
| static URL | Hardcoded `http://...` string in source |
| blast radius | Set of services affected if service X changes |
| zero-shot | LLM prompt with no examples |
| few-shot | LLM prompt with worked examples |
| static-only baseline | No LLM — extract service name from URL string only |
| Gap 1–8 | Research gaps identified mid-session (see projects file) |

## Models Available (Ollama local)
| Model | Type | Notes |
|-------|------|-------|
| `gemma3:4b` | General | Current baseline |
| `gemma4:latest` | General large | 9.6GB, accuracy ceiling |
| `llama3.1:8b` | General | 4.9GB |
| `qwen2.5:1.5b` | General tiny | Speed floor |
| `starcoder2:3b` | Code | OLD — drop from ablation |
| `starcoder:latest` | Code | OLD — drop from ablation |
| `qwen2.5-coder:7b` | Code | **PULL THIS** — main code model |
| `qwen3:4b` | Latest gen | **PULL THIS** — structured output |

→ Full ablation design: memory/projects/servicescope-paper.md

## Preferences
- British English in paper
- Python for all scripts
- Concise responses, no postamble
