# Validation evidence

What the reader sees first after the intro: the change working, one item per scenario, in one of these forms:

- a side-by-side before/after screen recording embedded as one video, when the change is in motion: timing, transitions, a flow across screens (Recordings, Sync and trim, Encode);
- screenshots, when the change is visible in a static state: a before/after pair when the old behaviour can be shown, a single screenshot when only the result can (Screenshots).

Pass the items as a list in the `demo` field and say where and how they were checked (stand, test data, anything simulated) in `demo_lead`.

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

Pass the clip, its pixel size, and a caption naming what each half shows as a `demo` item; `build.py` embeds it as base64 in a muted, looping, autoplaying `<video>`. Set `"controls": true` when the clip is long enough that the reader needs to pause or seek (roughly over 30 seconds).

## Screenshots

1. Capture before and after from the same screen, state, and window size, so a pair differs only where the change does.
2. Keep the full frame, uncropped: it shows where on the screen the change is, and the page's image viewer opens every screenshot enlarged, paging through all of them with the arrow keys.
3. Save UI screenshots as PNG (JPEG only for photographic content). The page embeds them as base64; a FullHD UI screenshot is about 100-200 KB.

`build.py` picks the layout from the image size: landscape (desktop) screenshots take the column width, a pair stacked before above after; portrait (mobile) ones sit side by side within 560px, like the video halves. It warns when the two images of a pair differ in size.

Pass a pair as `{"before", "after", "caption"}` and a single screenshot as `{"image", "caption"}`. Done when every scenario has its item and every caption names what the reader should notice.
