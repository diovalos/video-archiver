#uploads videos in a folder in discord using discord webhooks , splits files bigger than 8mb into smaller sectionf of 8mb
import os
import math
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import requests
import time
import multiprocessing
from concurrent.futures import ThreadPoolExecutor, as_completed
import json  # For saving/loading webhooks and upload records
import shutil  # For file operations
import sys

# Import drag-and-drop support; install tkinterdnd2 via pip if needed
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
except ImportError:
    messagebox.showerror("Import Error", "Please install tkinterdnd2 (pip install tkinterdnd2)")
    raise

# --- Global cancellation, cleanup and upload tracking ---
STOP_EVENT = threading.Event()      # When set, processing functions will abort
GENERATED_FILES = []                # Temporary files (e.g. video segments)

# UPLOADED_RECORDS stores a mapping: 
# { folder_path: [ { "file": local_file_path, "urls": [discord_url, ...] }, ... ] }
UPLOADED_RECORDS_FILE = "uploaded_records.json"
UPLOADED_RECORDS = {}

# --- Configuration ---
MAX_SIZE = 8 * 1024 * 1024           # 8 MB in bytes
IMAGE_EXTS = ['.png', '.jpg', '.jpeg', '.gif']
VIDEO_EXTS = ['.mp4', '.mov', '.avi', '.mkv']
WEBHOOKS_FILE = "saved_webhooks.json"  # File to store saved webhooks

# --- Helper Functions ---
def load_uploaded_records():
    global UPLOADED_RECORDS
    if os.path.exists(UPLOADED_RECORDS_FILE):
        with open(UPLOADED_RECORDS_FILE, 'r') as f:
            try:
                UPLOADED_RECORDS = json.load(f)
            except json.JSONDecodeError:
                UPLOADED_RECORDS = {}
    else:
        UPLOADED_RECORDS = {}

def save_uploaded_records():
    with open(UPLOADED_RECORDS_FILE, 'w') as f:
        json.dump(UPLOADED_RECORDS, f, indent=4)

def send_text_message(webhook_url, message_text):
    """Send a plain text message to the Discord webhook."""
    print(f"[DEBUG] Sending message: {message_text}")
    try:
        payload = {"content": message_text}
        response = requests.post(webhook_url, json=payload)
        if response.status_code in (200, 204):
            print("[DEBUG] Message sent successfully!")
        else:
            print(f"[ERROR] Failed to send message. Status: {response.status_code}")
    except Exception as e:
        print(f"[ERROR] Exception sending message: {e}")

def upload_file(file_path, webhook_url):
    """Upload a file to Discord via webhook and record its information in UPLOADED_RECORDS."""
    if STOP_EVENT.is_set():
        print(f"[DEBUG] Upload cancelled for file: {file_path}")
        return
    print(f"[DEBUG] Uploading file: {file_path}")
    # Ensure wait=true so that Discord returns a JSON response
    if "wait=true" not in webhook_url:
        if "?" in webhook_url:
            upload_url = webhook_url + "&wait=true"
        else:
            upload_url = webhook_url + "?wait=true"
    else:
        upload_url = webhook_url
    try:
        with open(file_path, "rb") as f:
            files = {"file": f}
            response = requests.post(upload_url, files=files)
        if response.status_code in (200, 204):
            try:
                data = response.json()
                urls = []
                if "attachments" in data:
                    urls = [att.get("url") for att in data["attachments"] if att.get("url")]
                print(f"[DEBUG] Uploaded URLs for {file_path}: {urls}")
            except Exception as e:
                print(f"[ERROR] Could not decode JSON response for {file_path}: {e}")
                urls = []
            folder = os.path.dirname(file_path)
            record = {"file": file_path, "urls": urls}
            if folder in UPLOADED_RECORDS:
                UPLOADED_RECORDS[folder].append(record)
            else:
                UPLOADED_RECORDS[folder] = [record]
            save_uploaded_records()
            print(f"[DEBUG] Uploaded {file_path} successfully!")
        else:
            print(f"[ERROR] Failed to upload {file_path}. Status: {response.status_code}")
    except Exception as e:
        print(f"[ERROR] Exception uploading {file_path}: {e}")

