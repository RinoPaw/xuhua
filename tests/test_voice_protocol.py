from heritage_explorer.voice_protocol import (
    ContextCommand,
    TextCommand,
    UtteranceStartCommand,
    decode_voice_command,
)


def test_decode_utterance_start_returns_typed_command() -> None:
    command = decode_voice_command(
        '{"type":"utterance.start","interrupt":true,"level":0.31,"threshold":0.18}'
    )

    assert command == UtteranceStartCommand(
        interrupt=True,
        level=0.31,
        threshold=0.18,
    )


def test_context_command_canonicalizes_browser_aliases() -> None:
    command = decode_voice_command(
        '{"type":"context","session_id":"abc","category":"传统美术",'
        '"locale":"yue-HK","selected_item":{"title":"汴绣"},'
        '"visible_items":[{"title":"武强木版年画"},{"title":"汴绣"}]}'
    )

    assert command == ContextCommand(
        session_id="abc",
        category="传统美术",
        locale_hint="yue-HK",
        selected_title="汴绣",
        titles=("汴绣", "武强木版年画"),
    )
    assert command.as_event() == {
        "type": "context",
        "session_id": "abc",
        "category": "传统美术",
        "locale_hint": "yue-HK",
        "selected_title": "汴绣",
        "titles": ["汴绣", "武强木版年画"],
    }


def test_text_command_is_canonicalized_at_protocol_boundary() -> None:
    assert decode_voice_command('{"type":"text","text":"  汴绣  "}') == TextCommand("汴绣")


def test_invalid_and_unknown_frames_are_ignored() -> None:
    assert decode_voice_command("not-json") is None
    assert decode_voice_command("[]") is None
    assert decode_voice_command('{"type":"future.command"}') is None
