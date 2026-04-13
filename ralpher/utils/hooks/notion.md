{%- if status -%}
# 🚦 Status

<callout icon="{{status.icon}}" color="{{status.color}}">
{{status.label}}
</callout>

{% endif -%}
# 👤 User Stories

{% if prd %}
{% for us in prd.user_stories %}
- [{% if us.passes %}x{% else %} {% endif %}] **{{ us.id }}** - {{ us.title }} {% if us.passes %}{{'{color="green"}'}}{% elif us.id == active_us %}{{'{color="blue"}'}}{% else %} {{'{color="yellow"}'}}{% endif %}
{% endfor %}
{% else %}
*N/A*
{% endif %}

# 📂 Git Branch

```
{{branch}}
```

# 📜 PRD

<details>
<summary>Click to Expand</summary>
{{prd_md}}
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