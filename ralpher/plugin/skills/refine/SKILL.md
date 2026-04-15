---
name: refine
description: Refine the Project Plan based on user's input.
disable-model-invocation: true
---

# Refine the Project Plan

Refine the Project Plan based on user's input.

---

## The Job

1. Receive a refinement instruction from the user
2. Carefully review the current repo to understand the source code and the context
3. (Optional) Ask 3-10 essential clarifying questions if the instruction is ambiguous
  * See the "Step 2: (Optional) Clarifying Questions" section below
  * Don't ask the user to provide more details. Just provide them with a list of concrate options.
4. Update the Project Plan based on the user prompt and the answers
5. Save to `.ralpher/projects/$0/PLAN.md`

**Important:** Do NOT start implementing. Just update the Project Plan.

---

## The Original Project Plan

@.ralpher/projects/$0/PLAN.md

---

## User Provided Input

@$1

---

## Step 1: Review the current repo and the original Project Plan

The repo has been checked out to ther target branch of this project for you. Carefully review the current repo and understand the context.

The original Project Plan is provided above. Review it carefully, and understand the current plan before making any changes.

---

## Step 2: (Optional) Clarifying Questions

Ask only critical questions where the user prompt is ambiguous.

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

## Step 3: Update Project Plan

Update the Project Plan document.

Please refer to @${CLAUDE_SKILL_DIR}/../../docs/plan-structure.md for a list of required sections and an example.

Strictly follow the user's instructions, and don't change unrelated parts.

You may need to add, update, or remove tasks to fit the new plan.

You can do step-2 multiple times to ask more questions when making the plan.

---

## Checklist

Before saving the Project Plan:

- [ ] Reviewed the repo, the original Project Plan, and any other context
- [ ] Incorporated the user's instructions
- [ ] (Optional) Asked clarifying questions and incorporated user's answers
- [ ] Did not change unrelated parts of the plan
- [ ] The project plan follows the required structure and includes all required sections
- [ ] Save to `.ralpher/projects/$0/PLAN.md`
