import unittest

from collector.eligibility import evaluate_eligibility


class EligibilityTests(unittest.TestCase):
    def test_meaningful_readme_is_eligible(self):
        result = evaluate_eligibility(
            repository_status="public",
            full_name="owner/repo",
            private=False,
            fork=False,
            archived=False,
            disabled=False,
            mirror_url_present=False,
            commit_sha="abc123",
            description="A useful project",
            readme_text="x" * 300,
        )
        self.assertTrue(result.eligible)
        self.assertEqual(result.reasons, [])

    def test_meaningful_description_without_readme_is_eligible(self):
        result = evaluate_eligibility(
            repository_status="public",
            full_name="owner/repo",
            private=False,
            fork=False,
            archived=False,
            disabled=False,
            mirror_url_present=False,
            commit_sha="abc123",
            description="A useful project with enough description text to pass the eighty character threshold for eligibility",
            readme_text="",
        )
        self.assertTrue(result.eligible)
        self.assertEqual(result.reasons, [])

    def test_empty_description_and_readme_is_ineligible(self):
        result = evaluate_eligibility(
            repository_status="public",
            full_name="owner/repo",
            private=False,
            fork=False,
            archived=False,
            disabled=False,
            mirror_url_present=False,
            commit_sha="abc123",
            description="",
            readme_text="",
        )
        self.assertFalse(result.eligible)
        self.assertIn("insufficient_project_text", result.reasons)

    def test_docusaurus_template_readme_is_ineligible(self):
        readme = (
            "This website is built using [Docusaurus]. "
            "A modern static website generator. "
            "Using SSH: yes. "
            "Not using SSH: no. "
            "npm run deploy. "
        )
        result = evaluate_eligibility(
            repository_status="public",
            full_name="owner/repo",
            private=False,
            fork=False,
            archived=False,
            disabled=False,
            mirror_url_present=False,
            commit_sha="abc123",
            description="",
            readme_text=readme,
        )
        self.assertFalse(result.eligible)
        self.assertIn("template_only_readme", result.reasons)

    def test_coursework_repository_is_ineligible(self):
        result = evaluate_eligibility(
            repository_status="public",
            full_name="owner/homework",
            private=False,
            fork=False,
            archived=False,
            disabled=False,
            mirror_url_present=False,
            commit_sha="abc123",
            description="",
            readme_text="",
        )
        self.assertFalse(result.eligible)
        self.assertIn("excluded_repository_type", result.reasons)

    def test_dotfiles_repository_is_ineligible(self):
        result = evaluate_eligibility(
            repository_status="public",
            full_name="owner/.dotfiles",
            private=False,
            fork=False,
            archived=False,
            disabled=False,
            mirror_url_present=False,
            commit_sha="abc123",
            description="",
            readme_text="",
        )
        self.assertFalse(result.eligible)
        self.assertIn("excluded_repository_type", result.reasons)

    def test_fork_is_ineligible(self):
        result = evaluate_eligibility(
            repository_status="public",
            full_name="owner/repo",
            private=False,
            fork=True,
            archived=False,
            disabled=False,
            mirror_url_present=False,
            commit_sha="abc123",
            description="A useful project",
            readme_text="x" * 300,
        )
        self.assertFalse(result.eligible)
        self.assertIn("fork", result.reasons)

    def test_missing_commit_sha_is_ineligible(self):
        result = evaluate_eligibility(
            repository_status="public",
            full_name="owner/repo",
            private=False,
            fork=False,
            archived=False,
            disabled=False,
            mirror_url_present=False,
            commit_sha=None,
            description="A useful project",
            readme_text="x" * 300,
        )
        self.assertFalse(result.eligible)
        self.assertIn("missing_launch_commit", result.reasons)

    def test_inaccessible_repository_is_ineligible(self):
        result = evaluate_eligibility(
            repository_status="private",
            full_name="owner/repo",
            private=True,
            fork=False,
            archived=False,
            disabled=False,
            mirror_url_present=False,
            commit_sha="abc123",
            description="A useful project",
            readme_text="x" * 300,
        )
        self.assertFalse(result.eligible)
        self.assertIn("not_public", result.reasons)


if __name__ == "__main__":
    unittest.main()