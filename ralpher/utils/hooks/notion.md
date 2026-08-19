{%- if status -%}
# 🚦 Status

<callout icon="{{status.icon}}" color="{{status.color}}">
{{status.label}}
</callout>

{% endif -%}
# 🔨 Tasks

{% if tasks %}
{% for t in tasks %}
- [{% if t.passed %}x{% else %} {% endif %}] **{{ t.id }}** - {{ t.title }} {% if t.passed %}{{'{color="green"}'}}{% elif t.id == active_task %}{{'{color="blue"}'}}{% else %} {{'{color="yellow"}'}}{% endif %}
{% endfor %}
{% else %}
*N/A*
{% endif %}

# 📂 Git Branch

```
{{branch}}
```

# 📐 Design

<callout>
<details>
<summary>Click to Expand</summary>
{{design_md}}
</details>
</callout>

# 📋 Task List

<callout>
<details>
<summary>Click to Expand</summary>
{%- if tasks %}
{%- for t in tasks %}
### {{ t.id }} - {{ t.title }}

{{ t.description }}

**Acceptance Criteria:**
{% for c in t.acceptance_criteria -%}
- {{ c }}
{% endfor %}
{%- endfor %}
{%- else %}
*N/A*
{%- endif %}
</details>
</callout>

# 💬 User Prompt

<callout>
<details>
<summary>Click to Expand</summary>
{{prompt_md}}
</details>
</callout>

# 🪵 Progress Logs

<callout>
<details>
<summary>Click to Expand</summary>
{{progress_md}}
</details>
</callout>