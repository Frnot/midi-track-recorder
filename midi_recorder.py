# SC-88VL midi recorder v1.1
# this script will automatically play a list of midi files on an SC-88VL
# and record the output to FLAC.


# pip install pipwin
# python -m pipwin install pyaudio

import os
import threading
import time
from queue import Queue

GM_Reset = [0xF0, 0x7E, 0x7F, 0x09, 0x01, 0xF7]
GS_Reset = [0xF0, 0x41, 0x7F, 0x42, 0x12, 0x40, 0x00, 0x7F, 0x00, 0x41, 0xF7]
XG_Reset = [0xF0, 0x43, 0x7F, 0x4C, 0x00, 0x00, 0x7E, 0x00, 0xF7]

dry_run = False
errors = []

path = r""
if not path:
    path = os.getcwd()

def main():
    autoinstall("mido")
    autoinstall("music_tag")
    autoinstall("numpy")
    autoinstall("pyaudio")
    autoinstall("pyloudnorm")
    autoinstall("soundfile")


    chunk = 1024  # Record in chunks of 1024 samples
    sample_format = pyaudio.paInt16  # 16 bits per sample
    channels = 2
    sample_rate = 44100  # Record at 44100 samples per second

    midi_device_name = "USB Midi"
    audio_device_id = 2

    midi_devices = mido.get_output_names()
    while True:
        try:
            print("Synthesizer devices:")
            for idx, option in enumerate(midi_devices):
                if midi_device_name in option:
                    default_device = option
                    selstring = " -> "
                else:
                    selstring = "    "
                print(f"{selstring}{idx} - {option}")
            choice = input("Choose a device number (or enter for default): ")

            midi_device = default_device if choice == "" else midi_devices[int(choice)]
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


    audio_port = pyaudio.PyAudio()  # Create an interface to PortAudio
    info = audio_port.get_host_api_info_by_index(0)
    numdevices = info.get("deviceCount")
    print("Available Input Devices:")
    for i in range(0, numdevices):
        if (audio_port.get_device_info_by_host_api_device_index(0, i).get("maxInputChannels")) > 0:
            selstring = " -> " if i is audio_device_id else "    "
            print(f"{selstring}{i} - "
                + audio_port.get_device_info_by_host_api_device_index(0, i).get("name")
            )

    print(f"Recording '{composer_tag}' on input device '{audio_port.get_device_info_by_host_api_device_index(0, audio_device_id).get('name')}'\n")
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

            results = Queue()
            playback_event = threading.Event()
            stop_event = threading.Event()
            play_thread = threading.Thread(target=play_midi, args=(stop_event, playback_event, midi_device, filepath))
            record_thread = threading.Thread(target=record_synth, args=(stop_event, playback_event, audio_stream, chunk, results))

            # Record MIDI
            try:
                record_thread.start()
                play_thread.start()

                while play_thread.is_alive() and record_thread.is_alive():
                    time.sleep(0.1)
            except KeyboardInterrupt:
                stop_event.set()
                play_thread.join()
                record_thread.join()
                audio_stream.close()
                exit()
            samples = results.get()

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
                    continue
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



def play_midi(stop: threading.Event, playing: threading.Event, device, filepath):
    try:
        print(f"Playing '{os.path.basename(filepath)}'")
        synth = mido.open_output(device)
        synth.send(mido.Message.from_bytes(GM_Reset))
        synth.send(mido.Message.from_bytes(GS_Reset))

        # MidiFile.__iter__ takes too long to generate messages on the fly
        midifile = [msg for msg in mido.MidiFile(filepath, clip=True)]
        start_time = time.time()
        input_time = 0.0

        # play file
        playing.set()
        for msg in midifile:
            input_time += msg.time

            playback_time = time.time() - start_time
            duration_to_next_event = input_time - playback_time

            if duration_to_next_event > 0.0:
                time.sleep(duration_to_next_event)

            if not isinstance(msg, mido.MetaMessage):
                synth.send(msg)

            if stop.isSet():
                return
        time.sleep(0.3)  # let sustain ring out
        playing.clear()
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

    return True



def record_synth(stop: threading.Event, playing: threading.Event, audio_stream, chunk, results): 
    frames = []
    playing.wait()
    audio_stream.start_stream()
    print("Recording track")
    while playing.isSet():
        data = audio_stream.read(chunk)
        frames.append(data)
        if stop.isSet():
            return

    audio_stream.stop_stream()
    frames = numpy.frombuffer(b"".join(frames), dtype=numpy.int16)
    samples = numpy.stack((frames[::2], frames[1::2]), axis=1)

    results.put(samples)
    


def autoinstall(package):
    import importlib
    try:
        globals()[package] = importlib.import_module(package)
    except ModuleNotFoundError as missing_pkg:
        inp = input(f"Package '{missing_pkg.name}' required. Install it now? (y/N): ")
        if "y" in inp.lower():
            import subprocess
            import sys
            subprocess.check_call([sys.executable, "-m", "pip", "install", missing_pkg.name])
            print("\n")
            globals()[package] = importlib.import_module(package)
        else:
            quit()



if __name__ == "__main__":
    main()
