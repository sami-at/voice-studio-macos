"""Output routing regressions without opening a physical audio device."""
from types import MethodType, SimpleNamespace

from voice_studio import ui


class Device:
    def __init__(self, name=''):
        self.name = name

    def id(self): return self.name.encode()
    def description(self): return self.name
    def isNull(self): return not self.name


def routing(monkeypatch):
    state = SimpleNamespace(devices=[Device('Speakers')], default=Device('Speakers'))
    monkeypatch.setattr(ui, 'QMediaDevices', SimpleNamespace(
        audioOutputs=lambda: state.devices, defaultAudioOutput=lambda: state.default))
    output = SimpleNamespace(current=Device('Disconnected Bluetooth'), changes=[])
    output.device = lambda: output.current
    def set_device(device):
        output.current = device
        output.changes.append(device.name)
    output.setDevice = set_device
    player = SimpleNamespace(plays=0, pauses=0)
    player.playbackState = lambda: ui.QMediaPlayer.PlaybackState.PlayingState
    player.play = lambda: setattr(player, 'plays', player.plays + 1)
    player.pause = lambda: setattr(player, 'pauses', player.pauses + 1)
    messages = []
    window = SimpleNamespace(audio_output=output, player=player,
                             status=SimpleNamespace(setText=messages.append))
    window.refresh_output_devices = MethodType(ui.VoiceStudio.refresh_output_devices, window)
    return window, state, messages


def test_play_rebinds_disconnected_cached_output_before_start(monkeypatch):
    window, _, _ = routing(monkeypatch)
    original_output = window.audio_output
    ui.VoiceStudio.start_playback(window)
    assert window.audio_output is original_output
    assert window.audio_output.changes == ['Speakers']
    assert window.player.plays == 1


def test_system_output_follows_changed_default(monkeypatch):
    window, state, _ = routing(monkeypatch)
    window.refresh_output_devices()
    state.default = Device('Headphones')
    state.devices.append(state.default)
    window.refresh_output_devices()
    assert window.audio_output.current.name == 'Headphones'


def test_default_returns_to_speakers_when_bluetooth_disconnects(monkeypatch):
    window, state, messages = routing(monkeypatch)
    state.default = Device('Headphones')
    state.devices.append(state.default)
    window.refresh_output_devices()
    assert window.audio_output.current.name == 'Headphones'
    state.default = Device('Speakers')
    state.devices = [state.default]
    window.refresh_output_devices()
    assert window.audio_output.current.name == 'Speakers'


def test_no_output_does_not_start_playback(monkeypatch):
    window, state, messages = routing(monkeypatch)
    state.devices = []
    state.default = Device()
    ui.VoiceStudio.start_playback(window)
    assert window.player.plays == 0 and window.player.pauses == 1
    assert 'No audio output' in messages[-1]


def test_same_default_is_not_rebound_or_started_on_refresh(monkeypatch):
    window, _, _ = routing(monkeypatch)
    window.refresh_output_devices()
    window.refresh_output_devices()
    assert window.audio_output.changes == ['Speakers']
    assert window.player.plays == 0
