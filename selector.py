"""Snipping-tool style region picker.

Shows a frozen screenshot full-screen in a Tk window and lets the user drag a
rectangle. Works regardless of how the game window is layered because the
game is never on top while the picker is open; only the screenshot is.
"""
from __future__ import annotations

import tkinter as tk

MIN_SIZE = 4


def select_region(image_bgr, prompt: str) -> tuple[int, int, int, int] | None:
    """Return (x, y, w, h) in screenshot pixels, or None if cancelled (Esc)."""
    import cv2

    ok, png = cv2.imencode(".png", image_bgr)
    if not ok:
        raise RuntimeError("could not encode screenshot")

    root = tk.Tk()
    root.title("bdo-enchanter: select region")
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.configure(cursor="cross")

    photo = tk.PhotoImage(data=png.tobytes())
    # Explicit geometry so the picker covers the screenshot 1:1 even when the
    # window manager ignores the fullscreen hint.
    root.geometry(f"{photo.width()}x{photo.height()}+0+0")
    canvas = tk.Canvas(root, width=photo.width(), height=photo.height(), highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_image(0, 0, anchor="nw", image=photo)

    banner = f"{prompt}\nDrag a box with the left mouse button.  Esc = cancel / retake"
    text_id = canvas.create_text(20, 20, anchor="nw", text=banner, fill="white",
                                 font=("TkDefaultFont", 14, "bold"))
    bbox = canvas.bbox(text_id)
    bg_id = canvas.create_rectangle(bbox[0] - 10, bbox[1] - 8, bbox[2] + 10, bbox[3] + 8,
                                    fill="#202020", outline="#ffcc00", width=2)
    canvas.tag_lower(bg_id, text_id)

    state = {"start": None, "rect": None, "result": None}

    def on_press(event):
        state["start"] = (event.x, event.y)
        if state["rect"]:
            canvas.delete(state["rect"])
        state["rect"] = canvas.create_rectangle(event.x, event.y, event.x, event.y,
                                                outline="#00ff00", width=2)

    def on_drag(event):
        if state["start"]:
            x0, y0 = state["start"]
            canvas.coords(state["rect"], x0, y0, event.x, event.y)

    def on_release(event):
        if not state["start"]:
            return
        x0, y0 = state["start"]
        x1, y1 = event.x, event.y
        x, y = min(x0, x1), min(y0, y1)
        w, h = abs(x1 - x0), abs(y1 - y0)
        if w < MIN_SIZE or h < MIN_SIZE:
            state["start"] = None
            return
        state["result"] = (x, y, w, h)
        root.destroy()

    def on_escape(_event):
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", on_escape)
    root.focus_force()
    root.mainloop()
    return state["result"]


def crop(image_bgr, region: tuple[int, int, int, int]):
    x, y, w, h = region
    return image_bgr[y:y + h, x:x + w].copy()
