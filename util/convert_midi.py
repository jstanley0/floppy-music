from argparse import ArgumentParser
from mido import MidiFile
import re
import io
from pico_connection import PicoConnection

parser = ArgumentParser(description='Convert MIDI file for floppy_music')
parser.add_argument('infile', type=str, help='input midi file')
parser.add_argument('-d', '--num_drives', type=int, default=4, help='number of drives to target (default 4)')
parser.add_argument('-p', '--prioritize-channels', type=int, metavar='CHANNEL', nargs='*',
                    help='give specific channels priority when filling voices')
parser.add_argument('-x', '--exclude-channels', type=int, metavar='CHANNEL', nargs='*',
                    help='exclude certain channels from the output file')
parser.add_argument('outfile', type=str, help='output binary file, or use - to stream to the Pico')
args = parser.parse_args()

class Note:
    def __init__(self, midi_note, channel, velocity=0, timestamp=0):
        self.midi_note = midi_note
        self.channel = channel
        self.velocity = velocity
        self.timestamp = timestamp

class Event:
    def __init__(self, delay, previous_timestamp):
        self.delay = delay
        self.timestamp = previous_timestamp + delay
        self.notes_on = []
        self.notes_off = []

    def merge(self, prior_note_off_event):
        if prior_note_off_event.notes_on:
            raise RuntimeError('invalid merge')
        self.delay += prior_note_off_event.delay
        self.notes_off.extend(prior_note_off_event.notes_off)

class Encoder:
    MAX_FREQ=640
    MIN_FREQ=64

    def __init__(self, num_drives, all_channels, priority_channels):
        self.num_drives = num_drives
        self.notes_playing = [Note(None, None)] * num_drives
        self.events = []
        self.all_channels = all_channels
        self.priority_channels = priority_channels

    def log_delay(self, delay):
        if self.events and not self.events[-1].notes_on and not self.events[-1].notes_off:
            self.events[-1].delay += delay
        else:
            self.events.append(Event(delay, self._previous_timestamp()))

    def log_note_on(self, note, channel, velocity):
        if channel == 10:
            # no percussion
            return
        event = self._ensure_event()
        event.notes_on.append(Note(note, channel, velocity, timestamp=event.timestamp))

    def log_note_off(self, note, channel):
        event = self._ensure_event()
        event.notes_off.append(Note(note, channel, timestamp=event.timestamp))

    def write_output(self, outfile):
        self.outfile = outfile
        pending_note_off_event = None
        for event in self.events:
            # if we have a note-off event followed by another event mere milliseconds later,
            # postpone the notes-off until the next event and consolidate delay events
            if pending_note_off_event:
                if event.delay < 0.01:
                    event.merge(pending_note_off_event)
                else:
                    self._write_event(pending_note_off_event)
                pending_note_off_event = None

            # if this event is nothing but notes-off, see if we can merge it with the next one
            if event.notes_off and not event.notes_on:
                pending_note_off_event = event
            else:
                self._write_event(event)

        if pending_note_off_event:
            self._write_event(pending_note_off_event)

    def _ensure_event(self):
        if not self.events:
            self.events.append(Event(0, 0))
        return self.events[-1]

    def _previous_timestamp(self):
        if self.events:
            return self.events[-1].timestamp
        return 0

    def _find_available_voice(self, note):
        return self._channel_affinity_voice(note.channel)
        # with no decay, and voices that sound different, this is hard
        if voice is None:
            return None
        for _ in range(self.num_drives):
            playing = self.notes_playing[voice]
            if playing.midi_note is None:
                return voice
            voice = (voice + 1) % self.num_drives
        return None

    def _channel_affinity_voice(self, channel):
        # TODO cli option for specifying channel affinity (this is clearly hacked for a specific midi)
        match channel:
            case 1 | 7:
                return 2
            case 8:
                return 3
            case _:
                return 0

    def _place_note(self, note):
        if note.channel not in self.all_channels:
            return None

        # find a slot, using channel affinity
        voice = self._find_available_voice(note)
        if voice:
            return voice
        
        # all channels are busy: possibly preempt a playing note
        preempt_candidates = []
        for v in range(self.num_drives):
            playing_note = self.notes_playing[v]
            if playing_note.channel in self.priority_channels:
                continue    # don't preempt a note in a priority channel
            # don't preempt a note that started too recently or it'll sound bad
            if note.channel in self.priority_channels:
                time_threshold = 0.075
            else:
                time_threshold = 0.15
            if note.channel in priority_channels or note.timestamp - playing_note.timestamp > time_threshold:
                playing_note.voice = v
                preempt_candidates.append(playing_note)
        if preempt_candidates:
            doomed_note = min(preempt_candidates, key=lambda note: note.timestamp)
            return doomed_note.voice

        # the note had to be dropped :(
        return None


    def _write_event(self, event):
        # write delay
        self._write_delay(event.delay)

        # figure notes off
        notes_off_mask = 0
        for note_off in event.notes_off:
            for v in range(self.num_drives):
                if note_off.midi_note == self.notes_playing[v].midi_note and note_off.channel == self.notes_playing[v].channel:
                    self.notes_playing[v].midi_note = None
                    self.notes_playing[v].channel = None
                    # crucially, the timestamp is left alone here; this lets us maximize release time
                    notes_off_mask |= (1 << v)

        # write notes on
        # this looks funny because False sorts before True, but this sorts notes in priority channels first
        notes_on = sorted(event.notes_on, key=lambda note: note.channel not in self.priority_channels)
        for note_on in notes_on:
            v = self._place_note(note_on)
            if v != None:
                self.notes_playing[v] = note_on
                self._write_note_on(v, note_on.midi_note)
                # no need to write a note-off for this voice if we're starting a new note here now
                notes_off_mask &= ~(1 << v)

        # write remaining notes off, if any
        if notes_off_mask != 0:
            self._write_notes_off(notes_off_mask)

    def _note_frequency(self, midi_note):
        freq = 440.0 * pow(2, (midi_note - 69.0) / 12)
        while freq > self.MAX_FREQ:
            freq /= 2
        while freq < self.MIN_FREQ:
            freq *= 2
        return round(freq)

    # note on: V = voice; F = frequency
    # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
    #  0 V3 V2 V1 V0 FA F9 F8 F7 F6 F5 F4 F3 F2 F1 F0
    def _write_note_on(self, voice, note):
        u16 = (voice & 0xf) << 11
        u16 |= self._note_frequency(note)
        self._write16(u16)

    # delay: D = delay in milliseconds
    # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
    #  1  0 DD DC DB DA D9 D8 D7 D6 D5 D4 D3 D2 D1 D0
    def _write_delay(self, delay):
        delay = round(delay * 1000)
        while delay > 0x3FFF:
            self._write16(0xBFFF)
            delay -= 0x3FFF
        if delay > 0:
            self._write16(0x8000 | delay)

    # notes off: C = channel; V = voice mask
    # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
    #  1  1  0  0 VB VA V9 V8 V7 V6 V5 V4 V3 V2 V1 V0
    def _write_notes_off(self, voice_mask):
        self._write16(0xC000 | voice_mask)

    def _write16(self, u16):
        self.outfile.write(u16.to_bytes(2, byteorder='big', signed=False))

