# Create Project Plan

Create a detailed Project Plan that is clear, actionable, and suitable for implementation.

---

## The Job

1. Receive a feature description from the user
2. Carefully review the current repo to understand the source code and the context
3. Ask 3-10 essential clarifying questions
  * See the "Step 2. Clarifying Questions" section below
  * Don't ask the user to provide more details. Just provide them with a list of concrate options.
  * Use the `StructuredOutput` tool.
4. Generate a markdown Project Plan based on answers and the context
  * Use the `StructuredOutput` tool.

**Important:** Do NOT start implementing. Just create the Project Plan.

---

## User Provided Feature Description

Read the user-provided feature description from the file `{{ prompt_path }}` before doing anything else.

---

## Step 1: Review the current repo

The repo has been checked out to ther target branch of this project for you. Carefully review the current repo and understand the context before making a plan.
{%- if jj %}

This repository is managed with [Jujutsu](https://jj-vcs.github.io/jj/): inspect its history with `jj log` / `jj diff` / `jj show` rather than `git`, and write the plan for an implementer that commits with `jj`, not `git`.
{%- endif %}

---

## Step 2. Clarifying Questions

Ask only critical questions where the initial prompt is ambiguous. Focus on:

- **Problem/Goal:** What problem does this solve?
- **Core Functionality:** What are the key actions?
- **Scope/Boundaries:** What should it NOT do?
- **Success Criteria:** How do we know it's done?
- Any other critical questions

To ask user questions, use the `StructuredOutput` tool with all the questions and finish your turn. The user will provide answers in the next turn.
* `header`: A short header in 1-2 words describing the question
* `question`: The question to ask the user. It should be a multiple-choice single-answer question.
* `options`: A list of 2-6 concrete options. Each option should have:
  * `label`: A short label for the option
  * `description`: A detailed description of the option to help the user choose

If any questions are depend on the answers to other questions, please ask the dependent questions in the next turn after receiving the user's answers.

---

## Step 3: Generate Project Plan

Generate the Project Plan markdown document.

Follow the structure below for the list of required sections and an example:

<plan-structure>
{{ plan_structure }}
</plan-structure>

You can do step-2 multiple times to ask more questions before making the plan.

---

## Checklist

Before outputing the Project Plan:

- [ ] Reviewed the repo and the context
- [ ] Asked clarifying questions
- [ ] Incorporated user's instructions and answers in the project plan
- [ ] The project plan follows the required structure and includes all required sections
- [ ] Output: Use `StructuredOutput` tool to output the project plan markdown content or questions, WITHOUT WRITING TO ANY FILES.
