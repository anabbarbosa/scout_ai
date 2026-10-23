import pytest

from scout_ai.cli import COMMANDS, main


@pytest.mark.parametrize("command", sorted(set(COMMANDS) - {"db-setup"}))
def test_stub_commands_are_registered(command: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([command]) == 1
    assert "not implemented yet" in capsys.readouterr().out


def test_requires_a_command() -> None:
    with pytest.raises(SystemExit):
        main([])
