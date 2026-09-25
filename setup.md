# Workstation Setup

Shared workstation setup for the consolidated Godogen source repo.

## .NET 9 SDK

Godot 4.5+ requires .NET 9.

### Linux (Ubuntu/Debian)

```bash
wget -q https://dot.net/v1/dotnet-install.sh -O /tmp/dotnet-install.sh
chmod +x /tmp/dotnet-install.sh
/tmp/dotnet-install.sh --channel 9.0 --install-dir ~/.dotnet
```

Add to `~/.bashrc`:

```bash
export PATH="$HOME/.dotnet:$PATH"
export DOTNET_ROOT="$HOME/.dotnet"
```

### macOS

```bash
brew install dotnet@9
```

## Rust

Bevy projects require a current Rust toolchain:

```bash
rustup update stable
cargo --version
rustc --version
```

## Node.js And Browser

The Tripo CLI needs Node.js 20+ for every engine (`npm install -g tripo-cli`); Babylon.js projects need 22.12+:

```bash
node --version
npm --version
```

Browser capture requires Chrome or Chromium with hardware WebGL2. Install one system browser and set `CHROME_BIN` if it is not on a common path:

```bash
command -v google-chrome || command -v chromium || command -v chromium-browser
export CHROME_BIN=/path/to/chrome
```

Babylon capture prefers hardware WebGL2. A fallback to a software renderer (SwiftShader, llvmpipe, lavapipe, etc.) on a GPU-equipped host means the browser GPU path is misconfigured and worth fixing; on a GPU-less host it still captures, at reduced quality and speed.

## System Packages

```bash
sudo apt-get install vulkan-tools xvfb ffmpeg imagemagick
```

- **vulkan-tools** — `vulkaninfo` for GPU validation
- **xvfb** — virtual X11 display for headless Godot/Bevy runs and capture
- **ffmpeg** — MP4 encoding of proof videos and sprite frame extraction
- **imagemagick** — image resize, flip, crop for sprite pipelines

On macOS:

```bash
brew install coreutils ffmpeg dotnet@9
```

## Python

Requires Python 3.10+.

```bash
python3 --version
pip install -r asset-gen/tools/requirements.txt
pip install google-genai
```

In a published game repo, the same asset-generation requirements file lives at:

- `.claude/skills/asset-gen/tools/requirements.txt` for Claude Code
- `.agents/skills/asset-gen/tools/requirements.txt` for Codex

`google-genai` is required by `asset_gen.py` for Gemini image generation.

## Godot (.NET edition)

The **.NET edition** is required for Godot projects. The standard Godot build cannot run C# scripts.

### Linux

```bash
VERSION=$(curl -s https://api.github.com/repos/godotengine/godot/releases/latest | grep -oP '"tag_name": "\K[^"]+' | sed 's/-stable//')
echo "Installing Godot .NET $VERSION"
cd /tmp
wget https://github.com/godotengine/godot/releases/download/${VERSION}-stable/Godot_v${VERSION}-stable_mono_linux_x86_64.zip
unzip Godot_v${VERSION}-stable_mono_linux_x86_64.zip
sudo mv Godot_v${VERSION}-stable_mono_linux_x86_64/Godot_v${VERSION}-stable_mono_linux.x86_64 /usr/local/bin/godot
sudo mv Godot_v${VERSION}-stable_mono_linux_x86_64/GodotSharp /usr/local/bin/GodotSharp
```

`GodotSharp/` must live next to the `godot` binary. Godot resolves it relative to itself.

### macOS

```bash
brew install --cask godot-mono
sudo rm -f /usr/local/bin/godot   # clear any symlink first: tee would write through it onto the Godot binary
printf '#!/bin/sh\nexec /Applications/Godot_mono.app/Contents/MacOS/Godot "$@"\n' | sudo tee /usr/local/bin/godot >/dev/null
sudo chmod +x /usr/local/bin/godot
```

