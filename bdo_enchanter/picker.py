"""Snipping-tool style region picker over a frozen screenshot (tkinter)."""
from __future__ import annotations

import tkinter as tk

MIN_SIZE = 4


def select_region(image_bgr, prompt: str) -> tuple[int, int, int, int] | None:
    """Return (x, y, w, h) in screenshot pixels, or None if cancelled with Esc."""
    import cv2

    ok, png = cv2.imencode(".png", image_bgr)
    if not ok:
        raise RuntimeError("could not encode screenshot")

    root = tk.Tk()
    root.title("bdo-enchanter: select region")
    photo = tk.PhotoImage(data=png.tobytes())
    root.geometry(f"{photo.width()}x{photo.height()}+0+0")
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.configure(cursor="cross")

    canvas = tk.Canvas(root, width=photo.width(), height=photo.height(), highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_image(0, 0, anchor="nw", image=photo)

    banner = f"{prompt}\nDrag a box with the left mouse button.   Esc = cancel"
    text_id = canvas.create_text(20, 20, anchor="nw", text=banner, fill="white",
                                 font=("TkDefaultFont", 14, "bold"))
    b = canvas.bbox(text_id)
    bg = canvas.create_rectangle(b[0] - 10, b[1] - 8, b[2] + 10, b[3] + 8,
                                 fill="#202020", outline="#ffcc00", width=2)
    canvas.tag_lower(bg, text_id)

    state = {"start": None, "rect": None, "result": None}

    def on_press(e):
        state["start"] = (e.x, e.y)
        if state["rect"]:
            canvas.delete(state["rect"])
        state["rect"] = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#00ff00", width=2)

    def on_drag(e):
        if state["start"]:
            canvas.coords(state["rect"], *state["start"], e.x, e.y)

    def on_release(e):
        if not state["start"]:
            return
        x0, y0 = state["start"]
        x, y, w, h = min(x0, e.x), min(y0, e.y), abs(e.x - x0), abs(e.y - y0)
        if w < MIN_SIZE or h < MIN_SIZE:
            state["start"] = None
            return
        state["result"] = (x, y, w, h)
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", lambda _e: root.destroy())
    root.focus_force()
    root.mainloop()
    return state["result"]


def crop(image_bgr, region):
    x, y, w, h = region
    return image_bgr[y:y + h, x:x + w].copy()
