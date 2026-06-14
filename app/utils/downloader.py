import urllib.request
import urllib.error
from pathlib import Path
from app.audit.audit_logger import log_audit_event

WHISPER_MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"

def download_whisper_model(dest_path: Path) -> None:
    """Downloads the ggml-base.en.bin Whisper model from Hugging Face if not present.
    
    Shows download progress via audit events and console printing.
    """
    if dest_path.exists():
        return

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    
    temp_dest_path = dest_path.with_suffix(".download")
    
    log_audit_event("MODEL_DOWNLOAD_START", "system", f"Starting download of Whisper model to {dest_path}")
    print(f"Downloading Whisper model from {WHISPER_MODEL_URL}...")
    
    try:
        req = urllib.request.Request(
            WHISPER_MODEL_URL,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        
        with urllib.request.urlopen(req) as response:
            total_size = int(response.info().get("Content-Length", 0))
            bytes_downloaded = 0
            block_size = 1024 * 1024  # 1 MB
            
            with open(temp_dest_path, "wb") as f:
                while True:
                    buffer = response.read(block_size)
                    if not buffer:
                        break
                    f.write(buffer)
                    bytes_downloaded += len(buffer)
                    
                    if total_size > 0:
                        percent = (bytes_downloaded / total_size) * 100
                        # Log/print progress every 10% or at completion
                        print(f"Downloaded {bytes_downloaded / (1024*1024):.1f} MB / {total_size / (1024*1024):.1f} MB ({percent:.1f}%)", end="\r", flush=True)
            
            print() # Print new line after progress loop finishes
            
        # Rename temporary file to destination path upon successful completion
        temp_dest_path.rename(dest_path)
        log_audit_event("MODEL_DOWNLOAD_SUCCESS", "system", f"Successfully downloaded Whisper model to {dest_path}")
        print("Whisper model download completed successfully.")
        
    except urllib.error.URLError as e:
        if temp_dest_path.exists():
            temp_dest_path.unlink()
        log_audit_event("MODEL_DOWNLOAD_ERROR", "system", f"Failed to download Whisper model: {e}")
        print(f"Error downloading Whisper model: {e}")
        raise RuntimeError(f"Failed to download Whisper model: {e}") from e
    except Exception as e:
        if temp_dest_path.exists():
            temp_dest_path.unlink()
        log_audit_event("MODEL_DOWNLOAD_ERROR", "system", f"Unexpected error during download: {e}")
        print(f"Unexpected error: {e}")
        raise e
