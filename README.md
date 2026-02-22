# Timelapse Generator

A Python script that generates a timelapse video from a directory of images based on parameters defined in a configuration file. It filters input images by filename prefix and modification time. 
It is also capable of connecting through FTP (to download new images and upload the final video), applying multiple watermarks with transparency, cropping images, and cleaning up old files to save disk space.

Image editing is dane in order: crop, adding watermarks, resizing.

@Author: Michael Hladky, Sumavanet.cz

# Requirements

The script requires Python 3 and the following dependencies. You can install them using:

```bash
pip install opencv-python numpy Pillow
```

# Usage

Run the script from the command line, providing the path to your configuration file as an argument:

```bash
py timelapse.py config.cfg
```

# Configuration File Format

The script reads parameters from a plain text file using a `key=value` structure. Empty lines and lines starting with `#` are treated as comments and ignored. Large/small letters should not make effect.

## Mandatory Parameters

* **`folder`** = Absolute or relative path to the directory containing the images.
* **`prefix`** = The filename prefix of the images to be processed (e.g., `img_`).
* **`hours`** = How many hours back from the current time to include images (e.g., `24`).
* **`duration`** = Frame duration in **milliseconds** (e.g., `100` results in 10 FPS).
* **`output`** = The desired output filename for the video (e.g., `output.mp4`). Dynamic Naming: If the filename ends with <h> right before the extension (e.g., video<h>.mp4), the script will replace <h> with a current timestamp (e.g., video_2026-02-21-18-05-40.mp4). If prameter video_folder is set, the video will be saved in that folder, otherwise in the same directory as the script.

## Optional Parameters

### Dimensions
* **`width`** = Target video width in pixels.
* **`height`** = Target video height in pixels.

> **Note:** If `width` and `height` are omitted, the script automatically detects and uses the dimensions of the first valid image.

### Cropping
* **`x`** =  Start x coordinate to crop in width
* **`cx`** = the crop size in width

* **`y`** =  Start y coordinate to crop in height
* **`cy`** = the crop size in height

### Watermarks
* **`logo[Name_or_number];x_of_watermark;y_of_watermark`** = Path to the watermark image and its coordinates, formatted as path;x;y. You can add multiple watermarks by using different keys starting with logo (e.g., logo1, logo2, logomain). Supports PNGs with transparency, GIF files or JPGs images.

Example: logo1=logo/watermark.png;100;100

### FTP stuff
* **`want_ftp_load`** = Set to true to download new images (newer then the newest file from directory) from the FTP server before generating the video. If missing then taken as false.
* **`want_ftp_write`** = Set to true to upload the generated video to the FTP server. If missing then taken as false.
* **`ftp_server`** = Address of the FTP server.
* **`ftp_user`** = FTP username.
* **`ftp_password`** = FTP password.

if want_ftp_load or want_ftp_write, parameters ftp_server, ftp_user, ftp_password are necessery, if they are missing, these functions will not happen.

### logging
* **`log_to_file`** = Set to true to enable logging to a file.
* **`log_file`** = Path to the log file. If not specified, logs will be saved in the same directory as the script with a default name or a timestamped with config file name if log_to_file is enabled.
* **`log_dir`** = Directory where log files will be stored. If not specified, logs will be saved in the same directory as the script with a config name (without extension) or a timestamped name if log_to_file is enabled.

> **Note:** If `log_to_file` is set to true but `log_file` is not specified, the script will attempt to create a log file config_name + timestamp in the directory specified by `log_dir`. If `log_dir` is also not specified, it will fall back to using a default log file name (app.log) in the same directory as the script.

### Directory cleanup (images)
* **`want_directory_clean`** = Set to true to automatically delete images from the local folder that are older than the specified hours limit after the process is finished. If missing then taken as false.

### Directory cleanup (logs)
* **`clear_log_dir`** = Set to true to automatically delete log files from the log directory that are older than value of `log_clean_days` in days after the process is finished. If missing then taken as false.
* **`log_dir`** = Directory where log files are stored. This parameter is required if `clear_log_dir` is set to true.
* **`log_clean_days`** = Number of days to keep log files when `clear_log_dir` is set to true. Log files older than this number of days will be deleted. This parameter is required if `clear_log_dir` is set to true.

### Directory cleanup (videos)
* **`want_video_clean`** = Set to true to automatically delete video files from the output folder that are older than the specified days limit after the process is finished. If missing then taken as false.
* **`video_folder`** = Directory where video files are stored. This parameter is required if `want_video_clean` is set to true.
* **`video_prefix`** = Prefix of video files to consider for deletion when `want_video_clean` is set to true. This parameter is required if `want_video_clean` is set to true.
* **`directory_clean_mp4_days`** = Number of days to keep video files when `want_video_clean` is set to true. Video files older than this number of days will be deleted. This parameter is required if `want_video_clean` is set to true.

## Example `config.txt`

folder=kts2

prefix=raw_

hours=1

duration=100

output=output.mp4

want_FTP_load=TRUE

width=1600

height=1000

ftp_server=ftp_server_here

ftp_user="ftp_user_here"

ftp_password="ftp_password_here"

want_ftp_write=true

want_directory_clean=true

logo1=logo/logo1.gif;100;100

logo2=logo/logo2.png;100;2000

logo3=logo/logo3.jpg;1000;1000

log_to_file=true

log_dir=logs

