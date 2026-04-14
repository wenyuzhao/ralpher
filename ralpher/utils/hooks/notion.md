{%- if status -%}
# 🚦 Status

<callout icon="{{status.icon}}" color="{{status.color}}">
{{status.label}}
</callout>

{% endif -%}
# 🔨 Tasks

{% if plan %}
{% for t in plan.tasks %}
- [{% if t.passes %}x{% else %} {% endif %}] **{{ t.id }}** - {{ t.title }} {% if t.passes %}{{'{color="green"}'}}{% elif t.id == active_task %}{{'{color="blue"}'}}{% else %} {{'{color="yellow"}'}}{% endif %}
{% endfor %}
{% else %}
*N/A*
{% endif %}

# 📂 Git Branch

```
{{branch}}
```

# 📜 Project Plan

<details>
<summary>Click to Expand</summary>
{{plan_md}}
</details>

# 💬 User Prompt

<details>
<summary>Click to Expand</summary>
{{prompt_md}}
</details>

# 🪵 Progress Logs

<details>
<summary>Click to Expand</summary>
{{progress_md}}
</details>