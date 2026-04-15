{%- if status -%}
# 🚦 Status

<callout icon="{{status.icon}}" color="{{status.color}}">
{{status.label}}
</callout>

{% endif -%}
# 🔨 Tasks

{% if tasks %}
{% for t in tasks %}
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

<callout>
<details>
<summary>Click to Expand</summary>
{{plan_md}}
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