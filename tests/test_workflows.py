"""The scalping engine must ride on the reliable dashboard trigger, first, and without being able to fail the build.
State lives on the `data` branch: restored before the engines run, saved after, and no database secrets are involved."""
import os
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..", ".github", "workflows")


def text(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class WorkflowTests(unittest.TestCase):
    def test_dashboard_workflow_runs_the_scalping_engine_first_and_tolerates_its_failure(self):
        t = text("deploy.yml")
        self.assertIn("python scalping_job.py", t)
        self.assertLess(t.index("python scalping_job.py"), t.index("python dashboard.py"))
        block = t[t.index("- name: Scalping engine"):t.index("- name: Generate dashboard")]
        self.assertIn("continue-on-error: true", block)

    def test_state_is_restored_before_and_saved_after_the_engines_and_no_database_secret_is_used(self):
        t = text("deploy.yml")
        self.assertLess(t.index("- name: Restore data"), t.index("python scalping_job.py"))
        self.assertLess(t.index("python dashboard.py"), t.index("- name: Save data"))
        self.assertLess(t.index("- name: Save data"), t.index("upload-pages-artifact"))
        self.assertNotIn("SUPABASE", t)
        self.assertIn("contents: write", t)

    def test_there_is_only_one_writer_of_the_store(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, "scalping.yml")))   # a second workflow would race on the data branch


if __name__ == "__main__":
    unittest.main()
