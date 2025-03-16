import utime
import math
from array import array
from machine import Pin, Timer
from sound import Sound

def read_words(filename):
    buffer = bytearray(128)
    with open(filename, 'rb', buffering=0) as file:
        while True:
            n = file.readinto(buffer)
            if n == 0:
                break
            i = 0
            while i + 1 < n:
                yield (buffer[i] << 8) | buffer[i + 1]
                i += 2

class MusicPlayer:
    def __init__(self):
        # scanning is generally quieter than shaking; I use this method
        # on my 5.25" drive which would be too loud otherwise
        self.sound = Sound(1 << 2)

    def play_song(self, filename):
        try:
            cmd_time = utime.ticks_ms()
            for word in read_words(filename):
                cmd_time = self.play_word(word, cmd_time)
        finally:
            self.sound.silence()

    def play_words(self, words, cmd_time):
        try:
            for word in words:
                cmd_time = self.play_word(word, cmd_time)
            return cmd_time
        except KeyboardInterrupt:
            self.sound.silence()
            raise

    def play_word(self, word, cmd_time):
        if word & 0x8000 == 0:
            # note on: V = voice; F = frequency
            # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
            #  0 V3 V2 V1 V0 FA F9 F8 F7 F6 F5 F4 F3 F2 F1 F0
            freq = word & 0x7FF
            voice = (word & 0x7800) >> 11
            self._note_on(voice, freq)

        elif word & 0xc000 == 0x8000:
            # delay: D = delay in milliseconds
            # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
            #  1  0 DD DC DB DA D9 D8 D7 D6 D5 D4 D3 D2 D1 D0
            ms = word & 0x3FFF
            # TODO figure out why utime.sleep_ms() sometimes failed to wake up
            # and then be a bit nicer to the Pico by avoiding this busy wait
            cmd_time = utime.ticks_add(cmd_time, ms)
            while utime.ticks_diff(cmd_time, utime.ticks_ms()) > 0:
                pass

        else:
            # notes off: C = channel; V = voice mask
            # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
            #  1  1  0  0 VB VA V9 V8 V7 V6 V5 V4 V3 V2 V1 V0
            mask = word & 0xFFF
            self._notes_off(mask)

        return cmd_time

    def _note_on(self, voice, freq):
        self.sound.play(voice, freq)

    def _notes_off(self, mask):
        for voice in range(12):
            if 0 != (mask & (1 << voice)):
                self.sound.stop(voice)

