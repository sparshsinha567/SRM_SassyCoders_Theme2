# Samsung PRISM GenAI Hackathon 2026 — Theme 2: Smart Guided Troubleshooting Engine

**Team Name:** SRM_SassyCoders  
**Theme:** Theme 2 — Smart Guided Troubleshooting Engine  
**Release Tag:** `PRISM_GENAI_HACKATHON_Y2026`  

---

## 🏆 Submission Deliverables & Artifacts

| Deliverable | File Link | Description |
|---|---|---|
| 📊 **Submission Presentation** | [`SRM_SassyCoders_Theme2.pptx`](SRM_SassyCoders_Theme2.pptx) | Official final submission slide deck |
| 🎥 **Video Demonstration** | [`SRM_SassyCoders_theme2.mp4`](SRM_SassyCoders_theme2.mp4) | High-definition live video walkthrough (Acts 1–5) |
| 📋 **Audited Telemetry & Metrics** | [`metrics.md`](metrics.md) | Verified latency, cache hit rate, screen resolution, and safety telemetry |
| 📱 **Interactive One UI Web Dashboard** | [`index.html`](index.html) | Production-ready interactive web application with force-cold & cache toggle |
| 📄 **Final 20-Query Output Contract** | [`final_submission_output.json`](final_submission_output.json) | Complete Appendix A schema-compliant JSON evaluation output |
| 📖 **Technical Architecture Walkthrough** | [`walkthrough.md`](walkthrough.md) | Comprehensive engineering whitepaper and architecture deep-dive |
| 🤖 **AI Disclosure Statement** | [`AI_DISCLOSURE.md`](AI_DISCLOSURE.md) | Full transparency declaration on AI tools, models, and guardrails |

---

## ⚡ Key Architectural Highlights

1. **Sub-25ms Semantic Cache Fast-Path**:
   - Calibrated hybrid cache using normalized cosine similarity (`threshold = 0.48`) and exact normalized canonical keys.
   - Warm queries resolve in **20.7 ms** (SLA target: $\le 100\text{ ms}$).
2. **100% Leaf-Screen Resolution**:
   - Recursive structural traversal eliminates root/intermediate screen ambiguity.
   - Evaluated across official 578 deep links: **2.00 / 2.0 (100.0% Leaf Screen Accuracy)**.
3. **Strict Programmatic Guardrails (Zero Hallucination)**:
   - Action descriptions strictly clamped to **5–7 words** starting with `"It will"`.
   - Complete URL stripping and deterministic action taxonomy (Settings vs. Device Care vs. Guidance).
   - Zero-link safety fallback for physical/hardware damage (e.g. cracked glass, water immersion).
4. **Official 578-Entry Catalog Integration**:
   - Production dataset located in `main_data_for_submission/` with full coverage across display, battery, connectivity, and audio settings.

---

## 🚀 Quick Start (Local)

### 1. Environment Setup
```bash
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment Keys
```bash
cp .env.example .env
# Edit .env with your GEMINI_API_KEY or OPENAI_API_KEY
```

### 3. Launch API & Interactive UI
```bash
python -m uvicorn api:app --host 0.0.0.0 --port 8000
```
Open **`http://localhost:8000`** in your browser to view the interactive Samsung One UI troubleshooting dashboard.

---

## 🧪 Verification & Test Suite

Run the full evaluation suite directly in terminal:

```bash
# 1. End-to-end smoke test
python smoke_test.py

# 2. Leaf screen resolution accuracy (100% leaf screen validation)
python eval_screen_resolution.py

# 3. Rule compliance & 5-7 word action constraint test
python test_one_action_one_screen.py

# 4. Semantic cache precision & generalization test
python cache_precision_test.py

# 5. Full 20-query batch evaluation
python run_final_submission.py
```

---

## 🐳 Docker Deployment

```bash
docker compose up --build
```
Spins up the production container with health checks exposed on `http://localhost:8000/health`.

---

## 📁 Repository Directory Structure

```
├── SRM_SassyCoders_Theme2.pptx     # Official submission presentation deck
├── SRM_SassyCoders_theme2.mp4      # Live demonstration video
├── main_data_for_submission/       # Official 578-entry catalog & 20 evaluation queries
│   ├── deeplinks.json              # 578 masked deeplink catalog entries
│   ├── queries.json                # 20 customer troubleshooting complaints
│   ├── siis_responses.json         # Raw SIIS knowledge base responses
│   └── sample_output.json          # Target submission schema reference
├── final_submission_output.json    # Complete validated JSON output for 20 queries
├── index.html                      # Interactive One UI responsive web dashboard
├── metrics.md                      # Complete quantitative benchmark report
├── walkthrough.md                  # Comprehensive architectural walkthrough
├── api.py                          # FastAPI service (REST endpoints & Web UI)
├── cache.py                        # Two-tier fast-path semantic caching engine
├── retrieval.py                    # Hybrid BM25 + dense embedding vector search
├── structure_extraction.py         # LLM action extraction & programmatic guardrails
├── query_enrichment.py             # Query normalization & paraphrase generation
├── schema.py                       # Appendix A Pydantic contract specification
├── llm_client.py                   # Multi-provider LLM connector (Gemini, OpenAI, Anthropic, Stub)
├── eval_screen_resolution.py       # Leaf screen resolution verification suite
├── test_one_action_one_screen.py   # Action constraint & schema validation suite
├── cache_precision_test.py         # Semantic cache threshold calibration harness
├── run_final_submission.py         # 20-query submission batch runner
├── smoke_test.py                   # End-to-end integration test
├── Dockerfile                      # Production Docker container definition
├── docker-compose.yml              # Container orchestration configuration
└── requirements.txt                # Pinned production dependencies
```

---
*Built with ❤️ by SRM_SassyCoders for the Samsung PRISM GenAI Hackathon 2026.*
