# SC-88VL midi recorder v2.0mt
# this script will automatically play a list of midi files on an SC-88VL
# and record the output to FLAC.

# only supports Python 3.9

# pip install pipwin
# python -m pipwin install pyaudio

## This is an exercise to see if I could create a multitasking scheduler 
# without the use of threads or subprocesses. This code is highly experimental 
# and likely has inaccurate timing. For any "production" use, I recommend
# using the normal variant of this script (midi_recorder.py).


import os
import time
from enum import Enum
from queue import Queue


class Sig(Enum):
    TERM = 1
    STOP = 2
    PLAYING = 3
    COMPLETE = 4

GM_Reset = [0xF0, 0x7E, 0x7F, 0x09, 0x01, 0xF7]
GS_Reset = [0xF0, 0x41, 0x7F, 0x42, 0x12, 0x40, 0x00, 0x7F, 0x00, 0x41, 0xF7]
XG_Reset = [0xF0, 0x43, 0x7F, 0x4C, 0x00, 0x00, 0x7E, 0x00, 0xF7]

dry_run = False
errors = []

path = r"C:\Users\Frnot\Music\MIDI\Descent 1"
if not path:
    path = os.getcwd()

def main():
    global mido; import mido
    global music_tag; import music_tag
    global numpy; import numpy
    global pyaudio; import pyaudio
    global pyloudnorm; import pyloudnorm
    global soundfile; import soundfile


    chunk = 2048  # Record in chunks of 1024 samples
    sample_format = pyaudio.paInt16  # 16 bits per sample
    channels = 2
    sample_rate = 48000  # Record at 48000 samples per second

    default_midi_device_name = "MOTU M Series MIDI Out 2"
    default_audio_device_id = 2


    #import pyaudio
    audio_port = pyaudio.PyAudio()  # Create an interface to PortAudio
    print(f"Loaded portaudio version {pyaudio.get_portaudio_version_text()}")


    midi_devices = mido.get_output_names()
    while True:
        try:
            print("Synthesizer devices:")
            default_device = None
            for idx, option in enumerate(midi_devices):
                if default_midi_device_name in option:
                    default_device = option
                    selstring = " -> "
                else:
                    selstring = "    "
                print(f"{selstring}{idx} - {option}")

            default_msg = " (or enter for default)" if default_device else ""
            choice = input(f"Choose a device number{default_msg}: ")

            midi_device = default_device if default_device and choice == "" else midi_devices[int(choice)]
            break
        except KeyboardInterrupt:
            exit()
        except (ValueError, IndexError):
            print("Enter a valid device number")
            continue

    

    print("Synthesizer mode:")
    print("1. Roland SC-88VL native")
    print("2. Roland SC-88VL in SC-55 map mode")
    while True:
        choice = input("Choose synth mode: ")
        if choice == "1":
            composer_tag = "Roland SC-88VL"
            break
        elif choice == "2":
            composer_tag = "Roland SC-88VL (SC-55 map)"
            break
        else:
            continue


    
    info = audio_port.get_host_api_info_by_index(0)
    numdevices = info.get("deviceCount")
    while True:
        try:
            print("Available Input Devices:")
            valid_ids = []
            for i in range(0, numdevices):
                if (audio_port.get_device_info_by_host_api_device_index(0, i).get("maxInputChannels")) > 0:
                    valid_ids.append(i)
                    selstring = " -> " if i is default_audio_device_id else "    "
                    print(f"{selstring}{i} - "
                        + audio_port.get_device_info_by_host_api_device_index(0, i).get("name")
                    )
            
            default_msg = " (or enter for default)" if default_device else ""
            choice = input(f"Choose a device number{default_msg}: ")

            audio_device_id = default_audio_device_id if default_audio_device_id and choice == "" else int(choice)
            if audio_device_id not in valid_ids:
                raise ValueError
            input_device = audio_port.get_device_info_by_host_api_device_index(0, audio_device_id)
            break
        except KeyboardInterrupt:
            exit()
        except (OSError, ValueError):
            print("Enter a valid device number")
            continue
            
    

    print(f"Recording '{composer_tag}' on input device '{input_device.get('name')}'\n")
    try:
        audio_stream = audio_port.open(
            input_device_index=audio_device_id,
            format=sample_format,
            channels=channels,
            rate=sample_rate,
            frames_per_buffer=chunk,
            input=True,
            start=False,
        )
    except Exception as e:
        print(e)
        return


    clipped = []
    max_peak = (0, None)
    # record files
    for root, d_names, f_names in os.walk(path):
        for file in f_names:
            if not file.lower().endswith(".mid"):
                continue

            filepath = os.path.join(root, file)
            flacname = os.path.splitext(file)[0] + ".flac"
            flacpath = os.path.join(root, flacname)

            if os.path.exists(flacpath):
                print(f"File \"{flacname}\" already exists. skipping \"{file}\"")
                continue

            frames = []
            task_queue = Queue()
            task_queue.put(record_synth(audio_stream, chunk, frames))
            task_queue.put(play_midi(midi_device, filepath))

            # Record MIDI
            playing = True
            try:
                while not task_queue.empty():
                    task = task_queue.get()

                    sig = None if playing else Sig.COMPLETE
                    sig = task.send(sig)

                    if sig == Sig.COMPLETE:
                        playing = False

                    if sig != Sig.STOP:
                        task_queue.put(task)
            except KeyboardInterrupt:
                for task in task_queue:
                    task.send(Sig.TERM)
                audio_stream.close()
                exit()

            # Convert PyAudio frames to audio samples
            frames = numpy.frombuffer(b"".join(frames), dtype=numpy.int16)
            samples = numpy.stack((frames[::2], frames[1::2]), axis=1)

            # Measure audio levels
            try:
                meter = pyloudnorm.Meter(sample_rate)  # BS.1770 meter
                norm_samples = samples / numpy.iinfo(numpy.int16).max
                loudness = meter.integrated_loudness(norm_samples)  # measure loudness
                print(f"loudness: {loudness} LUFS")

                peak = numpy.max(numpy.abs(samples))
                print(f"peak: {peak}")
                if peak > max_peak[0]:
                    max_peak = (peak, file)
                if peak >= numpy.iinfo(numpy.int16).max:
                    print("\nAudio clipped. Adjust Synth output")
                    clipped.append(file)
                    #continue
            except Exception as e:
                print(e)

            # Save data to flac
            try:
                soundfile.write(flacpath, samples, sample_rate)
            except Exception as e:
                print(e)

            # write tag info
            try:
                f = music_tag.load_file(flacpath)
                f["composer"] = composer_tag
                f.save()
            except Exception as e:
                print(e)

            print()
            

    audio_stream.close()
    print(f"Max peak: {max_peak[0]} - {max_peak[1]}")
    print("Files that clipped:")
    for file in clipped:
        print(file)
    input()


