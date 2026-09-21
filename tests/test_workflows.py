"""The scalping engine must ride on the reliable dashboard trigger, first, and without being able to fail the build."""
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
        for secret in ("KAIRO_SUPABASE_URL", "KAIRO_SUPABASE_ANON_KEY", "KAIRO_PUBLISHER_EMAIL", "KAIRO_PUBLISHER_PASSWORD"):
            self.assertIn(secret, block)

    def test_scalping_has_its_own_workflow_too(self):
        t = text("scalping.yml")
        self.assertIn("python scalping_job.py", t)
        self.assertIn("workflow_dispatch", t)


if __name__ == "__main__":
    unittest.main()
