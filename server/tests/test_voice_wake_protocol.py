import asyncio

from heritage_explorer.voice_protocol import TextCommand, WakeCommand, decode_voice_command
from heritage_explorer.voice_transport import dispatch_voice_command


def test_wake_is_a_dedicated_control_command() -> None:
    assert decode_voice_command('{"type":"wake"}') == WakeCommand()
    assert decode_voice_command('{"type":"text","text":"叙华"}') == TextCommand("叙华")


def test_wake_dispatches_acknowledgement_without_entering_text_command_path() -> None:
    class Runtime:
        def __init__(self) -> None:
            self.acknowledgements = 0
            self.commands: list[object] = []

        async def acknowledge_address(self) -> None:
            self.acknowledgements += 1

        async def handle_command(self, command: object) -> None:
            self.commands.append(command)

    async def scenario() -> Runtime:
        runtime = Runtime()
        await dispatch_voice_command(runtime, WakeCommand())  # type: ignore[arg-type]
        return runtime

    runtime = asyncio.run(scenario())
    assert runtime.acknowledgements == 1
    assert runtime.commands == []
