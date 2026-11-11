"""Codex ignores disable-model-invocation and reads only agents/openai.yaml."""
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = re.compile(r"^policy:\n(?:[ \t]+.*\n)*?[ \t]+allow_implicit_invocation:[ \t]*false[ \t]*$", re.M)


def frontmatter(skill: Path) -> str:
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    return text.split("---", 2)[1] if text.startswith("---") else ""


class CodexSkillPolicyTests(unittest.TestCase):
    def test_hidden_common_skills_are_hidden_from_codex(self):
        # common/skills is what Codex sees through ~/.agents/skills.
        hidden = [
            skill for skill in sorted((ROOT / "common/skills").iterdir())
            if (skill / "SKILL.md").is_file()
            and re.search(r"^disable-model-invocation:\s*true\s*$", frontmatter(skill), re.M)
        ]
        self.assertTrue(hidden)
        for skill in hidden:
            with self.subTest(skill=skill.name):
                policy = skill / "agents/openai.yaml"
                self.assertTrue(policy.is_file(), f"{skill.name}: add agents/openai.yaml")
                self.assertRegex(policy.read_text(encoding="utf-8"), POLICY)


if __name__ == "__main__":
    unittest.main()
