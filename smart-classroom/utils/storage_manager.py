import os
import json
from threading import Thread
from typing import Union
from pathlib import Path


class StorageManager:
    @staticmethod
    def _ensure_dir(path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)

    @staticmethod
    def _prepare_json_data(path: str, data: dict, append: bool) -> list:
        if append and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                    if isinstance(existing, list):
                        existing.append(data)
                        return existing
                    return [existing, data]
            except json.JSONDecodeError:
                return [data]
        return [data]  # Always return list

    @staticmethod
    def _write(path: str, data: Union[str, dict], append: bool):
        StorageManager._ensure_dir(path)

        if isinstance(data, dict):
            data = StorageManager._prepare_json_data(path, data, append)
            # Always overwrite to maintain valid JSON
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        else:
            mode = 'a' if append else 'w'
            with open(path, mode, encoding="utf-8") as f:
                f.write(data)

    @staticmethod
    def save(path: str, data: Union[str, dict], append: bool = False):
        StorageManager._write(path, data, append)

    @staticmethod
    def save_async(path: str, data: Union[str, dict], append: bool = False):
        Thread(target=StorageManager._write, args=(path, data, append)).start()

    @staticmethod
    def read_text_file(path: str | Path) -> str | None:
        """
        Reads a text file and returns its content as a string.
        Returns None if the file is empty or contains only whitespace.
        """
        try:
            return Path(path).read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            raise
        except Exception as e:
            raise RuntimeError(f"Error reading file {path}: {e}")
