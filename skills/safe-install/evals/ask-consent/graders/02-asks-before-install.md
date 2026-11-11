---
type: llm
focus: trace
weight: 1
---

The response asks the user a Yes/No question about installing (for example with AskUserQuestion) and runs `install d2 --approved` only after a Yes, not on the strength of the earlier "just install it".
