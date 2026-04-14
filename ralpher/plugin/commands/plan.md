# Project Plan Generator

Create detailed Project Plans that are clear, actionable, and suitable for implementation.

---

## The Job

1. Receive a feature description from the user
2. Ask 3-10 essential clarifying questions (see the "ask user questions" section below)
  * Don't ask the user to provide more details. Just provide them with a list of concrate options.
3. Generate a structured Project Plan based on answers
4. Save to `.ralpher/projects/$0/PLAN.md`

**Important:** Do NOT start implementing. Just create the Project Plan.

---

## User Provided Feature Description

@.ralpher/projects/$0/PROMPT.md

---

## Step 1: Clarifying Questions

Ask only critical questions where the initial prompt is ambiguous. Focus on:

- **Problem/Goal:** What problem does this solve?
- **Core Functionality:** What are the key actions?
- **Scope/Boundaries:** What should it NOT do?
- **Success Criteria:** How do we know it's done?

---

## Step 2: Generate Project Plan

Generate the Project Plan document.

Please refer to @!`echo $RALPHER_PLUGIN`/docs/plan-structure.md for a list of required sections and an example.

---

## Output

- **Format:** Markdown (`.md`)
- **Location:** `.ralpher/projects/$0/`
- **Filename:** `PLAN.md`

---

## Ask User Questions

To ask user questions, output all the questions to `.ralpher/projects/$0/questions.json` in the following format, and finish your turn. The user will provide answers in the next turn.

```json
{
  "questions": [
    {
      "header": "...", // A short header in 1-2 words
      "question": "The question?", // A mult-choice single-answer question
      "options": [
        // A list of 2-6 options
        {
          "label": "Label 1",
          "description": "Description 1"
        },
        {
          "label": "Label 2",
          "description": "Description 2"
        },
      ]
    },
    // ... other questions
  ]
}
```

---

## Checklist

Before saving the Project Plan:

- [ ] Asked clarifying questions
- [ ] Incorporated user's answers
- [ ] Tasks are small and specific
- [ ] Functional requirements are numbered and unambiguous
- [ ] Non-goals section defines clear boundaries
- [ ] Save to `.ralpher/projects/$0/PLAN.md`
