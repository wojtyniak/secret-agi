#!/usr/bin/env python3
"""Fix test_scenarios.py to remove fixtures and use local engine."""

import re


def fix_scenarios():
    """Fix the test scenarios file."""

    with open("tests/test_scenarios.py") as f:
        content = f.read()

    # Remove the fixture setup_method entirely
    content = re.sub(
        r'\s*@pytest_asyncio\.fixture\(autouse=True\)\s*async def setup_method\(self\):\s*"""Set up test environment\."""\s*self\.engine = GameEngine\(database_url="sqlite:///:memory:"\)\s*await self\.engine\.init_database\(\)\s*',
        '',
        content,
        flags=re.MULTILINE | re.DOTALL
    )

    # Replace all test methods to create engine locally
    def replace_test_method(match):
        method_def = match.group(1)
        method_body = match.group(2)

        # Add engine creation at the start
        engine_setup = '''        engine = GameEngine(database_url="sqlite:///:memory:")
        await engine.init_database()

'''

        # Replace all self.engine with engine
        method_body = method_body.replace('self.engine', 'engine')

        return method_def + '\n' + engine_setup + method_body

    # Find and replace all test methods
    content = re.sub(
        r'(@pytest\.mark\.asyncio\s*async def test_[^(]+\([^)]*\):\s*"""[^"]*"""\s*)',
        lambda m: m.group(1) + '\n        engine = GameEngine(database_url="sqlite:///:memory:")\n        await engine.init_database()\n        ',
        content
    )

    # Replace remaining self.engine references
    content = content.replace('self.engine', 'engine')

    with open("tests/test_scenarios.py", "w") as f:
        f.write(content)

    print("Fixed test_scenarios.py")

if __name__ == "__main__":
    fix_scenarios()

