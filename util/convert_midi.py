from argparse import ArgumentParser
from mido import MidiFile
import re
import io
from pico_connection import PicoConnection

parser = ArgumentParser(description='Convert MIDI file for floppy_music')
parser.add_argument('infile', type=str, help='input midi file')
parser.add_argument('outfile', type=str, help='output binary file, or use - to stream to the Pico')
parser.add_argument('orchestration', type=str, metavar='CHANNEL', nargs='+',
                    help='assign midi channels to drives (one argument per drive, each argument a comma-separated prioritized list; use a negative number to pick the lowest note in a chord)')
args = parser.parse_args()

class Note:
    def __init__(self, midi_note, channel, velocity=0, timestamp=0):
        self.midi_note = midi_note
        self.channel = channel
        self.velocity = velocity
        self.timestamp = timestamp

    def __eq__(self, other):
        if not isinstance(other, Note):
            return False
        
        return self.midi_note == other.midi_note and self.channel == other.channel

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

    def __init__(self, orchestration):
        self.orchestration = orchestration
        self.num_drives = len(orchestration)
        self.notes_playing = [None] * self.num_drives
        self.events = []

    def log_delay(self, delay):
        if self.events and not self.events[-1].notes_on and not self.events[-1].notes_off:
            self.events[-1].delay += delay
        else:
            self.events.append(Event(delay, self._previous_timestamp()))

    def log_note_on(self, note, channel, velocity):
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

    def _find_note_for_voice(self, v, event):
        # orchestration[v] is a prioritized list of MIDI channels assigned to voice v
        # where minus n means pick the *lowest* playing note in channel n
        for ch in self.orchestration[v]:
            notes = [note for note in event.notes_on if note.channel == abs(ch)]
            notes.sort(key=lambda note: note.midi_note)
            if notes:
                return notes[-1] if ch > 0 else notes[0]
        
        return None

    def _write_event(self, event):
        # write delay
        self._write_delay(event.delay)

        # figure notes off and write notes on for each drive
        notes_off_mask = 0
        for v in range(self.num_drives):
            if self.notes_playing[v] in event.notes_off:
                self.notes_playing[v] = None
                notes_off_mask |= (1 << v)

            note_on = self._find_note_for_voice(v, event)
            if note_on is not None:
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
orchestration = [[int(ch) for ch in drive.split(',')] for drive in args.orchestration]
included_channels = set([abs(ch) for sublist in orchestration for ch in sublist])
encoder = Encoder(orchestration)
for msg in midi:
    if msg.time > 0:
        encoder.log_delay(msg.time)
    if not msg.is_meta:
        channel = msg.channel + 1
        if channel in included_channels:
            if msg.type == 'note_on':
                if msg.velocity == 0:
                    encoder.log_note_off(msg.note, channel)
                else:
                    encoder.log_note_on(msg.note, channel, msg.velocity)
            elif msg.type == 'note_off':
                encoder.log_note_off(msg.note, channel)

if args.outfile == '-':
    buf = io.BytesIO()
    encoder.write_output(buf)
    buf.seek(0, io.SEEK_SET)
    PicoConnection().play_song(buf)
else:
    encoder.write_output(open(args.outfile, 'wb'))
