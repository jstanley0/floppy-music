# floppy-music
Music player for floppy drives using Raspberry Pi Pico PIO

## Installation
 * Copy the contents of `firmware` (`sound.py` and `music_player.py` to your Pico), via `rshell cp firmware/* /pyboard` or pasting into Thonny, etc.
 
## Playing songs from the Pico's file system
 * On your computer, run `python3 util/convert_midi.py example.mid example.dat`
 * Copy the output to the Pico via e.g. `rshell cp example.dat /pyboard`. It is a binary file so pasting it via an IDE isn't going to work.
 * On the Pico, instantiate a MusicPlayer and play the song:
```
from music_player import MusicPlayer
mp = MusicPlayer()
mp.play_song('example.dat')
```
## Playing MIDI files from a connected computer
 * run `python3 util/convert_midi.py example.mid -` 
 
## Limitations
Getting music data into a usable format is tricky. I wrote a script (util/convert_midi.py) that translates note-on and note-off events into a simple binary format that the microcontroller program can parse and play. The primary challenge is that we have at most eight notes of polyphony to work with, so it works best with simple MIDI files. I suggest opening files in e.g. MuseScore beforehand to identify channels to prioritize (with -p) or exclude (with -x). If no arguments are given, convert_midi.py will prioritize channels in tracks named "melody" or "vocals".
 
## Bill of Materials
 * one Raspberry Pi Pico
 * one to eight floppy drives
 * power for each drive
  
## Wiring
 * Power the FDDs separately from the Pico (e.g. from your PC's PSU)
 * Connect FDD ground (pin 1) to Pico ground
 * GPIO 0 = Drive 0 ready (pin 12)
 * GPIO 1 = Drive 0 direction (pin 18)
 * GPIO 2 = Drive 0 step (pin 20)
 * GPIO 3 = Drive 1 ready ...

