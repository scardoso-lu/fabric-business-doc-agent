> Section: Purpose — why this process exists and what business need it serves.
> Two sub-prompts separated by ---:
>   1. The business reason for existing (one or two sentences).
>   2. The impact if it stopped running (one sentence).
> The agent enriches this section with linked Jira / Azure DevOps tickets before
> calling the LLM. If no tickets are found it falls back to the data flow as context.

{{rag_context}}In one or two sentences, explain why "{{name}}" exists and what business problem it solves.

Information:
{{content}}

---

What would be missing or broken for the business if "{{name}}" did not run? Keep to one sentence.

Information:
{{content}}
