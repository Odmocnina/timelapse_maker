# Timelapse Generator

A Python script that generates a timelapse video from a directory of images based on parameters defined in a configuration file. It filters input images by filename prefix and modification time.

# Requirements

The script requires Python 3 and the following dependencies: numpy and open-cv, use this command to install them

```bash
pip install opencv-python numpy

# Usage

Run the script from the command line, providing the path to your configuration file as an argument:

py timelapse.py config.cfg

# Configuration File Format

The script reads parameters from a plain text file using a `key=value` structure. Empty lines and lines starting with `#` are treated as comments and ignored.

## Mandatory Parameters

* **`folder`** = Absolute or relative path to the directory containing the images.
* **`prefix`** = The filename prefix of the images to be processed (e.g., `img_`).
* **`hours`** = How many hours back from the current time to include images (e.g., `24`).
* **`duration`** = Frame duration in **milliseconds** (e.g., `100` results in 10 FPS).
* **`output`** = The desired output filename for the video (e.g., `output.mp4`).

## Optional Parameters

* **`width`** = Target video width in pixels.
* **`height`** = Target video height in pixels.

> **Note:** If `width` and `height` are omitted, the script automatically detects and uses the dimensions of the first valid image.

## Example `config.txt`

#--- Input Settings ---
folder=./input_images
prefix=cam1_

#--- Time (how far back make the video) ---
hours=12

#--- Time (how long will 1 frame last in miliseconds)
duration=100

#--- Output Settings ---
output=timelapse_video.mp4

#--- Optional Dimensions of video ---
width=1920
height=1080
