# Archiver
automate video uploading 
# Wrokflow

part 1:
automate script to crop videos greater than 8mb into equal sub parts and later delete the original file  ✔️
existing file asks the video to be selected, I need to automate that to such that it iterates through the videos by itself  finds the big files and crops it

part 2:
 add a progress bar when croping process is going on for each video  ✔️ (needs lil improvement)

 part 3:
 from a directory in windows all files should be uploaded to discord channel 
 ![image](https://github.com/user-attachments/assets/0234add6-0ddd-4021-bee7-ffe6c7f5bcea)

 part 4: (side project)
 upload to mega too (automation)

 part 5:
 before uploading to discord , write the folder name in which the video is kept and after that upload the video

 part 6: 
 for each video being uploaed add progress bar



## PROGRESS


- **Webhook Management:**  
  - Save, load, and delete Discord webhooks from a persistent JSON file.  
  - Select a webhook from a dropdown list.

- **Folder Selection:**  
  - Browse for a folder containing media files.  
  - Option to add all media files from the selected folder.

- **Recursive File Search Option:**  
  - A checkbox lets the user choose whether to search subdirectories (recursive) or just the top-level folder for media files.

- **Drag-and-Drop Support:**  
  - Drag and drop media files directly into a designated Listbox area.

- **Media Type Support:**  
  - Supports image files (PNG, JPG, JPEG, GIF).  
  - Supports video files (MP4, MOV, AVI, MKV).

- **Pre-Upload Notification:**  
  - Before uploading media, sends a text message to the Discord webhook with the folder name.

- **Video Handling:**  
  - For video files smaller than or equal to 8 MB, uploads them directly.  
  - For larger video files, automatically splits them into segments (using ffmpeg) so each segment is roughly under 8 MB.  
  - Uses ffprobe to determine video duration and calculate segment length.

- **Concurrent Processing:**  
  - Uses a thread pool (with half the available CPU cores) to process files concurrently.

- **Progress Monitoring:**  
  - Displays a progress bar in the GUI showing the number of files processed.

- **Stop Functionality:**  
  - A “Stop Upload” button that allows the user to cancel the upload process at any time.  
  - When stopped, any generated temporary video segments are cleaned up immediately.

- **Debug Logging:**  
  - Prints debug messages to the console at various stages (e.g., uploading files, splitting videos, cleaning up temporary files).
