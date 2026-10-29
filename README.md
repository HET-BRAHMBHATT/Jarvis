# J.A.R.V.I.S. — Personal Field Console

A small, local-first voice assistant inspired by the attached Mini JARVIS guide. It is designed to be useful immediately, even before connecting a paid or cloud AI service.

## Start it

1. Install Python 3.10 or newer on Windows.
2. Double-click **run_jarvis.bat**.
3. The console opens the assistant in your browser at http://127.0.0.1:8765. Keep the console window open while you use it; press Ctrl+C in that window to stop the server.

The app uses Python's standard library and browser features. It does not need a virtual environment, package downloads, or an account for its built-in commands. The optional `requirements.txt` is intentionally empty of dependencies.

## What works locally

- Chat-style commands for the local time and date.
- A restricted arithmetic calculator that understands standard symbols, spoken operators, speech variants of lakh, and Indian number scales such as lakh and crore; ask “read this number” to see the latest result in words. It does not evaluate arbitrary Python.
- Personal notes that are saved in `data/notes.json` in this project folder.
- Timers that remain active while the assistant tab is open.
- Links to an allowlist of sites: Google, YouTube, Spotify, GitHub, Wikipedia, and Google Maps.
- Voice replies through the browser’s built-in speech synthesis, with a dedicated stop button.
- A Local/OpenAI conversation-mode switch in the chat header. Your choice is remembered in this browser; built-in commands and notes stay local in either mode.
- Voice input in supported browsers. Tap the mic once to start a hands-free session; it stays ready for the next question after each answer. Tap the mic again to stop immediately. Browser speech recognition may process audio through your browser provider. If the browser asks again, set the local page microphone permission to Allow; private or temporary browser sessions may discard site permissions.

The chat transcript and voice-reply preference are saved in this browser’s local storage. In local mode, messages and notes are not sent to an AI service.

## Optional OpenAI chat

Open-ended AI answers require a configured language model and an API account with available credits and model access. This project supports the OpenAI Responses API. A key can be saved in .env, but creating a key does not add API credits; ChatGPT subscriptions and API billing are separate. Local commands continue to work if cloud usage is unavailable.

1. Copy `.env.example` to a file named `.env` in this folder.
2. Put your key after `OPENAI_API_KEY=`.
3. Save the file and restart `run_jarvis.bat`.

The server reads the key from `.env`; the browser never receives it. When OpenAI mode is selected, open-ended prompts and up to eight recent chat turns are sent to OpenAI. Built-in commands and notes continue to run locally. The interface reports that the key is configured until a live AI request succeeds. A 429 credit or spending-limit error means API billing needs attention; see [OpenAI billing](https://platform.openai.com/settings/organization/billing) and [organization limits](https://platform.openai.com/settings/organization/limits). You can choose a different model with `JARVIS_MODEL=...`. The default is `gpt-5.4-mini`.

J.A.R.V.I.S. uses the OpenAI Responses API for this optional connection. See the [official OpenAI API quickstart](https://developers.openai.com/api/docs/quickstart).

## Deploy on Render

`render.yaml` configures a free Render web service in Singapore. To deploy it, put this project in a Git repository you control, connect that repository to Render, and create the service from the Blueprint. Before the first deploy, provide `JARVIS_ACCESS_PASSWORD` and `OPENAI_API_KEY` as secret environment values in Render. Use a unique password of at least 20 characters. Never commit either value or the local `.env` file. The app asks for the access password using the browser’s built-in sign-in prompt.

The Blueprint stores notes in each visitor’s browser instead of on the service, so notes do not sync between devices and clearing browser data removes them. Render’s free service sleeps after 15 minutes without traffic, may take about a minute to wake, and has an ephemeral filesystem. Free hosting is for testing and hobby use. OpenAI chat also requires API billing credits; creating a key alone does not provide them.

The server accepts the platform-assigned `PORT`, binds to the required public interface in hosted mode, and keeps local runs bound to `127.0.0.1`.

## Privacy and safety

- In local mode, the server listens only on this computer’s loopback address, `127.0.0.1`.
- The `.env` file and saved notes are excluded by `.gitignore`.
- There is no wake word. The microphone is active only during a voice session you start; tap the mic again to stop.
- Notes are stored as plain text in the project folder. Keep that in mind if other people can access your Windows account or project files.
- In Render mode, the app is protected by its access password and notes stay in the current browser’s local storage.
- The built-in tools do not control smart-home devices, unlock doors, delete files, or spend money. The guide recommends adding physical-device control only after the basic assistant is working.

## If it does not open

- Keep the console window open. If it reports that port 8765 is occupied, add `JARVIS_PORT=8766` to `.env`, restart, and use the address printed in the console.
- If Windows does not recognize `py`, install Python 3.10+ and select the option to add Python to PATH, then start the batch file again.
- If voice input is unavailable, use a current version of Chrome or Edge. Text chat and the local tools still work without voice.
- If the browser blocks microphone access, allow it for the local assistant page in the browser’s site settings after pressing the mic button.

## Project files

- `server.py` — local API, safe command handling, note storage, and optional OpenAI connection.
- `index.html`, `styles.css`, `app.js` — responsive assistant interface.
- `run_jarvis.bat` — Windows launcher.
- `.env.example` — optional local AI configuration template.


