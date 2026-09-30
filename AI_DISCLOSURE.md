# AI Disclosure Statement

**Samsung PRISM GenAI Hackathon 2026**  
**Theme:** Theme 2 — Smart Guided Troubleshooting Engine  
**Team Name:** SRM_SassyCoders  
**Date:** September 30, 2026  

---

## 1. Declaration of AI Tool Usage

In accordance with the Samsung PRISM GenAI Hackathon guidelines on transparency, academic integrity, and responsible AI innovation, this document outlines the usage of Generative AI tools and foundation models in the development and runtime execution of the **Smart Guided Troubleshooting Engine**.

### 1.1 Development & Coding Assistance
- **Tools Utilized**: Large Language Model coding assistants (Google Gemini, Claude, and OpenAI).
- **Scope of Use**:
  - Drafting boilerplate configurations (FastAPI route stubs, Pydantic data schemas).
  - Assisting in unit test case formulation and regex validation for 5–7 word action constraints.
  - Formulating adversarial test queries for cache robustness and lexical trap evaluation.
- **Human Authorship & Verification**: All architectural design decisions, custom hybrid retrieval algorithms (BM25 + dense embedding Reciprocal Rank Fusion), recursive leaf-screen traversal algorithms, cache similarity calibrations, and telemetry benchmarks were authored, tuned, verified, and audited by SRM_SassyCoders team members.

---

## 2. Runtime Generative AI Architecture

The engine integrates Generative AI models as modular runtime components within a deterministic, guardrailed pipeline:

### 2.1 Models Supported & Implemented
- **Google Gemini API (`gemini-2.5-flash` / `gemini-1.5-pro`)**: Primary multi-intent structure extraction and conversational query normalization.
- **OpenAI API (`gpt-4o-mini` / `text-embedding-3-small`)**: Alternative pluggable provider for structure extraction and embedding vectors.
- **Anthropic Claude API (`claude-3-5-sonnet`)**: High-precision extraction fallback.
- **Deterministic Rule-Based Stub**: Local offline execution mode providing zero-cost, zero-latency deterministic responses for continuous integration, Docker health-checking, and evaluation.

### 2.2 Guardrails & Programmatic Hallucination Prevention
- **DeepLink Integrity**: The LLM is strictly prohibited from inventing or hallucinating action URLs or URIs. Actionable deep links are resolved exclusively via deterministic similarity search against the organizer-verified 578-entry catalog (`deeplinks.json`).
- **Description Clamping**: Programmatic regex and token filters enforce strict 5–7 word length constraints starting with `"It will"`.
- **Zero URL Leaks**: Hardcoded programmatic sanitizers strip any accidental URLs or schema leaks from user-facing text.
- **Hardware Triage Safety**: Physical damage queries (e.g. cracked screens, water exposure) automatically resolve with `actionableDeeplink: null` to prevent misleading automated action triggers.

---

## 3. Data Privacy & Ethical Compliance
- **Zero PII Storage**: The system processes user troubleshooting queries in-memory; no user identifiers, IP addresses, or personal identifiable information are stored or transmitted.
- **On-Device / Private Cloud Ready**: Retrieval, BM25 indexing, and semantic cache execution run 100% locally on-device without telemetry leakage.

---

**Confirmed & Certified by:**  
Team SRM_SassyCoders  
*Samsung PRISM GenAI Hackathon 2026*
