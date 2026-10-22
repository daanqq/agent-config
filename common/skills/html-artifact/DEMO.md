# Before/after demo

A side-by-side screen recording that shows the same scenario before and after the change, embedded in the page as one video.

## Recordings

The user records both versions on a real device: same scenario, same order of actions, starting from the same screen. When the change needs a build, prepare two builds that differ only by the change (same configuration, signing, and test settings), so the recordings differ only where the change does. Emulators hide timing problems behind a fast network and cannot receive real push notifications; prefer the device.

Copy the recordings into a new empty directory and work there. If `ffmpeg` is missing, install the static build from the `imageio-ffmpeg` package into a venv in that directory instead of a system package; it includes `libx264`.

## Sync and trim

1. Make a contact sheet of each recording (4 fps, timestamps drawn) to find each scenario's start and the end of useful footage.
2. Around every start, extract 20 fps frames and pick the first frame where the action becomes visible (for an app launch: the window starting to grow). The offset between the two recordings comes from these frames, not from the contact sheet.
3. Check every scenario in the recording: if the offsets agree within ~0.1 s, use one offset; otherwise cut both recordings at a point where both show the same static screen and sync each part separately.
4. End before any recorder UI (the stop-recording pill or dialog) appears in either recording; both halves get the same duration.
5. Trim with the `trim` filter, not input `-ss`: input seeking keeps frames from the preceding keyframe, and `setpts` then shifts the clip by up to a second.

Done when frames at the start, at each scenario's key moment, and at the end show both halves in the same state, and the clip duration matches the planned one.

## Encode

One side-by-side H.264 clip, so both halves always play in sync:

```bash
ffmpeg -i before.mp4 -i after.mp4 -filter_complex \
  "[0:v]trim=start=B:duration=D,setpts=PTS-STARTPTS,fps=30,scale=560:-2:flags=lanczos,pad=iw+16:ih:0:0:black[a];\
   [1:v]trim=start=A:duration=D,setpts=PTS-STARTPTS,fps=30,scale=560:-2:flags=lanczos[b];\
   [a][b]hstack=inputs=2:shortest=1,format=yuv420p" \
  -an -c:v libx264 -preset slow -crf 20 -profile:v high -movflags +faststart clip.mp4
```

Use 560px per half: the page shows the clip at about half that width, so it stays sharp on retina screens. Set both halves to the same explicit even height when `-2` rounds them differently. Prefer H.264 over animated WebP or GIF: for screen recordings it is several times smaller at better quality (a 10 s clip is about 2-3 MB, while lossy WebP of similar quality is about 7 MB and lossless WebP is over 20 MB).

Pass the clip, its pixel size, and a caption naming what each half shows in the `demo` field of the content JSON; `build.py` embeds it as base64 in a muted, looping, autoplaying `<video>`.
