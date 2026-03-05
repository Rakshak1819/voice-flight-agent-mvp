from src.app import parse_input_mode_command


def test_parse_input_mode_command_text() -> None:
    assert parse_input_mode_command("/text") == "text"
    assert parse_input_mode_command("switch to text mode") == "text"
    assert parse_input_mode_command("use keyboard input") == "text"


def test_parse_input_mode_command_voice() -> None:
    assert parse_input_mode_command("/voice") == "voice"
    assert parse_input_mode_command("switch to microphone mode") == "voice"
    assert parse_input_mode_command("go to speech mode") == "voice"


def test_parse_input_mode_command_help_or_none() -> None:
    assert parse_input_mode_command("/mode") == "help"
    assert parse_input_mode_command("mode help") == "help"
    assert parse_input_mode_command("/devices") == "devices"
    assert parse_input_mode_command("list devices") == "devices"
    assert parse_input_mode_command("book option two") is None
