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

# --- Main Application Class ---
class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title("Discord Media Uploader")
        self.geometry("650x550")
        self.webhooks = {}  # Dictionary to store webhooks (name: url)
        self.load_webhooks()  # Load saved webhooks from file
        load_uploaded_records()  # Load uploaded records from JSON
        self.create_widgets()

    def load_webhooks(self):
        if os.path.exists(WEBHOOKS_FILE):
            with open(WEBHOOKS_FILE, 'r') as file:
                try:
                    self.webhooks = json.load(file)
                except json.JSONDecodeError:
                    self.webhooks = {}

    def create_widgets(self):
        # File Manager Frame
        file_manager_frame = tk.Frame(self)
        file_manager_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Treeview with folder structure and uploaded files
        self.columns = ("Local Path", "URLs")
        self.tree = ttk.Treeview(file_manager_frame, columns=self.columns, show="tree")
        self.tree.pack(fill="both", expand=True)
        self.tree.heading("#0", text="Folder / File", anchor="w")

        # Populate the file manager tree
        self.populate_file_manager()

        # Progress bar for download operations
        self.download_progress = ttk.Progressbar(self, orient="horizontal", length=600, mode="determinate")
        self.download_progress.pack(pady=10)

        # Bind right-click for context menu
        self.tree.bind("<Button-3>", self.open_context_menu)

    def populate_file_manager(self):
        """Populate the file manager tree with uploaded records."""
        self.tree.delete(*self.tree.get_children())
        for folder, records in UPLOADED_RECORDS.items():
            parent_id = self.tree.insert("", "end", iid=folder, text=folder, open=True, values=(folder,))
            for rec in records:
                ext = os.path.splitext(rec["file"])[1].lower()
                if ext in VIDEO_EXTS:
                    display = os.path.basename(rec["file"])
                    self.tree.insert(parent_id, "end", text=display, values=(rec["file"], json.dumps(rec["urls"])))

    def open_context_menu(self, event):
        """Open context menu on right-click."""
        item = self.tree.identify_row(event.y)
        if not item:
            return

        context_menu = tk.Menu(self, tearoff=0)
        context_menu.add_command(label="Delete", command=lambda: self.delete_item(item))
        context_menu.add_command(label="Download Videos", command=lambda: self.download_videos_from_item(item))
        context_menu.post(event.x_root, event.y_root)

    def delete_item(self, item):
        """Delete a file or folder from the uploaded records."""
        path = self.tree.item(item, "values")[0]

        # Confirm deletion
        if not messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete '{path}'?"):
            return

        # Handle folder and file deletion
        if item in UPLOADED_RECORDS:
            del UPLOADED_RECORDS[item]  # Delete entire folder
        else:
            parent = self.tree.parent(item)
            if parent in UPLOADED_RECORDS:
                records = UPLOADED_RECORDS.get(parent, [])
                new_records = [rec for rec in records if rec["file"] != path]
                if new_records:
                    UPLOADED_RECORDS[parent] = new_records
                else:
                    del UPLOADED_RECORDS[parent]

        # Save updated records and refresh tree
        save_uploaded_records()
        self.populate_file_manager()
        messagebox.showinfo("Info", f"Deleted '{path}' successfully.")

    def download_videos_from_item(self, item):
        """Download videos from the selected directory or file node."""
        path = self.tree.item(item, "values")[0]
        parent = self.tree.parent(item) if not path else item

        # Get all video records for the selected folder
        records = UPLOADED_RECORDS.get(parent, [])
        video_records = [rec for rec in records if os.path.splitext(rec["file"])[1].lower() in VIDEO_EXTS and rec["urls"]]

        if not video_records:
            messagebox.showinfo("Info", "No videos available for download.")
            return

        dest = filedialog.askdirectory(title="Select Destination Folder for Downloaded Videos")
        if not dest:
            return

        total_files = len(video_records)
        self.download_progress["maximum"] = total_files
        self.download_progress["value"] = 0

        for count, rec in enumerate(video_records, 1):
            base_name = os.path.basename(rec["file"])
            for i, url in enumerate(rec["urls"]):
                file_name = f"{base_name}" if len(rec["urls"]) == 1 else f"{os.path.splitext(base_name)[0]}_{i}{os.path.splitext(base_name)[1]}"
                dest_path = os.path.join(dest, file_name)
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
            self.download_progress["value"] = count

        messagebox.showinfo("Info", "Download process completed.")

if __name__ == "__main__":
    app = App()
    app.mainloop()
