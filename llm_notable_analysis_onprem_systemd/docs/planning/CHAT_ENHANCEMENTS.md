# Chat Enhancements

## Goal

Make portal chat answers feel like a default ChatGPT-style chatbot: direct,
conversational, adaptive to the question, and useful without forcing a report
template into every answer.

## Proposed Answer Shape

- Answer the analyst's question directly first.
- Choose the format that fits the question: short paragraph, bullets, numbered steps, or a small table only when useful.
- Avoid default section headers such as `Grounded answer`, `Unknowns`, and `Suggested next steps` unless they make the answer clearer.
- Mention evidence gaps naturally instead of forcing an `Unknowns` section.
- Keep responses concise by default, then expand when the analyst asks for depth.
- Do not include `Draft query/example` unless the analyst explicitly asks for a query, rule, command, or example.

## Query Prompt Behavior

- When a query would be the appropriate next step, ask a short follow-up instead of generating it by default.
- Example: `Want me to draft a Splunk, Elasticsearch, or CrowdStrike query for that pivot?`
- Keep generated queries labeled as unvalidated draft guidance when requested.
- Never imply that the portal executed a query or performed an action.

## Prompt Update Notes

- Remove `Draft query/example` from the default optional section list in portal chat prompts.
- Replace the default section list with an adaptive chatbot instruction: answer naturally, keep it concise, and add structure only when helpful.
- Add an instruction to offer a query prompt only when the answer naturally leads to a hunt, pivot, or validation step.
- Preserve grounding rules: case facts come from retrieved context; general security knowledge may support interpretation and suggested next steps.
- Preserve refusal and insufficient-evidence behavior.

## Out Of Scope

- Automatic query execution.
- Ticket writeback or host actions.
- New UI widgets for query generation.
