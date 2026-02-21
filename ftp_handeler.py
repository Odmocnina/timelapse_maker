import os
import datetime
import ftplib

"""
    Function for downloading new images from FTP, uploading the created video to FTP and cleaning up old images from the 
    directory.
    param: config - dictionary with configuration parameters, expected keys:
        - wantFTPLoad (str): "true" if FTP download is enabled, otherwise "false"
        - ftp_server (str): FTP server address
        - ftp_user (str): FTP username
        - ftp_password (str): FTP password
        - folder (str): Local folder to save downloaded images
        - prefix (str): Prefix of image files to consider
"""
def download_new_from_ftp(config):
    # control if FTP download is enabled, if not, skip the whole function
    if str(config.get('want_ftp_load', 'false')).lower() != 'true':
        print("FTP Download not on, no images will be downloaded from FTP.")
        return

    print("--- Starting FTP Download ---")
    try:  # check of mandatory parameters, if any is missing, print error and skip the whole function, because we cannot
        ftp_server = config['ftp_server']           #  continue without them
        ftp_user = config['ftp_user']
        ftp_password = config['ftp_password']
        image_folder = config['folder']
        file_prefix = config['prefix']
    except KeyError as e:
        print(f"FTP Download Error: Missing mandatory parameter {e}")
        return

    # find the newest local image time to avoid downloading files we already have
    newest_local_time = 0
    if os.path.exists(image_folder):
        for filename in os.listdir(image_folder):
            if filename.startswith(file_prefix) and filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                mtime = os.path.getmtime(os.path.join(image_folder, filename))
                if mtime > newest_local_time:
                    newest_local_time = mtime

    # connect to FTP and download files that are newer than the newest local file
    try:
        with ftplib.FTP(ftp_server, ftp_user, ftp_password) as ftp:
            files = ftp.nlst()  # get list of files in the current FTP directory
            downloaded_count = 0

            for filename in files:
                if filename.startswith(file_prefix) and filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                    try:

                        mdtm_resp = ftp.voidcmd(f"MDTM {filename}")
                        ftp_time_str = mdtm_resp[4:].strip()

                        # get time of the file
                        ftp_dt = datetime.datetime.strptime(ftp_time_str, "%Y%m%d%H%M%S")
                        ftp_dt = ftp_dt.replace(tzinfo=datetime.timezone.utc)  # time in UTC
                        ftp_time = ftp_dt.timestamp()  #get real time in milisecs from 1970 something

                        # if the FTP file is newer than the newest local file, download it
                        if ftp_time > newest_local_time:
                            local_path = os.path.join(image_folder, filename)
                            with open(local_path, 'wb') as f:
                                ftp.retrbinary(f"RETR {filename}", f.write)
                            downloaded_count += 1
                    except Exception as e:
                        print(f"Warning: Could not check/download {filename}: {e}")

            print(f"FTP Download finished. Got {downloaded_count} new images.")
    except Exception as e:
        print(f"FTP Connection failed: {e}")


"""
    Function for uploading the created video to FTP if enabled in the configuration.
    param: config - dictionary with configuration parameters, expected keys:
        - wantFTPwrite (str): "true" if FTP upload is enabled, otherwise "false"
        - ftp_server (str): FTP server address
        - ftp_user (str): FTP username
        - ftp_password (str): FTP password
        - output (str): Path to the video file to upload
"""
def upload_video_to_ftp(config):
    # control if FTP upload is enabled, if not, skip the whole function
    if str(config.get('want_ftp_write', 'false')).lower() != 'true':
        print("Writing into FTP not on, mp4 file will not be written into FTP.")
        return

    print("--- Starting FTP Upload ---")
    try:
        ftp_server = config['ftp_server']
        ftp_user = config['ftp_user']
        ftp_password = config['ftp_password']
        output_filename = config['output']
    except KeyError as e:
        print(f"FTP Upload Error: Missing parameter {e}")
        return

    if not os.path.exists(output_filename):
        print(f"Error: Output video {output_filename} not found for upload.")
        return

    try: # try to connect to FTP and upload the video file
        with ftplib.FTP(ftp_server, ftp_user, ftp_password) as ftp:
            with open(output_filename, 'rb') as f:
                # load file in binary mode and upload it using STOR command, the file will be stored with the same name
                ftp.storbinary(f"STOR {os.path.basename(output_filename)}", f) #  as the local file
        print("Success: Video uploaded to FTP.")
    except Exception as e:
        print(f"FTP Upload failed: {e}")