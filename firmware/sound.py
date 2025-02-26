# make floppy music!

from rp2 import PIO, asm_pio, StateMachine
from machine import Pin, freq, mem32
import utime

# there's no built-in way to do this, so HAX
# also note that the upper limit on the original Pico is 8
# and since I have an original Pico and only 3 drives, I
# haven't tested any more than this!
def _update_sm_freq(sm, f):
    if f == 0:
        return False
    if sm < 0 or sm >= 12:
        raise ValueError("state machine index out of range")
    base = [0x50200000, 0x50300000, 0x50400000][sm >> 2]
    offset = [0x0c8, 0x0e0, 0x0f8, 0x110][sm & 3]
    div = (freq() * 256) // f
    if div < 0x100 or div >= 0x1000000:
        return False
    mem32[base + offset] = div << 8
    return True

def _reset_drive(base_pin, tracks, target=0):
    ds = Pin(base_pin, Pin.OUT, value=0)
    dp = Pin(base_pin + 1, Pin.OUT, value=1)
    step = Pin(base_pin + 2, Pin.OUT, value=1)
    for _ in range(tracks):
        step.value(0)
        utime.sleep_ms(5)
        step.value(1)
        utime.sleep_ms(5)
    dp.value(1)
    utime.sleep_ms(50)
    for _ in range(target):
        step.value(0)
        utime.sleep_ms(5)
        step.value(1)
        utime.sleep_ms(5)
    ds.value(1)
    utime.sleep_ms(50)

# scan back and forth across the disk
@asm_pio(out_init=(PIO.OUT_HIGH), set_init=(PIO.OUT_HIGH))
def _scan_prog():
    pull()
    mov(x, 0)
    label("bounce")
    mov(pins, x)
    mov(y, osr)
    label("step")
    set(pins, 0)[11]
    set(pins, 1)[11]
    jmp(y_dec, "step")
    mov(x, invert(x))[8] # skip a beat when switching directions because physics
    jmp("bounce")
    
# oscillate back and forth one track
@asm_pio(out_init=(PIO.OUT_HIGH), set_init=(PIO.OUT_HIGH))
def _shake_prog():
    pull()
    wrap_target()
    mov(pins, 0)
    set(pins, 0)[11]
    set(pins, 1)[11]
    mov(pins, 1)
    set(pins, 0)[11]
    set(pins, 1)[11]
    
# GPIO 0 = drive 0 select
# GPIO 1 = drive 0 direction
# GPIO 2 = drive 0 step
# GPIO 3 = drive 1 select ...
class Sound:
    DRIVES = 4

    # scan_mask indicates which drives scan across the whole disk
    # instead of just shaking the head back and forth on one track
    def __init__(self, scan_mask = 0, tracks = 80):
        self.drive_select_pins = []
        self.state_machines = []        
        for drive in range(Sound.DRIVES):
            base_pin = drive * 3
            scan = scan_mask & (1 << drive) != 0
            _reset_drive(base_pin, tracks, 0 if scan else tracks/2)
            self.drive_select_pins.append(Pin(base_pin, Pin.OUT, value=1))
            self.state_machines.append(
                StateMachine(drive,
                             _scan_prog if scan else _shake_prog,
                             freq=2000,
                             out_base=base_pin+1,
                             set_base=base_pin+2))
            self.state_machines[drive].put(tracks - 1);
            
    def stop(self, drive):
        self.state_machines[drive].active(0)
        self.drive_select_pins[drive].value(1)

    def play(self, drive, freq):
        if _update_sm_freq(drive, freq * 25):
            self.drive_select_pins[drive].value(0)
            self.state_machines[drive].active(1)
        else:
            self.stop(drive)
                                       
    def silence(self):
        for drive in range(Sound.DRIVES):
            self.stop(drive)

    def scale(self, drive, octave = 1):
        tabl=[131, 147, 165, 175, 196, 220, 247, 261]
        for f in tabl:
            self.play(drive, f * octave)
            utime.sleep_ms(250)
        self.stop(drive)

