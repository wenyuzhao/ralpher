---
# Modified from https://github.com/snarktank/ralph/blob/main/skills/prd/SKILL.md
---

# PRD Generator

Create detailed Product Requirements Documents that are clear, actionable, and suitable for implementation.

---

## The Job

1. Receive a feature description from the user
2. Ask 3-10 essential clarifying questions using the `AskUserQuestion` tool
  * Don't ask the user to provide more details. Just provide them with a list of concrate options.
  * You can use `AskUserQuestion` multiple times.
3. Generate a structured PRD based on answers
4. Save to `.ralpher/tasks/$0/PRD.md`

**Important:** Do NOT start implementing. Just create the PRD.

---

## User Provided Feature Description

@.ralpher/tasks/$0/PROMPT.md

---

## Step 1: Clarifying Questions

Ask only critical questions where the initial prompt is ambiguous. Focus on:

- **Problem/Goal:** What problem does this solve?
- **Core Functionality:** What are the key actions?
- **Scope/Boundaries:** What should it NOT do?
- **Success Criteria:** How do we know it's done?

---

## Step 2: Generate PRD

Generate the PRD document.

Please refer to @../docs/prd-structure.md for a list of required sections and an example.

---

## Output

- **Format:** Markdown (`.md`)
- **Location:** `.ralpher/tasks/$0/`
- **Filename:** `PRD.md`

---

## Checklist

Before saving the PRD:

- [ ] Asked clarifying questions
- [ ] Incorporated user's answers
- [ ] User stories are small and specific
- [ ] Functional requirements are numbered and unambiguous
- [ ] Non-goals section defines clear boundaries
- [ ] Save to `.ralpher/tasks/$0/PRD.md`