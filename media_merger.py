#merges all media in a folder , small videos into a single video , merges all photos into a gif , photos and videos into a video , can adjust time for each photo
import os
import threading
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
import time
import traceback
from PIL import Image, ImageOps

class MediaMergerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Photo + Video Merger")
        self.selected_folder = ""
        self.image_duration = tk.IntVar(value=1)
        self.cancel_requested = False
        self.merge_option = tk.StringVar(value="both")

        # UI Components
        self.label = tk.Label(root, text="No folder selected")
        self.label.pack(pady=5)

        self.select_button = tk.Button(root, text="Choose Folder", command=self.select_folder)
        self.select_button.pack(pady=5)

        self.option_frame = tk.Frame(root)
        self.option_frame.pack(pady=5)

        tk.Label(self.option_frame, text="Merge option:").pack(side=tk.LEFT)
        tk.Radiobutton(self.option_frame, text="Photos Only", variable=self.merge_option, value="photos").pack(side=tk.LEFT)
        tk.Radiobutton(self.option_frame, text="Videos Only", variable=self.merge_option, value="videos").pack(side=tk.LEFT)
        tk.Radiobutton(self.option_frame, text="Both", variable=self.merge_option, value="both").pack(side=tk.LEFT)

        self.duration_label = tk.Label(root, text="Image duration (seconds):")
        self.duration_label.pack(pady=2)

        self.duration_entry = tk.Entry(root, textvariable=self.image_duration)
        self.duration_entry.pack(pady=2)

        self.file_listbox = tk.Listbox(root, width=70, height=10)
        self.file_listbox.pack(pady=10)

        self.progress = ttk.Progressbar(root, orient="horizontal", mode="determinate", length=400)
        self.progress.pack(pady=10)

        self.merge_button = tk.Button(root, text="Merge to Output", command=self.start_merge)
        self.merge_button.pack(pady=5)

        self.cancel_button = tk.Button(root, text="Cancel", command=self.cancel_process, state=tk.DISABLED)
        self.cancel_button.pack(pady=5)

    def select_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.selected_folder = folder
            self.label.config(text=f"Selected Folder: {folder}")
            self.load_files()

    def load_files(self):
        self.file_listbox.delete(0, tk.END)
        if not self.selected_folder:
            return

        files = sorted(Path(self.selected_folder).iterdir())
        self.media_files = [f for f in files if f.suffix.lower() in ['.jpg', '.jpeg', '.png', '.bmp', '.webp', '.mp4', '.mov', '.avi', '.mkv']]

        for f in self.media_files:
            self.file_listbox.insert(tk.END, f.name)

    def start_merge(self):
        if not hasattr(self, 'media_files') or not self.media_files:
            messagebox.showwarning("No files", "No media files found in selected folder.")
            return

        try:
            duration = int(self.image_duration.get())
            if duration <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid Duration", "Please enter a valid positive integer for image duration.")
            return

        self.cancel_requested = False
        self.cancel_button.config(state=tk.NORMAL)
        self.merge_button.config(state=tk.DISABLED)
        threading.Thread(target=self.merge_media, args=(duration,)).start()

    def cancel_process(self):
        self.cancel_requested = True

    def merge_media(self, image_duration):
        temp_dir = Path(self.selected_folder) / "__temp_ffmpeg__"
        temp_dir.mkdir(exist_ok=True)
        output_path = Path(self.selected_folder) / ("merged_output.gif" if self.merge_option.get() == "photos" else "merged_output.mp4")

        option = self.merge_option.get()
        filtered_media = []
        for f in self.media_files:
            ext = f.suffix.lower()
            if option == "photos" and ext in ['.jpg', '.jpeg', '.png', '.bmp', '.webp']:
                filtered_media.append(f)
            elif option == "videos" and ext in ['.mp4', '.mov', '.avi', '.mkv']:
                filtered_media.append(f)
            elif option == "both":
                filtered_media.append(f)

        total = len(filtered_media)
        self.progress["maximum"] = total

        try:
            if option == "photos":
                images = filtered_media
                images.sort()
                pil_images = []

                # Use first image's size as base
                base_img = Image.open(images[0])
                base_size = base_img.size

                for i, img_path in enumerate(images):
                    if self.cancel_requested:
                        raise Exception("Merging cancelled by user")
                    img = Image.open(img_path).convert("RGBA")
                    img = ImageOps.pad(img, base_size, method=Image.Resampling.LANCZOS)
                    pil_images.append(img)
                    self.progress["value"] = i + 1
                    self.root.update_idletasks()

                pil_images[0].save(
                    output_path,
                    save_all=True,
                    append_images=pil_images[1:],
                    optimize=False,
                    duration=image_duration * 1000,
                    loop=0
                )

            else:
                image_index = 0
                video_index = 0
                temp_files = []

                for i, media in enumerate(filtered_media):
                    if self.cancel_requested:
                        raise Exception("Merging cancelled by user")

                    if media.suffix.lower() in ['.jpg', '.jpeg', '.png', '.bmp', '.webp']:
                        temp_file = temp_dir / f"image_{image_index}.ts"
                        cmd = [
                            "ffmpeg", "-y", "-loop", "1",
                            "-t", str(image_duration),
                            "-i", str(media),
                            "-vf", "format=yuv420p",
                            "-c:v", "libx264", "-preset", "veryfast", "-f", "mpegts",
                            str(temp_file)
                        ]
                        print(f"[DEBUG] Running ffmpeg for image: {cmd}")
                        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                        temp_files.append(temp_file)
                        image_index += 1
                    else:
                        temp_file = temp_dir / f"video_{video_index}.ts"
                        cmd = [
                            "ffmpeg", "-y", "-i", str(media),
                            "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-f", "mpegts",
                            str(temp_file)
                        ]
                        print(f"[DEBUG] Running ffmpeg for video: {cmd}")
                        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                        temp_files.append(temp_file)
                        video_index += 1

                    self.progress["value"] = i + 1
                    self.root.update_idletasks()

                concat_list = '|'.join([f.as_posix() for f in temp_files])
                cmd = [
                    "ffmpeg", "-y", "-i", f"concat:{concat_list}",
                    "-c", "copy", str(output_path)
                ]
                print(f"[DEBUG] Running ffmpeg for final merge: {cmd}")
                subprocess.run(cmd, check=True)

            messagebox.showinfo("Success", f"Merged output saved to:\n{output_path}")

        except Exception as e:
            traceback_str = traceback.format_exc()
            print(f"[ERROR] {e}\n{traceback_str}")
            messagebox.showerror("Error", f"Failed to merge: {str(e)}")

        finally:
            for f in temp_dir.glob("*"):
                try:
                    f.unlink()
                except Exception as ex:
                    print(f"[WARN] Failed to delete temp file {f}: {ex}")
            try:
                temp_dir.rmdir()
            except Exception as ex:
                print(f"[WARN] Failed to remove temp directory: {ex}")

            self.cancel_button.config(state=tk.DISABLED)
            self.merge_button.config(state=tk.NORMAL)
            self.progress["value"] = 0

if __name__ == "__main__":
    root = tk.Tk()
    app = MediaMergerApp(root)
    root.mainloop()
