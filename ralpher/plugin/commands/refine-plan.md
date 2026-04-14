# Project Plan Refiner

Refine the Project Plan based on user's input.

---

## The Job

1. Receive a refinement instruction from the user
2. (Optional) Ask 3-10 essential clarifying questions using the `AskUserQuestion` tool if the instruction is ambiguous
  * Don't ask the user to provide more details. Just provide them with a list of concrate options.
  * You can use `AskUserQuestion` multiple times.
3. Update the Project Plan based on the user prompt and the answers
4. Save to `.ralpher/projects/$0/PLAN.md`

**Important:** Do NOT start implementing. Just update the Project Plan.

---

## The Original Project Plan

@.ralpher/projects/$0/PLAN.md

---

## User Provided Input

@$1

---

## Step 1: (Optional) Clarifying Questions

Ask only critical questions where the user prompt is ambiguous.

---

## Step 2: Update Project Plan

Update the Project Plan document.

Please refer to @!`echo $RALPHER_PLUGIN`/docs/plan-structure.md for a list of required sections and an example.

Strictly follow the user's instructions, and don't change unrelated parts.

You may need to add, update, or remove tasks to fit the new plan.

---

## Checklist

Before saving the Project Plan:

- [ ] Incorporated the user's instructions
- [ ] (Optional) Asked clarifying questions and incorporated user's answers
- [ ] Tasks are small and specific
- [ ] Functional requirements are numbered and unambiguous
- [ ] Non-goals section defines clear boundaries
- [ ] Save to `.ralpher/projects/$0/PLAN.md`
