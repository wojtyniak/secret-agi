#!/usr/bin/env python3
"""Script to convert test files from sync to async."""

import re
from pathlib import Path


def convert_test_file(file_path: Path) -> None:
    """Convert a test file from sync to async."""
    print(f"Converting {file_path}")

    content = file_path.read_text()

    # Add pytest_asyncio import if not present
    if "import pytest_asyncio" not in content:
        content = content.replace(
            "import pytest", "import pytest\nimport pytest_asyncio"
        )

    # Convert GameEngine instantiation
    content = re.sub(
        r"GameEngine\(enable_persistence=False\)",
        'GameEngine(database_url=":memory:")',
        content,
    )

    # Convert test methods to async
    # Match test methods and add @pytest.mark.asyncio decorator and async keyword
    def add_async_decorator(match):
        indent = match.group(1)
        method_def = match.group(2)
        return f"{indent}@pytest.mark.asyncio\n{indent}async {method_def}"

    content = re.sub(
        r"^(\s*)def (test_\w+\(self\):)",
        add_async_decorator,
        content,
        flags=re.MULTILINE,
    )

    # Add await engine.init_database() after GameEngine creation
    content = re.sub(
        r'(engine = GameEngine\(database_url=":memory:"\))',
        r"\1\n        await engine.init_database()",
        content,
    )

    # Convert sync method calls to async
    replacements = [
        (r"engine\.create_game_sync\(", "await engine.create_game("),
        (r"engine\.perform_action_sync\(", "await engine.perform_action("),
        (
            r"engine\.simulate_to_completion_sync\(",
            "await engine.simulate_to_completion(",
        ),
        (r"engine\.save_game_sync\(", "await engine.save_game("),
        (r"create_game_sync\(", "await create_game("),
        (r"run_random_game_sync\(", "await run_random_game("),
    ]

    for pattern, replacement in replacements:
        content = re.sub(pattern, replacement, content)

    # Fix convenience function calls to use database_url
    content = re.sub(
        r"await create_game\(([^)]+)\)",
        r'await create_game(\1, database_url=":memory:")',
        content,
    )
    content = re.sub(
        r"await run_random_game\(([^)]+)\)",
        r'await run_random_game(\1, database_url=":memory:")',
        content,
    )

    # Fix imports
    content = re.sub(
        r"from secret_agi\.engine\.game_engine import GameEngine, run_random_game_sync",
        "from secret_agi.engine.game_engine import GameEngine, run_random_game",
        content,
    )

    file_path.write_text(content)
    print(f"Converted {file_path}")


def main():
    """Main function."""
    test_files = [
        Path("tests/test_game_engine.py"),
        Path("tests/test_integration.py"),
        Path("tests/test_scenarios.py"),
    ]

    for test_file in test_files:
        if test_file.exists():
            convert_test_file(test_file)
        else:
            print(f"Warning: {test_file} not found")


if __name__ == "__main__":
    main()
