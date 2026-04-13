from ralpher.models import PRD, UserStory


class TestUserStory:
    def test_defaults(self):
        story = UserStory(
            id="us-1",
            title="Login",
            description="User can log in",
            acceptance_criteria=["Can enter email"],
            priority=1,
        )
        assert story.passes is False
        assert story.notes == ""

    def test_all_fields(self):
        story = UserStory(
            id="us-2",
            title="Signup",
            description="User can sign up",
            acceptance_criteria=["Email", "Password"],
            priority=2,
            passes=True,
            notes="Done",
        )
        assert story.passes is True
        assert story.notes == "Done"


class TestPRD:
    def _make_prd(self, stories_pass: list[bool] | None = None) -> PRD:
        if stories_pass is None:
            stories_pass = [True, False, True]
        stories = [
            UserStory(
                id=f"us-{i}",
                title=f"Story {i}",
                description=f"Desc {i}",
                acceptance_criteria=[],
                priority=i,
                passes=p,
            )
            for i, p in enumerate(stories_pass)
        ]
        return PRD(
            project="Test",
            description="A test PRD",
            user_stories=stories,
        )

    def test_failed_stories(self):
        prd = self._make_prd([True, False, True, False])
        failed = prd.failed_stories()
        assert len(failed) == 2
        assert all(not s.passes for s in failed)

    def test_failed_stories_all_pass(self):
        prd = self._make_prd([True, True, True])
        assert prd.failed_stories() == []

    def test_failed_stories_none_pass(self):
        prd = self._make_prd([False, False])
        assert len(prd.failed_stories()) == 2

    def test_model_validate_from_dict(self):
        data = {
            "project": "P",
            "branch_name": "b",
            "description": "d",
            "user_stories": [
                {
                    "id": "us-1",
                    "title": "T",
                    "description": "D",
                    "acceptance_criteria": ["AC1"],
                    "priority": 1,
                }
            ],
        }
        prd = PRD.model_validate(data)
        assert prd.project == "P"
        assert len(prd.user_stories) == 1
        assert prd.user_stories[0].passes is False