midi = MidiFile(args.infile)

# NOTE: 1 is added to channels to match user-visible channel numbers in e.g. MuseScore

# I feel like there should be a better way to enumerate channels, but whatevs...
all_channels = set()
for msg in midi:
    if msg.type == 'note_on':
        all_channels.add(msg.channel + 1)

# remove excluded channels
if args.exclude_channels:
    all_channels -= set(args.exclude_channels)

# add priority channels
if args.prioritize_channels:
    priority_channels = set(args.prioritize_channels)
else:
    priority_channels = set()
    melody_track_pattern = re.compile('melody|vocals', re.I)
    for track in midi.tracks:
        if melody_track_pattern.match(track.name):
            track_channels = set()
            for msg in track:
                if msg.type == 'note_on':
                    track_channels.add(msg.channel + 1)
            print("{file}: prioritized melody track \"{name}\" channels {channels}".format(file=args.infile,name=track.name,channels=track_channels))
            priority_channels = priority_channels.union(track_channels)


encoder = Encoder(args.num_drives, all_channels, priority_channels)
for msg in midi:
    if msg.time > 0:
        encoder.log_delay(msg.time)
    if not msg.is_meta:
        if msg.type == 'note_on':
            if msg.velocity == 0:
                encoder.log_note_off(msg.note, msg.channel + 1)
            else:
                encoder.log_note_on(msg.note, msg.channel + 1, msg.velocity)
        elif msg.type == 'note_off':
            encoder.log_note_off(msg.note, msg.channel + 1)

if args.outfile == '-':
    buf = io.BytesIO()
    encoder.write_output(buf)
    buf.seek(0, io.SEEK_SET)
    PicoConnection().play_song(buf)
else:
    encoder.write_output(open(args.outfile, 'wb'))