def coroutine(func):
    def start(*args,**kwargs):
        cr = func(*args,**kwargs)
        next(cr)
        return cr
    return start


@coroutine
def play_midi(device, filepath):
    try:
        synth = mido.open_output(device)
        synth.send(mido.Message.from_bytes(GM_Reset))
        synth.send(mido.Message.from_bytes(GS_Reset))
        yield
        
        # play file
        print(f"Playing '{os.path.basename(filepath)}'")
        for msg in mido.MidiFile(filepath, clip=True).play():
            synth.send(msg)
            sig = yield
            if sig == Sig.TERM:
                return

        # let sustain ring out
        wait_time = time.time() + 0.3
        while time.time() < wait_time:
            yield
        yield Sig.COMPLETE
    except Exception as e:
        print(f'Exception with file: "{filepath}"\n{e}')
        return False
    finally:
        print("Stopping MIDI playback")
        for i in range(16):
            msg = mido.Message.from_hex(f"B{i:x} 78 00")
            synth.send(msg)
        synth.send(mido.Message.from_bytes(GM_Reset))
        synth.send(mido.Message.from_bytes(GS_Reset))
        synth.close()
        yield Sig.STOP


@coroutine
def record_synth(audio_stream, chunk, frames): 
    partial_chunk = int(chunk*0.9)
    yield
    print("Recording track")
    audio_stream.start_stream()
    while True:
        if audio_stream.get_read_available() >= partial_chunk:
            data = audio_stream.read(chunk)
            sig = yield
            frames.append(data)
            sig = yield
        else:
            sig = yield
        if sig == Sig.TERM or sig == Sig.COMPLETE:
            break

    print("Finished recording")
    audio_stream.stop_stream()
    yield Sig.STOP


if __name__ == "__main__":
    while True:
        try:
            main()
        except ModuleNotFoundError as missing_pkg:
            inp = input(f"Package '{missing_pkg.name}' required. Install it now? (y/N): ")
            if "y" in inp.lower():
                import subprocess
                import sys
                subprocess.check_call([sys.executable, "-m", "pip", "install", missing_pkg.name])
                print("\n")
                continue
            break
