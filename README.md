# Hunter TTS Lab

**Built & customized by The Hunter AI** · [Subscribe on YouTube: The Hunter AI](https://www.youtube.com/@TheHunter-AI)

Clone your own voice and make it read any script, on your own PC, for free.
Hindi, Hinglish and English. It works with an NVIDIA graphics card, with an
AMD or Intel card, and on a PC with no graphics card at all.

![The Studio: script, voice, model, make the voice](docs/studio.png)

## What you get

- **Your voice from 5 to 10 seconds of audio.** Record it in the app or pick a
  file. Save it once, use it for every clip.
- **The app checks your PC and tells you what will run.** It reads your
  processor, RAM and graphics memory and marks the model that suits them.
- **One button to install.** It downloads the model, sets up the engine for
  your hardware, and makes a test clip to prove it works. If one way of
  running does not work on your PC, it tries the next by itself.
- **Long scripts are fine.** A script is cut into short pieces, spoken piece
  by piece and joined, with a progress bar and a Cancel button.
- **Script polishing (optional).** Add a free Google Gemini key and the app
  tidies a script before it is spoken: punctuation, numbers as words, and
  Hinglish turned into Hindi script. In our test that took Chatterbox from
  81% of the words heard right to 100%.
- **Download every clip as a WAV file**, ready for your video editor.
- **Private.** Voices, scripts and clips stay on your PC. Nothing is uploaded.
  The only exception is a script you choose to polish, which goes to Google.

## Start in three steps

1. Download this project: the green **Code** button, then **Download ZIP**,
   and unzip it. (Or `git clone` it.)
2. Double-click **`Start Hunter TTS Lab.bat`**. A black window opens and the
   app opens in your browser. Keep the black window open while you use it.
3. On the **Models** page, press **Install** on the model marked
   "Best for this PC". When it finishes, go to the **Studio**.

You do not need to install Python or anything else. On its first start the
app fetches a small private copy of Python (11 MB) into its own folder.

**Needs:** Windows 10 or 11 (64-bit), 6 GB of free disk space, and internet
for the first setup. After that it works offline.

## Which model for which PC

The app decides this for you. For the curious, this is what it goes by:

| Your PC | Model it picks | 10 seconds of voice takes |
|---|---|---|
| NVIDIA card with 8 GB or more | VoxCPM2 | about 5 seconds |
| NVIDIA card with 4 to 6 GB | Chatterbox | about 5 seconds |
| AMD or Intel card with 4 GB or more | Chatterbox, through Vulkan | about 6 seconds |
| No graphics card, 8 GB RAM | Chatterbox, on the processor | about 1 minute |
| No graphics card, 16 GB RAM | Chatterbox, and VoxCPM2 if you want it | about 1 minute |

![The Models page: what this PC has, and which model suits it](docs/models.png)

The times were measured on one PC (Ryzen 5 5600, RTX 5060 Ti 16 GB, 32 GB
RAM). After installing, the Models page shows the time measured on **your**
PC instead. The Vulkan row was measured on the NVIDIA card running through
Vulkan; it has not been tried on an AMD or Intel card yet.

| Model | Good at | Graphics memory for one piece of text | RAM on a processor |
|---|---|---|---|
| **VoxCPM2** (OpenBMB) | Hinglish: it heard 97% of the words right. 48 kHz sound. | 4.7 GB | 9.1 GB |
| **Chatterbox** (Resemble AI) | Hindi script: 96% of the words right. Light on memory. | 3.2 GB | 3.2 GB |

"Words right" means a speech-to-text service listened to the clips and that
share of the given words came back correct, over 5 Hindi and Hinglish texts.

## Getting a good clone

- Record in a quiet room. No music, no echo, one person.
- 5 to 10 seconds is enough. In our tests a 14 second sample cloned no better
  than its first 6 seconds.
- Speak the way you want the clips to sound. The model copies mood and speed,
  not only the voice.
- For Chatterbox, Hindi written in Devanagari is read more clearly than Hindi
  typed in English letters. Script polishing can convert it for you: the same
  Hinglish script went from 81% of the words heard right to 100% after it
  (VoxCPM2 was at 98% either way).

## Script polishing with Gemini

1. Get a free API key from [Google AI Studio](https://aistudio.google.com/apikey).
2. Paste it on the **Settings** page and choose a model. The ones Google
   usually offers for free are listed first.
3. In the Studio, press **Polish script**.

The key is stored in the app's `data` folder on your PC and is sent only to
Google. Google decides which models are free and how much you can use them.
If the model you picked has run out of its free limit, the app tries the
next free one by itself and remembers the one that answered.

## Your files

Everything the app creates or downloads is in the `data` folder next to it:
voices, clips, models and settings. Delete that folder to start fresh. To
keep it on another drive, set the environment variable
`HUNTER_TTS_LAB_DATA` to a folder before starting.

## If something goes wrong

- **Windows asks "Are you sure you want to run this?"** That is Windows being
  careful with a file that came from the internet. Choose Run (or More info,
  then Run anyway).
- **A model feels slower than it should.** On the Models page press
  **Test again**. The app times every way of running the engine on your PC
  and keeps the fastest; if your graphics driver was updated since, press
  **Check this PC again** first.
- **Install says a way of running "did not work here".** That is the test
  doing its job; the app moves on to the next way by itself (NVIDIA, then
  Vulkan, then the processor) and tells you which one it kept.
- **"The graphics card ran out of memory."** Close games, video editors and
  other AI tools, then try again. Or switch to Chatterbox, the lighter model.
- **It is very slow.** On a processor about a minute per 10 seconds of voice
  is normal. The Models page shows what your PC really does.
- **The browser page says the app is not answering.** The black window was
  closed. Start the app again.
- **The download stopped.** Press Install again. It continues from where it
  stopped, and every file is checked before it is used.

## For developers

The app is plain Python (standard library only) and plain JavaScript, with no
build step.

```
Start Hunter TTS Lab.bat   gets the private Python on first start, runs the app
app/                       the local server: hardware check, recommendation,
                           downloads, engine install and test, voices, speech
web/                       the page (one HTML, one CSS, one JS file)
tests/                     python -m unittest discover tests
data/                      created at run time, never committed
```

`python app/main.py --no-browser --port 7870` runs it with your own Python
3.10 or newer. What gets downloaded, from where and with which checksum is in
`app/catalog.py`.

## Credits and licences

The app is by **The Hunter AI** and is MIT licensed.

The voices are made by other people's work, which the app downloads from
their own pages: the [audio.cpp](https://github.com/0xShug0/audio.cpp) engine
(ShugoAI, Apache 2.0) with the
[Chatterbox](https://github.com/resemble-ai/chatterbox) (Resemble AI, MIT) and
[VoxCPM2](https://github.com/OpenBMB/VoxCPM) (OpenBMB, Apache 2.0) models.
Details are in [THIRD_PARTY.md](THIRD_PARTY.md).

## Use it responsibly

Copy only your own voice, or a voice you have permission to copy. Do not use
a cloned voice to pretend to be someone else.

---

**Built & customized by The Hunter AI** · [youtube.com/@TheHunter-AI](https://www.youtube.com/@TheHunter-AI) · Tutorials, updates and new tools on the channel.
