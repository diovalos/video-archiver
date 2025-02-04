import os
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox
from tqdm import tqdm

# Video Size Utility
def get_video_size(file_path):
    """Get the size of the video file in MB."""
    return os.path.getsize(file_path) / (1024 * 1024)

# Video Cropping Function
def crop_video(input_file, max_size_mb=8, codec='libx264'):
    """
    Crop a video into smaller sections if its size exceeds the specified maximum size (in MB).
    Each section is saved as a separate file, and the original video is deleted.
    """
    original_size = get_video_size(input_file)
    print(f"Original video size: {original_size:.2f} MB")

    if original_size <= max_size_mb:
        print("Video is already under the size limit. No cropping needed.")
        return

    duration = float(subprocess.check_output(
        f'ffprobe -i "{input_file}" -show_entries format=duration -v quiet -of csv="p=0"',
        shell=True
    ).decode().strip())
    print(f"Video duration: {duration:.2f} seconds")

    num_sections = int(original_size / max_size_mb) + 1
    section_duration = duration / num_sections

    print(f"Cropping video into {num_sections} sections, each ~{section_duration:.2f} seconds long.")

    for i in tqdm(range(num_sections), desc=f"Processing '{os.path.basename(input_file)}'"):
        start_time = i * section_duration
        output_file = f"{os.path.splitext(input_file)[0]}_part{i + 1}.mp4"

        command = [
            'ffmpeg',
            '-i', input_file,
            '-ss', str(start_time),
            '-t', str(section_duration),
            '-c:v', codec,
            '-c:a', 'aac',
            output_file
        ]

        try:
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"Section {i + 1} created: {output_file}")
        except subprocess.CalledProcessError as e:
            print(f"Error during cropping section {i + 1}: {e}")
            return

    os.remove(input_file)
    print(f"Original video '{input_file}' deleted after processing.")
    print("All sections have been created successfully.")

# GUI Main Function
def gui_main():
    def select_folder():
        folder_path.set(filedialog.askdirectory(title="Select Folder Containing Videos"))

    def process_videos():
        folder = folder_path.get()
        codec_choice = codec_var.get()
        max_size = max_size_var.get()

        if not folder or not os.path.isdir(folder):
            messagebox.showerror("Error", "Invalid folder path. Please select a valid folder.")
            return

        video_extensions = ('.mp4', '.mkv', '.avi', '.mov')
        video_files = []

        # Traverse directory and subdirectories
        for dirpath, _, filenames in os.walk(folder):
            for filename in filenames:
                if filename.lower().endswith(video_extensions):
                    video_files.append(os.path.join(dirpath, filename))

        if not video_files:
            messagebox.showinfo("Info", "No video files found in the selected folder and its subdirectories.")
            return

        print(f"Found {len(video_files)} video file(s).")

        for video_file in video_files:
            crop_video(video_file, max_size_mb=float(max_size), codec=codec_choice)

        messagebox.showinfo("Success", "All video processing completed.")

    root = tk.Tk()
    root.title("Video Cropper Tool")

    folder_path = tk.StringVar()
    codec_var = tk.StringVar(value="libx264")
    max_size_var = tk.StringVar(value="8")

    tk.Label(root, text="Folder Path:").grid(row=0, column=0, padx=5, pady=5)
    tk.Entry(root, textvariable=folder_path, width=50).grid(row=0, column=1, padx=5, pady=5)
    tk.Button(root, text="Browse", command=select_folder).grid(row=0, column=2, padx=5, pady=5)

    tk.Label(root, text="Codec:").grid(row=1, column=0, padx=5, pady=5)
    tk.OptionMenu(root, codec_var, "libx264", "libx265", "vp9").grid(row=1, column=1, padx=5, pady=5)

    tk.Label(root, text="Max Size (MB):").grid(row=2, column=0, padx=5, pady=5)
    tk.Entry(root, textvariable=max_size_var).grid(row=2, column=1, padx=5, pady=5)

    tk.Button(root, text="Process Videos", command=process_videos).grid(row=3, column=1, pady=10)

    root.mainloop()

if __name__ == "__main__":
    gui_main()
