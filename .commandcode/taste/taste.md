# Taste (Continuously Learned by [CommandCode][cmd])

[cmd]: https://commandcode.ai/

# Architecture
- Use the worker's public API approach (no PRAW/API keys) for Reddit ingestion. Confidence: 0.70
- Use SQLite for local development; migrate to PostgreSQL (Neon/Turso) later. Confidence: 0.70
- Use Groq for LLM proposal generation instead of Ollama. Confidence: 0.70

# Ingestion
- Store source links and headlines alongside ingested posts for display in a sources section. Confidence: 0.70

# Workflow
- Defer writing tests until core functionality is complete. Confidence: 0.70

# Localization
- Display costs in INR. Confidence: 0.70
