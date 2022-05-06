# SC-88VL midi recorder v0.2
# this script will automatically play a list of midi files and record the
# output of the SC-88VL to corresponding audio files.


# pip install pipwin
# python -m pipwin install pyaudio
import mido
import music_tag
import numpy
import os
import pyaudio
import pyloudnorm
import soundfile
import time
import wave

dry_run = False
errors = []

path = "C:\\Users\\frnot\\Desktop\\MIDI\\Doom"

chunk = 1024  # Record in chunks of 1024 samples
sample_format = pyaudio.paInt16  # 16 bits per sample
channels = 2
sample_rate = 44100  # Record at 44100 samples per second
device_id = 2

print("Synthesizer choices:")
print("1. Roland SC-88VL")
print("2. Roland SC-88VL in SC-55 map mode")
while True:
    choice = input("Choose synth device: ")
    if choice == "1":
        composer_tag = "Roland SC-88VL"
        break
    elif choice == "2":
        composer_tag = "Roland SC-88VL in SC-55 map mode"
        break
    else:
        continue


port = pyaudio.PyAudio()  # Create an interface to PortAudio
info = port.get_host_api_info_by_index(0)
numdevices = info.get("deviceCount")
print("Available Input Devices:")
for i in range(0, numdevices):
    if (
        port.get_device_info_by_host_api_device_index(0, i).get("maxInputChannels")
    ) > 0:
        selstring = " -> " if i is device_id else "    "
        print(
            selstring
            + "Input Device id "
            + str(i)
            + " - "
            + port.get_device_info_by_host_api_device_index(0, i).get("name")
        )

print(
    f"Recording '{composer_tag}' on input device '{port.get_device_info_by_host_api_device_index(0, device_id).get('name')}'\n"
)


max_peak = (0, None)
# record files
for root, d_names, f_names in os.walk(path):
    for file in f_names:
        if not file.lower().endswith(".mid"):
            continue

        filepath = os.path.join(root, file)
        wavpath = os.path.join(root, os.path.splitext(file)[0] + ".wav")
        flacname = os.path.splitext(file)[0] + ".flac"
        flacpath = os.path.join(root, os.path.splitext(file)[0] + ".flac")

        if os.path.exists(flacpath):
            # print(f"File \"{flacname}\" already exists. skipping \"{file}\"")
            continue

        try:
            track_length = mido.MidiFile(filepath, clip=True).length + 0.1
            # track_length=10
        except Exception as e:
            print(f'Exception with file: "{filepath}"\n{e}')
            continue

        print(f"Recording '{file}' to '{flacname}'")
        print(f"Recording for {track_length} seconds")

        # make sure windows will open midi files with the correct application by default
        os.startfile(filepath)
        # time.sleep(0.05)
        try:
            stream = port.open(
                input_device_index=device_id,
                format=sample_format,
                channels=channels,
                rate=sample_rate,
                frames_per_buffer=chunk,
                input=True,
            )
        except Exception as e:
            print(e)
            continue

        frames = []
        for i in range(0, int(sample_rate / chunk * track_length)):
            data = stream.read(chunk)
            frames.append(data)
        stream.stop_stream()
        stream.close()

        # Save data to wave
        try:
            print(f"Writing to file: {flacpath}")
            wf = wave.open(wavpath, "wb")
            wf.setnchannels(channels)
            wf.setsampwidth(port.get_sample_size(sample_format))
            wf.setframerate(sample_rate)
            wf.writeframes(b"".join(frames))
            wf.close()
        except Exception as e:
            print(e)

        # Measure audio levels
        try:
            data, fs = soundfile.read(wavpath)
            meter = pyloudnorm.Meter(fs)  # BS.1770 meter
            loudness = meter.integrated_loudness(data)  # measure loudness
            print(f"loudness: {loudness} LUFS")

            peak = numpy.max(numpy.abs(data))
            print(f"peak: {peak}")
            if peak >= 1.0:
                print("\nAudio clipped\nAdjust Synth output")

            if peak > max_peak[0]:
                max_peak = (peak, file)

        except Exception as e:
            print(e)

        # Convert wave to flac
        try:
            data, fs = soundfile.read(wavpath)
            soundfile.write(flacpath, data, fs)
        except Exception as e:
            print(e)

        # write tag info
        try:
            f = music_tag.load_file(flacpath)
            f["composer"] = composer_tag
            f.save()
        except Exception as e:
            print(e)

        # Delete wave file
        try:
            os.remove(wavpath)
        except Exception as e:
            print(e)

        # sleep to let possible sustain dissipate
        time.sleep(1)
        print()


print(f"Max peak: {max_peak[0]} - {max_peak[1]}")
input()
