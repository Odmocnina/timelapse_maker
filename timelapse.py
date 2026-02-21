import cv2
import os
import argparse
import datetime
import numpy as np
import sys
import ftp_handeler as ftp

"""
    Function to clean up old images from the specified directory based on the configuration.
    param: config - dictionary of parameters, expected keys:
        - wantDirectoryClean (str): "true" if cleanup is enabled, otherwise "false"
        - folder (str): Directory to clean
        - prefix (str): Prefix of image files to consider for deletion
        - hours (float): Age in hours; files older than this will be deleted
"""
def clean_directory(config):
    if str(config.get('wantDirectoryClean', 'false')).lower() != 'true': # control if cleanup is enabled
        return

    print("--- Starting Directory Cleanup ---")
    try: # check for mandatory parameters
        image_folder = config['folder']
        hours_back = float(config['hours'])
        file_prefix = config['prefix']
    except KeyError as e:
        print(f"Cleanup Error: Missing parameter {e}")
        return

    # calculate the timestamp threshold for deletion
    time_threshold = datetime.datetime.now() - datetime.timedelta(hours=hours_back)
    threshold_timestamp = time_threshold.timestamp()
    deleted_count = 0

    if not os.path.exists(image_folder):
        return

    for filename in os.listdir(image_folder): # go over all files in directory if older and have prefix, delete them
        if filename.startswith(file_prefix) and filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            file_path = os.path.join(image_folder, filename)
            if os.path.getmtime(file_path) < threshold_timestamp:
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except OSError as e:
                    print(f"Warning: Failed to delete {file_path}: {e}")

    print(f"Cleanup finished. Deleted {deleted_count} old images.")

"""
    Loads configuration from a file. Expects key=value format.
    Returns a dictionary of parameters.
    param: config_path - path to config file
    return: dictionary of parameters (e.g., {'folder': 'path/to/images', 'prefix': 'img_', ...})
"""
def load_config(config_path):

    params = {}
    if not os.path.exists(config_path): # no config file
        print(f"Error: Configuration file '{config_path}' does not exist.")
        sys.exit(1)

    with open(config_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # Skip empty lines or comments
            if not line or line.startswith('#'):
                continue

            if '=' in line:
                key, value = line.split('=', 1)
                params[key.strip()] = value.strip()

    return params

"""
    Helper function to safely read an image (handling paths with special/non-ASCII characters).
    param: file_path - path to the image file
    return: image as a numpy array (or None if error)
"""
def read_image_safe(file_path):
    try:
        with open(file_path, "rb") as f:
            file_bytes = bytearray(f.read())
            numpy_array = np.asarray(file_bytes, dtype=np.uint8)
            return cv2.imdecode(numpy_array, cv2.IMREAD_COLOR)
    except Exception as e:
        print(f"Error reading file stream: {e}")
        return None

"""
    Function to create a timelapse video based on the provided configuration.
    param: config - dictionary of parameters loaded from config file, expected keys:
        - folder (str): Directory containing the images
        - prefix (str): Prefix of image files to include
        - hours (float): Time range in hours to include images from
        - duration (float): Duration of each frame in milliseconds
        - output (str): Output video filename (e.g., "timelapse.mp4")
        - width (int, optional): Target width of video frames (if not specified, uses original image width)
        - height (int, optional): Target height of video frames (if not specified, uses original image height)
"""
def create_timelapse(config):
    try:
        image_folder = config['folder']
        file_prefix = config['prefix']
        hours_back = float(config['hours'])
        frame_duration = float(config['duration'])
        output_filename = config['output']
    except KeyError as e:
        print(f"Error: Missing parameter: {e}")
        return

    target_width = int(config.get('width')) if config.get('width') else None
    target_height = int(config.get('height')) if config.get('height') else None

    # get all files with prefix and within time range (in memory only string, not images)
    time_threshold = datetime.datetime.now() - datetime.timedelta(hours=hours_back)

    print(f"Scanning {image_folder}...")
    all_files = []
    for filename in os.listdir(image_folder):
        if filename.startswith(file_prefix) and filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            path = os.path.join(image_folder, filename)
            mtime = os.path.getmtime(path)
            if datetime.datetime.fromtimestamp(mtime) >= time_threshold:
                all_files.append((path, mtime))

    if not all_files:
        print("No images found.")
        return

    # sort by modification time (oldest first)
    all_files.sort(key=lambda x: x[1])

    video_writer = None
    fps = 1000.0 / frame_duration
    count = 0

    # main loop - read, resize, write (only one image in memory at a time)
    for file_path, _ in all_files:
        img = read_image_safe(file_path) # safe reading to handle special characters in paths
        if img is None:
            continue

        # Initialize video writer on the first image (after we know dimensions), or use target dimensions if specified
        if video_writer is None:
            h, w, _ = img.shape # get first images dimensions
            target_width = target_width or w # give to target width what was in config or what was in first image
            target_height = target_height or h # give to target height what was in config or what was in first image
            fourcc = cv2.VideoWriter_fourcc(*'mp4v') # use mp4v codec for .mp4 output
            video_writer = cv2.VideoWriter(output_filename, fourcc, fps, (target_width, target_height))
            print(f"Video started: {target_width}x{target_height} @ {fps} FPS")

        # resize image if target dimensions are specified, otherwise keep original size
        img_resized = cv2.resize(img, (target_width, target_height))
        video_writer.write(img_resized)

        count += 1
        if count % 10 == 0: # print progress every 10 frames
            print(f"Processing frame {count}/{len(all_files)}...", end='\r')

    if video_writer:
        video_writer.release()
        print(f"\nDone! Processed {count} images.")
    else:
        print("\nNo video was created.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a timelapse video from a config file.")
    parser.add_argument("config_file", help="Path to the configuration file (e.g., config.txt)")
    args = parser.parse_args()

    config_data = load_config(args.config_file)
    create_timelapse(config_data)

    ftp.download_new_from_ftp(config_data)
    ftp.upload_video_to_ftp(config_data)