def get_video_duration(input_file):
    """Use ffprobe to obtain video duration in seconds."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", input_file
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        duration = float(result.stdout.strip())
        print(f"[DEBUG] Duration of {input_file}: {duration} seconds")
        return duration
    except Exception as e:
        print(f"[ERROR] Could not get duration for {input_file}: {e}")
        return None

def split_video(input_file, output_pattern):
    """
    Splits the video into segments using ffmpeg.
    Each segment resets timestamps to avoid audio/video glitches.
    """
    duration = get_video_duration(input_file)
    if duration is None:
        return []
    file_size = os.path.getsize(input_file)
    num_segments = math.ceil(file_size / MAX_SIZE)
    seg_duration = duration / num_segments
    seg_duration_str = f"{seg_duration:.2f}"
    print(f"[DEBUG] Splitting {input_file} into {num_segments} segments (approx {seg_duration_str} sec each)")
    cmd = [
        "ffmpeg", "-i", input_file, "-c", "copy", "-map", "0",
        "-segment_time", seg_duration_str, "-reset_timestamps", "1",
        "-f", "segment", output_pattern
    ]
    print(f"[DEBUG] Running ffmpeg: {' '.join(cmd)}")
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    base_dir = os.path.dirname(input_file)
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    ext = os.path.splitext(input_file)[1]
    segments = []
    for filename in os.listdir(base_dir):
        if (filename.startswith(base_name) and filename.endswith(ext)
            and filename != os.path.basename(input_file)):
            seg_path = os.path.join(base_dir, filename)
            segments.append(seg_path)
            GENERATED_FILES.append(seg_path)
    segments.sort()
    print(f"[DEBUG] Segments found: {segments}")
    return segments

def process_video_file(file_path, webhook_url):
    """Process a video file: upload directly if small or split and upload segments if too large."""
    if STOP_EVENT.is_set():
        print(f"[DEBUG] Skipping video {file_path} due to stop request.")
        return
    print(f"[DEBUG] Processing video file: {file_path}")
    file_size = os.path.getsize(file_path)
    if file_size <= MAX_SIZE:
        upload_file(file_path, webhook_url)
    else:
        dir_name = os.path.dirname(file_path)
        base_name, ext = os.path.splitext(os.path.basename(file_path))
        output_pattern = os.path.join(dir_name, f"{base_name}_%03d{ext}")
        segments = split_video(file_path, output_pattern)
        for seg in segments:
            if STOP_EVENT.is_set():
                print("[DEBUG] Stop requested during segment upload; aborting further uploads.")
                break
            upload_file(seg, webhook_url)
            time.sleep(0.5)
        for seg in segments:
            if os.path.exists(seg):
                try:
                    os.remove(seg)
                    print(f"[DEBUG] Deleted segment: {seg}")
                    if seg in GENERATED_FILES:
                        GENERATED_FILES.remove(seg)
                except Exception as e:
                    print(f"[ERROR] Could not delete segment {seg}: {e}")

def process_image_file(file_path, webhook_url):
    """Process an image file by uploading it."""
    if STOP_EVENT.is_set():
        print(f"[DEBUG] Skipping image {file_path} due to stop request.")
        return
    print(f"[DEBUG] Processing image file: {file_path}")
    upload_file(file_path, webhook_url)

def process_file(file_path, webhook_url):
    """Determine file type and process accordingly."""
    if STOP_EVENT.is_set():
        print(f"[DEBUG] Skipping file {file_path} due to stop request.")
        return
    ext = os.path.splitext(file_path)[1].lower()
    if ext in IMAGE_EXTS:
        process_image_file(file_path, webhook_url)
    elif ext in VIDEO_EXTS:
        process_video_file(file_path, webhook_url)
    else:
        print(f"[DEBUG] Skipping unsupported file: {file_path}")

def cleanup_generated_files():
    """Delete all temporary files recorded in GENERATED_FILES."""
    print("[DEBUG] Cleaning up generated temporary files...")
    for f in GENERATED_FILES.copy():
        if os.path.exists(f):
            try:
                os.remove(f)
                print(f"[DEBUG] Deleted generated file: {f}")
                GENERATED_FILES.remove(f)
            except Exception as e:
                print(f"[ERROR] Could not delete generated file {f}: {e}")

# --- GUI Application ---
class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title("Discord Media Uploader")
        self.geometry("650x550")
        self.webhooks = {}  # Dictionary to store webhooks (name: url)
        self.load_webhooks()  # Load saved webhooks from file
        load_uploaded_records()  # Load uploaded records from JSON
        self.selected_webhook = tk.StringVar()  # Selected webhook name
        self.folder_path = tk.StringVar()
        self.recursive = tk.BooleanVar(value=False)  # Checkbox for recursive search
        self.file_list = []  # List of full file paths to upload
        self.total_files = 0
        self.processed_files = 0
        self.create_widgets()

    def load_webhooks(self):
        """Load saved webhooks from the JSON file."""
        if os.path.exists(WEBHOOKS_FILE):
            with open(WEBHOOKS_FILE, 'r') as file:
                try:
                    self.webhooks = json.load(file)
                except json.JSONDecodeError:
                    self.webhooks = {}

    def save_webhooks(self):
        """Save webhooks to the JSON file."""
        with open(WEBHOOKS_FILE, 'w') as file:
            json.dump(self.webhooks, file, indent=4)

    def create_widgets(self):
        # Webhook management frame
        webhook_frame = tk.Frame(self)
        webhook_frame.pack(pady=10, fill="x", padx=10)
        tk.Label(webhook_frame, text="Webhook Name:").pack(side="left")
        self.webhook_name_var = tk.StringVar()
        tk.Entry(webhook_frame, textvariable=self.webhook_name_var, width=15).pack(side="left", padx=5)
        tk.Label(webhook_frame, text="URL:").pack(side="left")
        self.webhook_url_var = tk.StringVar()
        tk.Entry(webhook_frame, textvariable=self.webhook_url_var, width=30).pack(side="left", padx=5)
        tk.Button(webhook_frame, text="Save Webhook", command=self.save_webhook).pack(side="left", padx=5)
        tk.Button(webhook_frame, text="Delete Webhook", command=self.delete_webhook).pack(side="left", padx=5)
        tk.Label(webhook_frame, text="Select Webhook:").pack(side="left", padx=5)
        self.webhook_dropdown = ttk.Combobox(webhook_frame, textvariable=self.selected_webhook, state="readonly")
        self.webhook_dropdown.pack(side="left", padx=5)
        self.update_webhook_dropdown()

        # Folder selection frame
        folder_frame = tk.Frame(self)
        folder_frame.pack(pady=5, fill="x", padx=10)
        tk.Label(folder_frame, text="Select Folder:").pack(side="left")
        tk.Entry(folder_frame, textvariable=self.folder_path, width=40).pack(side="left", padx=5)
        tk.Button(folder_frame, text="Browse", command=self.browse_folder).pack(side="left", padx=5)
        tk.Button(folder_frame, text="Add Folder Files", command=self.add_folder_files).pack(side="left", padx=5)
        tk.Checkbutton(folder_frame, text="Recursive File Search", variable=self.recursive).pack(side="left", padx=5)
        tk.Button(folder_frame, text="Download Videos", command=self.download_videos).pack(side="left", padx=5)
        tk.Button(folder_frame, text="Open File Manager", command=self.open_file_manager).pack(side="left", padx=5)

        # Drag-and-drop file list frame
        list_frame = tk.Frame(self)
        list_frame.pack(pady=10, fill="both", expand=True, padx=10)
        tk.Label(list_frame, text="Drag and Drop Files Here:").pack(anchor="w")
        self.file_listbox = tk.Listbox(list_frame, selectmode="extended", width=80, height=10)
        self.file_listbox.pack(fill="both", expand=True)
        self.file_listbox.drop_target_register(DND_FILES)
        self.file_listbox.dnd_bind('<<Drop>>', self.on_drop)

        # Control buttons frame
        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Clear File List", command=self.clear_file_list).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Start Upload", command=self.start_upload).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Stop Upload", command=self.stop_upload).pack(side="left", padx=5)

        # Progress bar for upload progress
        self.progress = ttk.Progressbar(self, orient="horizontal", length=550, mode="determinate")
        self.progress.pack(pady=10)

    def update_webhook_dropdown(self):
        """Update the webhook dropdown with the current list of webhooks."""
        self.webhook_dropdown['values'] = list(self.webhooks.keys())
        if self.webhook_dropdown['values']:
            self.selected_webhook.set(self.webhook_dropdown['values'][0])

    def save_webhook(self):
        """Save a new webhook or update an existing one."""
        name = self.webhook_name_var.get().strip()
        url = self.webhook_url_var.get().strip()
        if not name or not url:
            messagebox.showerror("Error", "Please provide both a name and a URL.")
            return
        self.webhooks[name] = url
        self.save_webhooks()
        self.update_webhook_dropdown()
        self.webhook_name_var.set("")
        self.webhook_url_var.set("")
        messagebox.showinfo("Success", "Webhook saved successfully!")

    def delete_webhook(self):
        """Delete the selected webhook."""
        name = self.selected_webhook.get()
        if not name:
            messagebox.showerror("Error", "No webhook selected.")
            return
        if messagebox.askyesno("Confirm", f"Are you sure you want to delete the webhook '{name}'?"):
            del self.webhooks[name]
            self.save_webhooks()
            self.update_webhook_dropdown()
            messagebox.showinfo("Success", "Webhook deleted successfully.")

    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.folder_path.set(folder)

    def add_folder_files(self):
        folder = self.folder_path.get()
        if not folder:
            messagebox.showerror("Error", "Please select a folder first.")
            return
        if self.recursive.get():
            for root, _, files in os.walk(folder):
                for file in files:
                    file_full = os.path.join(root, file)
                    ext = os.path.splitext(file_full)[1].lower()
                    if ext in IMAGE_EXTS or ext in VIDEO_EXTS:
                        if file_full not in self.file_list:
                            self.file_list.append(file_full)
                            self.file_listbox.insert(tk.END, file_full)
        else:
            for entry in os.listdir(folder):
                file_full = os.path.join(folder, entry)
                if os.path.isfile(file_full):
                    ext = os.path.splitext(file_full)[1].lower()
                    if ext in IMAGE_EXTS or ext in VIDEO_EXTS:
                        if file_full not in self.file_list:
                            self.file_list.append(file_full)
                            self.file_listbox.insert(tk.END, file_full)

    def on_drop(self, event):
        files = self.tk.splitlist(event.data)
        for f in files:
            if os.path.isfile(f):
                ext = os.path.splitext(f)[1].lower()
                if ext in IMAGE_EXTS or ext in VIDEO_EXTS:
                    if f not in self.file_list:
                        self.file_list.append(f)
                        self.file_listbox.insert(tk.END, f)
                        print(f"[DEBUG] Added via drag-and-drop: {f}")

    def clear_file_list(self):
        self.file_list = []
        self.file_listbox.delete(0, tk.END)

    def start_upload(self):
        selected_webhook_name = self.selected_webhook.get()
        if not selected_webhook_name:
            messagebox.showerror("Error", "Please select a webhook to use.")
            return
        webhook_url = self.webhooks[selected_webhook_name]
        if not self.file_list:
            messagebox.showinfo("Info", "No files to process. Drag and drop files or add folder files.")
            return
        folder = self.folder_path.get().strip()
        if folder:
            folder_name = os.path.basename(folder)
            send_text_message(webhook_url, f"Uploading media from folder: {folder_name}")
        STOP_EVENT.clear()
        self.total_files = len(self.file_list)
        self.processed_files = 0
        self.progress["maximum"] = self.total_files
        num_workers = max(1, multiprocessing.cpu_count() // 2)
        print(f"[DEBUG] Using {num_workers} worker threads for processing.")
        threading.Thread(target=self.process_files_thread, args=(self.file_list.copy(), webhook_url, num_workers)).start()

    def process_files_thread(self, files, webhook_url, num_workers):
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = {executor.submit(process_file, f, webhook_url): f for f in files}
            for future in as_completed(futures):
                if STOP_EVENT.is_set():
                    print("[DEBUG] Stop event detected; aborting remaining tasks.")
                    break
                self.processed_files += 1
                self.progress["value"] = self.processed_files
                print(f"[DEBUG] Completed {self.processed_files} of {self.total_files} files.")
        print("[DEBUG] File processing thread ending.")
        if STOP_EVENT.is_set():
            cleanup_generated_files()
            messagebox.showinfo("Info", "Upload stopped and temporary files cleaned up.")
        else:
            messagebox.showinfo("Info", "Upload process completed.")

    def stop_upload(self):
        """Stop processing and clean up generated files."""
        STOP_EVENT.set()
        print("[DEBUG] Stop button pressed. Stopping further processing...")
        cleanup_generated_files()

    def download_videos(self):
        """(Legacy download) Download video files from the selected folder preserving folder structure."""
        source_folder = self.folder_path.get().strip()
        if not source_folder:
            messagebox.showerror("Error", "Please select a source folder first.")
            return
        dest = filedialog.askdirectory(title="Select Destination Folder for Downloaded Videos")
        if not dest:
            return
        if self.recursive.get():
            for root, _, files in os.walk(source_folder):
                for file in files:
                    ext = os.path.splitext(file)[1].lower()
                    if ext in VIDEO_EXTS:
                        source_path = os.path.join(root, file)
                        rel_path = os.path.relpath(source_path, start=source_folder)
                        dest_path = os.path.join(dest, rel_path)
                        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                        try:
                            shutil.copy2(source_path, dest_path)
                            print(f"[DEBUG] Downloaded {source_path} to {dest_path}")
                        except Exception as e:
                            print(f"[ERROR] Failed to copy {source_path}: {e}")
        else:
            for entry in os.listdir(source_folder):
                source_path = os.path.join(source_folder, entry)
                if os.path.isfile(source_path):
                    ext = os.path.splitext(source_path)[1].lower()
                    if ext in VIDEO_EXTS:
                        rel_path = os.path.relpath(source_path, start=source_folder)
                        dest_path = os.path.join(dest, rel_path)
                        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                        try:
                            shutil.copy2(source_path, dest_path)
                            print(f"[DEBUG] Downloaded {source_path} to {dest_path}")
                        except Exception as e:
                            print(f"[ERROR] Failed to copy {source_path}: {e}")
        messagebox.showinfo("Info", "Download process completed.")

    def open_file_manager(self):
        """Open a file manager window (similar to Disbox) displaying the uploaded records.
        In this window you can browse uploaded folders and download all videos from a selected folder."""
        load_uploaded_records()  # Refresh UPLOADED_RECORDS from JSON
        fm_window = tk.Toplevel(self)
        fm_window.title("Uploaded Files Manager")
        fm_window.geometry("650x500")
        
        # Treeview for folder structure with columns for file and URL(s)
        columns = ("Local Path", "URLs")
        tree = ttk.Treeview(fm_window, columns=columns, show="tree")
        tree.pack(fill="both", expand=True, padx=10, pady=10)
        tree.heading("#0", text="Folder / File", anchor="w")
        
        # Populate tree: each folder is a parent node; each uploaded record as a child.
        for folder, records in UPLOADED_RECORDS.items():
            parent_id = tree.insert("", "end", iid=folder, text=folder, open=True, values=(folder,))
            for rec in records:
                ext = os.path.splitext(rec["file"])[1].lower()
                # Only include video files in the manager.
                if ext in VIDEO_EXTS:
                    display = os.path.basename(rec["file"])
                    tree.insert(parent_id, "end", text=display, values=(rec["file"], json.dumps(rec["urls"])))
        
        # Download progress bar in file manager window
        fm_progress = ttk.Progressbar(fm_window, orient="horizontal", length=600, mode="determinate")
        fm_progress.pack(pady=5)
        
        # Function to download all uploaded videos for the selected folder
        def download_selected_folder():
            selected = tree.selection()
            if not selected:
                messagebox.showerror("Error", "Please select a folder node.")
                return
            folder_node = selected[0]
            # Ensure a folder node is selected (if a file is selected, get its parent)
            if tree.parent(folder_node):
                folder_node = tree.parent(folder_node)
            folder_path = tree.item(folder_node, "values")[0]
            dest = filedialog.askdirectory(title="Select Destination Folder for Downloaded Videos")
            if not dest:
                return
            # Get all records for the folder
            records = UPLOADED_RECORDS.get(folder_path, [])
            video_records = [rec for rec in records if os.path.splitext(rec["file"])[1].lower() in VIDEO_EXTS and rec["urls"]]
            total = len(video_records)
            if total == 0:
                messagebox.showinfo("Info", "No uploaded video files found for the selected folder.")
                return
            fm_progress["maximum"] = total
            fm_progress["value"] = 0
            count = 0
            for rec in video_records:
                base_name = os.path.basename(rec["file"])
                for i, url in enumerate(rec["urls"]):
                    if len(rec["urls"]) > 1:
                        name, ext = os.path.splitext(base_name)
                        file_name = f"{name}_{i}{ext}"
                    else:
                        file_name = base_name
                    rel_path = os.path.relpath(os.path.dirname(rec["file"]), start=folder_path)
                    dest_path = os.path.join(dest, rel_path, file_name)
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    try:
                        r = requests.get(url, stream=True)
                        if r.status_code == 200:
                            with open(dest_path, "wb") as f:
                                for chunk in r.iter_content(chunk_size=8192):
                                    f.write(chunk)
                            print(f"[DEBUG] Downloaded {url} to {dest_path}")
                        else:
                            print(f"[ERROR] Failed to download {url}. Status: {r.status_code}")
                    except Exception as e:
                        print(f"[ERROR] Exception downloading {url}: {e}")
                count += 1
                fm_progress["value"] = count
            messagebox.showinfo("Info", "Download process completed.")
        
        # Button frame in file manager window
        btn_frame = tk.Frame(fm_window)
        btn_frame.pack(pady=5)
        tk.Button(btn_frame, text="Download Selected Folder", command=download_selected_folder).pack(side="left", padx=5)
        
        # Bind double-click to open folder in file explorer
        def on_double_click(event):
            item = tree.selection()
            if not item:
                return
            item = item[0]
            path = tree.item(item, "values")[0]
            try:
                if sys.platform.startswith('win'):
                    os.startfile(path)
                elif sys.platform.startswith('darwin'):
                    subprocess.call(["open", path])
                else:
                    subprocess.call(["xdg-open", path])
            except Exception as e:
                messagebox.showerror("Error", f"Could not open folder: {e}")
        tree.bind("<Double-1>", on_double_click)
        
    def download_videos(self):
        """(Legacy download) Download video files from the selected folder preserving folder structure."""
        source_folder = self.folder_path.get().strip()
        if not source_folder:
            messagebox.showerror("Error", "Please select a source folder first.")
            return
        dest = filedialog.askdirectory(title="Select Destination Folder for Downloaded Videos")
        if not dest:
            return
        if self.recursive.get():
            for root, _, files in os.walk(source_folder):
                for file in files:
                    ext = os.path.splitext(file)[1].lower()
                    if ext in VIDEO_EXTS:
                        source_path = os.path.join(root, file)
                        rel_path = os.path.relpath(source_path, start=source_folder)
                        dest_path = os.path.join(dest, rel_path)
                        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                        try:
                            shutil.copy2(source_path, dest_path)
                            print(f"[DEBUG] Downloaded {source_path} to {dest_path}")
                        except Exception as e:
                            print(f"[ERROR] Failed to copy {source_path}: {e}")
        else:
            for entry in os.listdir(source_folder):
                source_path = os.path.join(source_folder, entry)
                if os.path.isfile(source_path):
                    ext = os.path.splitext(source_path)[1].lower()
                    if ext in VIDEO_EXTS:
                        rel_path = os.path.relpath(source_path, start=source_folder)
                        dest_path = os.path.join(dest, rel_path)
                        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                        try:
                            shutil.copy2(source_path, dest_path)
                            print(f"[DEBUG] Downloaded {source_path} to {dest_path}")
                        except Exception as e:
                            print(f"[ERROR] Failed to copy {source_path}: {e}")
        messagebox.showinfo("Info", "Download process completed.")

    def open_file_manager(self):
        """Open a file manager window after uploading (similar to Disbox).
        This window displays the uploaded folders and files from UPLOADED_RECORDS and provides download functionality."""
        load_uploaded_records()  # Refresh the uploaded records
        fm_window = tk.Toplevel(self)
        fm_window.title("Uploaded Files Manager")
        fm_window.geometry("650x500")
        
        # Treeview with folder hierarchy
        columns = ("Local Path", "URLs")
        tree = ttk.Treeview(fm_window, columns=columns, show="tree")
        tree.pack(fill="both", expand=True, padx=10, pady=10)
        tree.heading("#0", text="Folder / File", anchor="w")
        
        # Populate tree: each key in UPLOADED_RECORDS becomes a parent node.
        for folder, records in UPLOADED_RECORDS.items():
            parent_id = tree.insert("", "end", iid=folder, text=folder, open=True, values=(folder,))
            for rec in records:
                ext = os.path.splitext(rec["file"])[1].lower()
                if ext in VIDEO_EXTS:
                    tree.insert(parent_id, "end", text=os.path.basename(rec["file"]),
                                values=(rec["file"], json.dumps(rec["urls"])))
        
        # Download progress bar in file manager window
        fm_progress = ttk.Progressbar(fm_window, orient="horizontal", length=600, mode="determinate")
        fm_progress.pack(pady=5)
        
        # Function to download all videos for the selected folder
        def download_selected_folder():
            selected = tree.selection()
            if not selected:
                messagebox.showerror("Error", "Please select a folder node.")
                return
            folder_node = selected[0]
            if tree.parent(folder_node):
                folder_node = tree.parent(folder_node)
            folder_path = tree.item(folder_node, "values")[0]
            dest = filedialog.askdirectory(title="Select Destination Folder for Downloaded Videos")
            if not dest:
                return
            records = UPLOADED_RECORDS.get(folder_path, [])
            video_records = [rec for rec in records if os.path.splitext(rec["file"])[1].lower() in VIDEO_EXTS and rec["urls"]]
            total = len(video_records)
            if total == 0:
                messagebox.showinfo("Info", "No uploaded video files found for the selected folder.")
                return
            fm_progress["maximum"] = total
            fm_progress["value"] = 0
            count = 0
            for rec in video_records:
                base_name = os.path.basename(rec["file"])
                for i, url in enumerate(rec["urls"]):
                    if len(rec["urls"]) > 1:
                        name, ext = os.path.splitext(base_name)
                        file_name = f"{name}_{i}{ext}"
                    else:
                        file_name = base_name
                    rel_path = os.path.relpath(os.path.dirname(rec["file"]), start=folder_path)
                    dest_path = os.path.join(dest, rel_path, file_name)
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    try:
                        r = requests.get(url, stream=True)
                        if r.status_code == 200:
                            with open(dest_path, "wb") as f:
                                for chunk in r.iter_content(chunk_size=8192):
                                    f.write(chunk)
                            print(f"[DEBUG] Downloaded {url} to {dest_path}")
                        else:
                            print(f"[ERROR] Failed to download {url}. Status: {r.status_code}")
                    except Exception as e:
                        print(f"[ERROR] Exception downloading {url}: {e}")
                count += 1
                fm_progress["value"] = count
            messagebox.showinfo("Info", "Folder download completed.")
        
        # Button to trigger download
        btn_frame = tk.Frame(fm_window)
        btn_frame.pack(pady=5)
        tk.Button(btn_frame, text="Download Selected Folder", command=download_selected_folder).pack(side="left", padx=5)
        
        # Double-click to open folder in system file explorer
        def on_double_click(event):
            item = tree.selection()
            if not item:
                return
            item = item[0]
            path = tree.item(item, "values")[0]
            try:
                if sys.platform.startswith('win'):
                    os.startfile(path)
                elif sys.platform.startswith('darwin'):
                    subprocess.call(["open", path])
                else:
                    subprocess.call(["xdg-open", path])
            except Exception as e:
                messagebox.showerror("Error", f"Could not open folder: {e}")
        tree.bind("<Double-1>", on_double_click)

if __name__ == "__main__":
    app = App()
    app.mainloop()
