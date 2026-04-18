> Section: Flow — high-level prose overview, a Mermaid diagram (macro view),
> and a numbered pseudo-code walkthrough (detailed view).
> Three sub-prompts separated by ---:
>   1. Prose description (up to two paragraphs).
>   2. Mermaid flowchart LR diagram.
>   3. Numbered pseudo-code step list.
> The agent routes sub-prompt 2 through a diagram-aware cleaner that preserves
> the mermaid fence. Sub-prompts 1 and 3 use the standard text cleaner.

{{rag_context}}In at most two short paragraphs, describe the data flow for "{{name}}": where data comes from, what this process does to it, and where the output goes. Use plain business language.

Information:
{{content}}

---

Produce a Mermaid diagram for "{{name}}". Follow this format exactly — no extra text after the diagram:

```mermaid
flowchart LR
    SourceSystem[External Source] --> ThisProcess[{{name}}] --> OutputReport[Downstream Consumer]
```

Rules for the diagram:
- Use flowchart LR
- Label every node in plain English using square brackets: NodeId[Plain English Label]
- Put real source systems and inputs on the left
- Put this process in the middle
- Put real downstream consumers or outputs on the right
- Use --> for all arrows

Information:
{{content}}

---

List the steps of "{{name}}" as a numbered pseudo-code walkthrough in plain English.

Rules:
- One line per step.
- Use two-space indentation for sub-steps inside loops, conditions, or branches.
- Label branches clearly (e.g. "If the file is empty:", "On failure:").
- Use plain business language — no programming syntax.
- Each step should say what it receives or checks, what it does, and what it produces or passes on.
- Precede the list with the bold heading **Steps:**

Information:
{{content}}