`godot` must be a wrapper script, not a symlink. Godot resolves `GodotSharp/` (in the bundle's `Contents/Resources/`) from the path it was invoked as, so through a symlink it looks in `/usr/local/bin/` and fails — as a silent hang, since macOS shows fatal errors in a modal that `--headless` can't dismiss. Skip the plain `godot` cask: its `godot` command runs the build without C#.

### Verify

```bash
dotnet --version                    # 9.0.x
godot --version                     # 4.x.x.stable.mono
timeout 60 godot --headless --quit  # may show harmless RID warnings
```

Assembly errors (Linux) or a timeout with output ending at `.NET: Initializing module...` (macOS) mean `godot` can't find `GodotSharp/`:

```bash
ls "$(dirname "$(which godot)")"/GodotSharp/   # Linux: must sit next to the binary
head -2 "$(which godot)"                       # macOS: must be the wrapper script above
```

## Character Animation (Optional)

Custom humanoid animation (the asset-gen skill's `motion.md`) additionally requires:

- NVIDIA GPU with a working CUDA driver. Modest is fine: the text encoder runs on CPU (needs ≥20 GB free RAM), diffusion peaks ~2.5 GB VRAM; ~35 GB disk
- `cmake` — the Kimodo install builds a compiled extension

### Dependency layout

The animation stack is machine-level: one copy per workstation, shared by every game project. It lives under a single directory, with these exact names:

```
$KIMODO_HOME/
├── kimodo-practical/   # the animation lib — reference clone; projects clone their workspace from it
├── kimodo/             # upstream NVIDIA Kimodo checkout, editable-installed into kimenv/
├── kimenv/             # the pipeline venv — run the lib's python tools with kimenv/bin/python
└── text_encoders/      # local Llama-3 encoder mirror (built by the lib's setup_text_encoder.py)
```

Model weights — the ~3 GB Kimodo checkpoint and the 16 GB Llama base — live in `~/.cache/huggingface`; `text_encoders/` is symlinks into it. Install steps for all four entries: `kimodo-practical/KIMODO.md` §1, run from `$KIMODO_HOME`. The venv is not relocatable (absolute shebangs, editable install) — pick the location once, or rebuild the venv after a move.

Export in `~/.bashrc` (and `~/.zshrc`):

```bash
export KIMODO_HOME="$HOME/Documents/kimodo-home"
```

A set `KIMODO_HOME` is the signal agents key on: the stack is installed and complete under it — reuse it, never re-fetch or search the filesystem. It is the only animation env var; upstream Kimodo's own variables derive from the fixed layout and are set per command (`TEXT_ENCODERS_DIR="$KIMODO_HOME/text_encoders"`, `TEXT_ENCODER_DEVICE=cpu`), as `motion.md` and the lib's docs instruct.

Verify:

```bash
"$KIMODO_HOME/kimenv/bin/python" -c "import kimodo, torch; print(torch.cuda.is_available())"  # True
ls "$KIMODO_HOME/text_encoders/llama3-8b-instruct-base/config.json"
```

## Local Image Generation (Optional)

A `qwen-image` command on `PATH` runs [Qwen-Image-2.1](https://huggingface.co/Qwen/Qwen-Image-2.1) on the local GPU. When the asset-gen skill finds it, simple images are generated there for free; otherwise they go to the paid APIs.

Requires an NVIDIA GPU with a working CUDA driver and ~33 GB of weights to download. Unquantized, the model wants ~40 GB VRAM; quantized with CPU offload, a 12 GB card with 23 GB RAM runs it at ~2.5 min per 1024² image.

GPUs, drivers, and memory differ too much for one recipe, so there isn't one: on the target machine, have Claude Code build the command from the brief below.

### Brief

Goal: a `qwen-image` command on `PATH` that runs Qwen-Image-2.1 (https://huggingface.co/Qwen/Qwen-Image-2.1, diffusers `QwenImage21Pipeline`) locally with the interface below. Download the model, quantize/offload if the local GPU needs it, implement the CLI in its own isolated Python environment. One-shot command, not a server. It must behave the same from any directory and shell, whatever the caller's environment (an active venv, `PYTHONPATH`, `LD_LIBRARY_PATH`) — game agents call it from their own project shells.

- `qwen-image generate PROMPT` | `qwen-image rgba PROMPT` (transparent PNG; the command adds the model's RGBA prompt phrasing itself) | `qwen-image edit -i IMG [-i IMG ...] PROMPT` | `qwen-image info`
- `PROMPT` of `-` reads stdin.
- Options: `-o/--out PATH`, `--size WxH`, `--resolution N` (default 1024), `--steps N` (default 40), `--seed N` (random if omitted), `--cfg F`, `--negative TEXT`, `--json`.
- stdout: absolute output path, or with `--json` `{output, width, height, mode, prompt, seed, steps, cfg, inputs, seconds, peak_vram_gb}` / `{"error": ...}`. Progress on stderr. Exit 0 on success, 1 on failure. Output is PNG.

Known trap: don't quantize the transformer with bitsandbytes LLM.int8 (`load_in_8bit`). Its kernel casts activations to fp16, which overflows on this DiT and returns the same noise for every prompt. NF4 or torchao int8 weight-only are clean.

Verify:

```bash
qwen-image info
qwen-image rgba --resolution 512 --steps 10 "a red apple" -o /tmp/apple.png   # look at it
magick identify -format '%[opaque]\n' /tmp/apple.png                           # False (has transparency)
```

## API Keys

Set in environment:

- `GOOGLE_API_KEY` — Gemini image generation
- `XAI_API_KEY` — xAI Grok image generation and animated-sprite video

Either image key is enough; with both, Gemini is the default and quality-critical assets are generated on each.
- `TRIPO_API_KEY` — image-to-3D conversion via the `tripo` CLI (`npm install -g tripo-cli`, Node 20+)

## WSL2 (Windows)

WSL has no Linux NVIDIA driver and no `nvidia_icd.json`. The GPU reaches Linux through `/dev/dxg` and the libraries in `/usr/lib/wsl/lib`, which speak D3D12 and CUDA — so CUDA (`nvidia-smi`, `onnxruntime-gpu`) works out of the box, but graphics need Mesa to translate to D3D12:

- **Vulkan** needs Mesa's `dzn` ("Dozen", Vulkan over D3D12). Ubuntu's `mesa-vulkan-drivers` leaves it out, so stock Vulkan is `llvmpipe` on the CPU — ~20 s per frame on a heavy 1080p scene, too slow for video. The [kisak-mesa PPA](https://launchpad.net/~kisak/+archive/ubuntu/kisak-mesa) ships it (`libvulkan_dzn.so`, `dzn_icd.json`); upgrade all Mesa packages together:

  ```bash
  sudo add-apt-repository -y ppa:kisak/kisak-mesa
  sudo apt-get update && sudo apt-get upgrade -y
  ```

  Without `sudo`, the same driver works from a user-local copy: pull `libvulkan_dzn.so` out of the PPA's `mesa-vulkan-drivers` package and point the Vulkan loader at it. The loader then sees only this driver — drop the variable once the PPA is installed system-wide.

  ```bash
  base=https://ppa.launchpadcontent.net/kisak/kisak-mesa/ubuntu/pool/main/m/mesa/
  deb=$(. /etc/os-release; curl -s $base | grep -oE "mesa-vulkan-drivers_[^\"]*~${VERSION_CODENAME:0:1}_amd64\.deb" | sort -V | tail -1)   # ~r = resolute, ~n = noble
  curl -so /tmp/vk.deb "$base$deb" && dpkg-deb -x /tmp/vk.deb /tmp/vk
  mkdir -p ~/.local/opt/dzn && cp /tmp/vk/usr/lib/x86_64-linux-gnu/libvulkan_dzn.so ~/.local/opt/dzn/
  printf '{"file_format_version":"1.0.1","ICD":{"api_version":"1.1","library_path":"%s"}}\n' ~/.local/opt/dzn/libvulkan_dzn.so > ~/.local/opt/dzn/dzn_icd.json
  echo 'export VK_DRIVER_FILES=$HOME/.local/opt/dzn/dzn_icd.json' >> ~/.bashrc
  ```

- **OpenGL** uses Mesa's `d3d12` Gallium driver, already in Ubuntu's Mesa, but Mesa picks `llvmpipe` unless told otherwise. Add to `~/.bashrc`:

  ```bash
  export GALLIUM_DRIVER=d3d12
  ```

`dzn` exposes Vulkan 1.2, is flagged non-conformant (it warns `dzn is not a conformant Vulkan implementation`), and runs Godot's Forward+ renderer. **SSAO renders a regular dot-grid pattern on it** — a driver bug, not the scene; shadows, SSIL, glow, and volumetric fog render the same as on `llvmpipe`. Leave SSAO off for WSL captures or treat the pattern as known.

WSLg provides `DISPLAY=:0`, so `godot --path .` opens a window on the Windows desktop. `xvfb-run` still works and keeps unattended captures off the desktop.

Agents run commands in fresh non-interactive shells that may skip `~/.bashrc`: put `GALLIUM_DRIVER` and `VK_DRIVER_FILES` in whatever launches the agent too, and check the `renderer` line of a capture — `llvmpipe` there means the variables didn't reach it.

Getting results in front of the user from WSL: `explorer.exe "$(wslpath -w video.mp4)"` plays a file on the Windows desktop, `explorer.exe /select,"$(wslpath -w file)"` shows it in its folder. Windows reaches servers in WSL at `localhost:<port>`. Tailscale runs on the Windows side, not in WSL, so expose a WSL server to the user's other devices with `tailscale.exe serve --bg --https=<port> http://localhost:<wsl-port>` (tailnet-only). Windows' localhost forwarding for one port can wedge — requests from Windows time out while `curl` inside WSL answers — typically after a client dies mid-download; serving on a different port gets around it.

## Verify Rendering

```bash
VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/nvidia_icd.json vulkaninfo --summary 2>&1 | grep "deviceName"
xvfb-run -a godot --headless --quit
```

On WSL, skip `VK_ICD_FILENAMES` and look for the D3D12 device, then confirm Godot picks it:

```bash
vulkaninfo --summary 2>&1 | grep -E "deviceName|driverName"   # Microsoft Direct3D12 (NVIDIA ...) / Dozen
glxinfo -B | grep "renderer string"                            # D3D12 (NVIDIA ...)   — glxinfo is in mesa-utils
xvfb-run -a godot --rendering-driver vulkan --write-movie /tmp/v.png --quit-after 2 2>&1 | grep "Using Device"
# Vulkan 1.2.x - Forward+ - Using Device #0: NVIDIA - Microsoft Direct3D12 (NVIDIA ...)
```
