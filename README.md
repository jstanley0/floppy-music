# floppy-music
Music player for floppy drives using Raspberry Pi Pico PIO

## Installation
 * Copy the contents of `firmware` (`sound.py` and `music_player.py` to your Pico), via `rshell cp firmware/* /pyboard` or pasting into Thonny, etc.
 
## Orchestration
MIDI files are generally far too complicated to be played with any fidelity by an array of floppy drives!
You'll need to look at the MIDI file you want to play and assign MIDI channels to each drive. Pass one
argument for each drive in your array. Each argument is a (1-based) MIDI channel number, or a comma-separated
list of channel numbers (where the drive will play notes from any of those channels in the priority given).
You can also pass a negative number to assign the *lowest* note from a chord in the channel; otherwise if 
multiple notes are played in the channel at once, it will pick the highest.

## Playing songs from the Pico's file system
 * On your computer, run `python3 util/convert_midi.py example.mid example.dat (orchestration)`
 * Copy the output to the Pico via e.g. `rshell cp example.dat /pyboard`. It is a binary file so pasting it via an IDE isn't going to work.
 * On the Pico, instantiate a MusicPlayer and play the song:
```
from music_player import MusicPlayer
mp = MusicPlayer()
mp.play_song('example.dat')
```
## Playing MIDI files from a connected computer
 * run `python3 util/convert_midi.py example.mid - (orchestration)` 
 
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

