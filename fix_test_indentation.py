#!/usr/bin/env python3
"""Fix indentation and syntax errors in test files."""

import re
from pathlib import Path


def fix_indentation_errors(content: str) -> str:
    """Fix common indentation and syntax errors."""

    # Fix indentation issues in for loops
    content = re.sub(
        r'(\s+for \w+ in [^:]+:)\s*\n(\s+engine = GameEngine\([^)]+\))\s*\n\s*await engine\.init_database\(\)',
        r'\1\n            engine = GameEngine(database_url="sqlite:///:memory:")\n            await engine.init_database()',
        content
    )

    # Fix misaligned lines after for loops
    content = re.sub(
        r'(\s+)engine = GameEngine\([^)]+\)\s*\n\s*await engine\.init_database\(\)\s*\n(\s+)config =',
        r'\1engine = GameEngine(database_url="sqlite:///:memory:")\n\1await engine.init_database()\n\1config =',
        content
    )

    # Fix database URL format
    content = re.sub(r'database_url=":memory:"', 'database_url="sqlite:///:memory:"', content)

    # Fix missing imports
    if 'import pytest' in content and 'import pytest_asyncio' not in content:
        content = content.replace('import pytest', 'import pytest\nimport pytest_asyncio')

    return content

def fix_test_file(file_path: Path) -> None:
    """Fix a test file."""
    print(f"Fixing {file_path}")

    content = file_path.read_text()
    content = fix_indentation_errors(content)

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

