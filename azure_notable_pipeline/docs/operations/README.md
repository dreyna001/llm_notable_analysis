# Azure operations documentation

Azure deployment, monitoring, intake, portal, AI Search, and Azure OpenAI
runbooks are delivered with Phase 4.

The intake recovery runbook must distinguish three independent poison paths:

- `webjobs-blobtrigger-poison` on input storage means discovery/publication did
  not complete; check whether an analyzer job was already durably published.
- `notable-analysis-jobs-poison` on output storage means analyzer processing
  failed after publication.
- `case-embed-invocations-poison` on output storage means embedding failed.

None is replayed automatically. Replay follows correction of the underlying
cause and uses the normal idempotent intake or queue path.
