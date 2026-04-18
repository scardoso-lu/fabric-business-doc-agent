> Section: Data Quality & Alerts — validation checks, error handling, and notifications.
> Two sub-prompts separated by ---:
>   1. What is validated (rules, filters, thresholds).
>   2. What happens on failure — exceptions raised, branches taken, external alerts sent.
> The agent pre-extracts alert signals (raise/except/logging/webhook/email/Teams/Slack
> patterns) from the source code and includes them in {{content}} for sub-prompt 2.

{{rag_context}}What validation checks, filters, or conditional logic does "{{name}}" apply to ensure the data is accurate and complete? List the specific rules, conditions, or thresholds checked.

Information:
{{content}}

---

What happens when something goes wrong in "{{name}}"? Look for:
- Exceptions or errors that are raised (raise statements, Fail activities, error conditions)
- If/else or Switch branches that handle bad data or failures
- External notifications triggered on failure: log messages, email alerts, webhook calls, Teams or Slack messages, API calls to monitoring systems

For each pattern found, describe: what condition triggers it, what the response is, and where the notification goes (recipient, log target, endpoint) if it can be identified from the code.

If no external alerting is found, state the fallback behaviour (stops silently, propagates the error, skips bad records, and so on).

Information:
{{content}}
