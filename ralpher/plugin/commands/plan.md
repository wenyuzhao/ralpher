# Project Plan Generator

Create detailed Project Plans that are clear, actionable, and suitable for implementation.

---

## The Job

1. Receive a feature description from the user
2. Carefully review the current repo to understand the source code and the context
3. Ask 3-10 essential clarifying questions
  * See the "Step 2. Clarifying Questions" section below
  * Don't ask the user to provide more details. Just provide them with a list of concrate options.
4. Generate a structured Project Plan based on answers and the context
5. Save to `.ralpher/projects/$0/PLAN.md`

**Important:** Do NOT start implementing. Just create the Project Plan.

---

## User Provided Feature Description

@.ralpher/projects/$0/PROMPT.md

---

## Step 1: Review the current repo

The repo has been checked out to ther target branch of this project for you. Carefully review the current repo and understand the context before making a plan.

---

## Step 2. Clarifying Questions

Ask only critical questions where the initial prompt is ambiguous. Focus on:

- **Problem/Goal:** What problem does this solve?
- **Core Functionality:** What are the key actions?
- **Scope/Boundaries:** What should it NOT do?
- **Success Criteria:** How do we know it's done?
- Any other critical questions

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

## Step 3: Generate Project Plan

Generate the Project Plan document.

Please refer to @!`echo $RALPHER_PLUGIN`/docs/plan-structure.md for a list of required sections and an example.

You can do step-2 multiple times to ask more questions when making the plan.

---

## Checklist

Before saving the Project Plan:

- [ ] Reviewed the repo and the context
- [ ] Asked clarifying questions
- [ ] Incorporated user's answers
- [ ] Tasks are small and specific
- [ ] Functional requirements are numbered and unambiguous
- [ ] Non-goals section defines clear boundaries
- [ ] Save to `.ralpher/projects/$0/PLAN.md`
