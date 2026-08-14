Place the following background assets in this directory:

  black_bg_horizontal.mp4   — 30-minute UHD (3840x2160) black video, landscape
  black_bg_vertical.mp4     — 30-minute UHD (2160x3840) black video, portrait
  black_bg_horizontal.png   — UHD black PNG, landscape (3840x2160)
  black_bg_vertical.png     — UHD black PNG, portrait (2160x3840)

These are used for the "Black Overlay" aspect-fit mode in the stitcher.
The box_zoom mode does not require them.

You can generate them with ffmpeg:
  ffmpeg -f lavfi -i color=black:s=3840x2160:d=1800 -c:v libx264 -crf 0 black_bg_horizontal.mp4
  ffmpeg -f lavfi -i color=black:s=2160x3840:d=1800 -c:v libx264 -crf 0 black_bg_vertical.mp4
  ffmpeg -f lavfi -i color=black:s=3840x2160:vframes=1 black_bg_horizontal.png
  ffmpeg -f lavfi -i color=black:s=2160x3840:vframes=1 black_bg_vertical.png
