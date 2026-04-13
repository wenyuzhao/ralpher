# PRD Refiner

Refine the Product Requirements Documents based on user's input.

---

## The Job

1. Receive an refinement instruction from the user
2. (Optional) Ask 3-10 essential clarifying questions using the `AskUserQuestion` tool if the instruction is ambiguous
  * Don't ask the user to provide more details. Just provide them with a list of concrate options.
  * You can use `AskUserQuestion` multiple times.
3. Update the PRD based on the user prompt and the answers
4. Save to `.ralpher/tasks/$0/PRD.md`

**Important:** Do NOT start implementing. Just create the PRD.

---

## The Original PRD

@.ralpher/tasks/$0/PRD.md

---

## User Provided Input

@$1

---

## Step 1: (Optional) Clarifying Questions

Ask only critical questions where the user prompt is ambiguous.

---

## Step 2: Update PRD

Update the PRD document.

Please refer to @!`echo $RALPHER_PLUGIN`/docs/prd-structure.md for a list of required sections and an example.

Strictly follow the user's instructions, and don't change unrelated parts.

You may need to add/update/remove user stories to fit the new plan.

---

## Checklist

Before saving the PRD:

- [ ] Incorporated the user's instructions
- [ ] (Optional) Asked clarifying questions and incorporated user's answers
- [ ] User stories are small and specific
- [ ] Functional requirements are numbered and unambiguous
- [ ] Non-goals section defines clear boundaries
- [ ] Save to `.ralpher/tasks/$0/PRD.md`