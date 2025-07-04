#!/usr/bin/env python3
"""Fix syntax errors in converted test files."""

import re
from pathlib import Path


def fix_test_file(file_path: Path) -> None:
    """Fix syntax errors in a test file."""
    print(f"Fixing {file_path}")

    content = file_path.read_text()

    # Fix missing def keywords
    content = re.sub(
        r'(@pytest\.mark\.asyncio)\s*\n\s*async (\w+\(self\):)',
        r'\1\n    async def \2',
        content
    )

    # Remove duplicate init_database calls
    content = re.sub(
        r'await engine\.init_database\(\)\s*\n\s*await engine\.init_database\(\)',
        'await engine.init_database()',
        content
    )

    # Fix incorrect await syntax in method calls
    content = re.sub(r'self\.await engine\.', 'await self.engine.', content)
    content = re.sub(r'self\.await ', 'await ', content)

    # Fix setup_method syntax errors in test_scenarios.py
    if 'setup_method' in content:
        content = re.sub(
            r'def setup_method\(self\):\s*"""Set up test environment\."""\s*self\.engine = GameEngine\(database_url=":memory:"\)\s*await engine\.init_database\(\)',
            '''async def setup_method(self):
        """Set up test environment."""
        self.engine = GameEngine(database_url=":memory:")
        await self.engine.init_database()''',
            content,
            flags=re.MULTILINE | re.DOTALL
        )

    # Fix incorrect await usage in loops
    content = re.sub(
        r'for i in range\(\d+\):\s*engine = GameEngine\(database_url=":memory:"\)\s*await engine\.init_database\(\)',
        lambda m: m.group(0).replace('for i in range', 'for i in range').replace('await engine.init_database()', 'await engine.init_database()'),
        content
    )

    file_path.write_text(content)
    print(f"Fixed {file_path}")

def main():
    """Main function."""
    test_files = [
        Path("tests/test_game_engine.py"),
        Path("tests/test_integration.py"),
        Path("tests/test_scenarios.py"),
    ]

    for test_file in test_files:
        if test_file.exists():
            fix_test_file(test_file)

if __name__ == "__main__":
    main()
