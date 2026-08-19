import json
from unittest.mock import AsyncMock, patch

import pytest

from ralpher.loop.iterate import ProgressReport, Result, iterate
from ralpher.models import Project, Settings, resolve_jj
from ralpher.prompts import render_prompt
from ralpher.utils.git import check_jj_prerequisites
from ralpher.utils.hooks import HooksManager


class TestJjDefaults:
    def test_settings_jj_off_by_default(self):
        assert Settings().jj is False

    def test_project_jj_off_by_default(self):
        assert Project(id="x").jj is False


class TestResolveJj:
    """--jj/--no-jj wins over the 'jj' key in settings.toml."""

    def _write_settings(self, tmp_path, content: str):
        ralpher = tmp_path / ".ralpher"
        ralpher.mkdir()
        (ralpher / "settings.toml").write_text(content)

    def test_reads_jj_true_from_settings(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        self._write_settings(tmp_path, "jj = true\n")
        assert resolve_jj(None) is True

    def test_defaults_false_when_settings_absent(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert resolve_jj(None) is False

    def test_defaults_false_when_key_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        self._write_settings(tmp_path, "[models]\n")
        assert resolve_jj(None) is False

    def test_flag_overrides_settings(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        self._write_settings(tmp_path, "jj = true\n")
        assert resolve_jj(False) is False

    def test_flag_wins_without_settings(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert resolve_jj(True) is True


class TestCheckJjPrerequisites:
    """--jj needs the CLI on PATH and a git-colocated jj workspace."""

    def _stub(self, monkeypatch, *, on_path: bool, root: str | None):
        monkeypatch.setattr(
            "ralpher.utils.git.shutil.which",
            lambda name: "/usr/bin/jj" if on_path and name == "jj" else None,
        )
        monkeypatch.setattr("ralpher.utils.git.jj_root", lambda: root)

    def test_fails_when_jj_not_on_path(self, monkeypatch, tmp_path):
        self._stub(monkeypatch, on_path=False, root=str(tmp_path))
        with pytest.raises(SystemExit):
            check_jj_prerequisites()

    def test_fails_outside_a_jj_repo(self, monkeypatch):
        self._stub(monkeypatch, on_path=True, root=None)
        with pytest.raises(SystemExit):
            check_jj_prerequisites()

    def test_fails_when_not_colocated_with_git(self, monkeypatch, tmp_path):
        self._stub(monkeypatch, on_path=True, root=str(tmp_path))
        with pytest.raises(SystemExit):
            check_jj_prerequisites()

    def test_passes_for_a_colocated_workspace(self, monkeypatch, tmp_path):
        (tmp_path / ".git").mkdir()
        self._stub(monkeypatch, on_path=True, root=str(tmp_path))
        check_jj_prerequisites()


class TestJjPrompts:
    """The rendered prompts tell the agent which VCS to drive."""

    def _iterate(self, *, jj: bool) -> str:
        return render_prompt(
            "iterate",
            current_task_path="/tmp/current_task.json",
            plan_path="/tmp/PLAN.md",
            progress_path="/tmp/progress.md",
            jj=jj,
            context_file="CLAUDE.md",
        )

    def _verify(self, *, jj: bool) -> str:
        return render_prompt(
            "verify",
            current_task_path="/tmp/current_task.json",
            plan_path="/tmp/PLAN.md",
            jj=jj,
        )

    def test_iterate_defaults_to_git(self):
        prompt = self._iterate(jj=False)
        assert "obvious in `git log`" in prompt
        assert "jj" not in prompt

    def test_iterate_instructs_jj(self):
        prompt = self._iterate(jj=True)
        assert 'jj commit -m "<message>"' in prompt
        assert "Use `jj`, Not `git`" in prompt
        assert "obvious in `git log`" not in prompt

    def test_verify_defaults_to_git(self):
        prompt = self._verify(jj=False)
        assert "git log -1 --stat" in prompt
        assert "jj show" not in prompt

    def test_verify_instructs_jj(self):
        prompt = self._verify(jj=True)
        assert "jj show @-" in prompt
        assert "git log -1 --stat" not in prompt

    @pytest.mark.parametrize("name", ["plan", "refine"])
    def test_plan_prompts_mention_jj_only_when_enabled(self, name):
        paths = {"prompt_path": "/tmp/PROMPT.md"}
        if name == "refine":
            paths = {"plan_path": "/tmp/PLAN.md", "input_path": "/tmp/in.md"}
        assert "Jujutsu" in render_prompt(name, jj=True, **paths)
        assert "Jujutsu" not in render_prompt(name, jj=False, **paths)


class TestIteratePassesJj:
    """`Project.jj` reaches the implementation and verification prompts."""

    @patch("ralpher.loop.iterate.run_agent", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_prompts_are_rendered_with_project_jj(
        self, mock_run, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        project = Project(id="jj-run", jj=True)
        project.project_dir.mkdir(parents=True)
        project.current_iteration = 0
        project.current_task_id = "T-001"
        project.tasks_json.write_text(
            json.dumps(
                {
                    "tasks": [
                        {
                            "id": "T-001",
                            "title": "Do the thing",
                            "description": "…",
                            "acceptance_criteria": ["it works"],
                            "passes": False,
                        }
                    ]
                }
            )
        )
        project.progress_md.write_text("# Progress\n")

        mock_run.side_effect = [
            ProgressReport(notes="did the thing"),
            Result(task_passed=True),
        ]
        await iterate(project, HooksManager([]))

        implement_prompt = mock_run.call_args_list[0][1]["prompt"]
        verify_prompt = mock_run.call_args_list[1][1]["prompt"]
        assert 'jj commit -m "<message>"' in implement_prompt
        assert "jj show @-" in verify_prompt
