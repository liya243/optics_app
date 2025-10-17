# Optics App

Desktop editor for laying out optical schemes. I vibecoded it because as I notices science nerds use shitass tools like Paint or Inkscape which force you to spend a lot of time. The application is written with PySide6 and provides a canvas with grid snapping, a categorized component browser populated from local PNG assets, and tools for drawing laser paths. Use it to assemble diagrams, save them as JSON projects, or export them as high-resolution PNG images.

## Features

- **Component library** – `components/` Double-click any entry to place the PNG on the canvas at the current view center. You can add your own custom components, names of files will be imported automatically
- **Drag-and-drop editing** – Components and custom PNGs (which you can just paste into app) become movable, rotatable, flippable items with grid snapping (`main.py:52`, `main.py:261`, `main.py:742`).
- **Laser paths** – Right-click and drag to sketch laser lines, their direction will be corrected automatically (`main.py:210`).
- **Layer system** – Items are assigned to logical layers (“Layer 0…4”); visibility toggles and PageUp/PageDown shortcuts help manage occlusion (`main.py:518`, `main.py:870`).
- **Canvas control** – Adjust canvas size and maintain the current viewport; the scene rect and grid redraw automatically (`main.py:503`, `main.py:942`).
- **Project persistence** – Save or load designs as JSON packages that include embedded PNG data and metadata (`main.py:1017`).
- **Export** – Render the assembled scene to a standalone PNG, optionally omitting the grid (`main.py:969`).
- **Built-in guidance** – Press `H` for a compact help overlay or `F1` to open the full shortcut list for power users (`main.py:360`, `main.py:600`).

## Getting Started

1. Ensure Python 3.9+ is installed.
2. Install dependencies:
   ```bash
   pip install PySide6
   ```
3. Run the editor:
   ```bash
   python main.py
   ```

The window loads with a background theme (`background.png`) and a left sidebar that summarizes the active components directory.

## Working With Components

- Populate the sidebar by keeping PNG sprites inside `components/`. Subfolders (many are already provided with Russian names such as “Вспомогательные” or “Ист. света”) become categories in the tree.
- Click **Обновить список** if you add or remove files while the app is open.
- Use the search box to filter by filename (case-insensitive, matches substrings).
- Double-click a component to add it to the scene, or press **Добавить PNG (файл)** to bring in an ad-hoc sprite from elsewhere on disk.

## Canvas Editing Workflow

- **Placement** – Items snap to the 40 px grid when released; group moves also snap to preserve alignment (`main.py:70`, `main.py:237`).
- **Transformations** – Select an item and use `R`/`Shift+R` to rotate ±22.5°, `V` to flip vertically, and `[`/`]` to change PNG opacity (`main.py:261`).
- **Copy & duplicate** – `Ctrl+C`, `Ctrl+V`, and `Ctrl+D` duplicate selections with a one-grid offset.
- **Laser creation** – Right mouse drag adds `LaserLine` objects; delete them with `Delete` and reassign layers with PageUp/PageDown.
- **Layers** – Choose the default placement layer from the combo box, or toggle visibility with the checklist. Internal layer names are stored with each item and preserved on export.
- **Grid** – The grid renders as part of the scene background; enable “Без сетки при экспорте” to output clean images while keeping the grid visible during editing.

## Saving, Loading, and Exporting

- `Ctrl+S` / **Сохранить проект…** writes a JSON file containing:
  - Scene dimensions.
  - Serialized items (`component`, `png`, or `laser`), including inlined PNGs (Base64) and transforms.
- `Ctrl+O` / **Открыть проект…** clears the scene and restores items from JSON, reapplying layer visibility toggles.
- `Ctrl+E` / **Экспорт PNG** saves the current view as a raster image sized to the canvas rectangle.

Sample data:

- `example.json` – Extensive demo project with embedded sprites.
- `project.json` – Minimal lens example.
- `optical_scheme.png` – Example export result.

## Keyboard Shortcuts

| Action | Shortcut |
| --- | --- |
| Toggle help overlay | `H` |
| Shortcuts dialog | `F1` |
| Zoom in/out (view) | `Ctrl` + `+` / `Ctrl` + `-` |
| Reset view zoom | `Ctrl` + `0` |
| Zoom selected PNG | `Ctrl` + `+` / `Ctrl` + `-` (with selection) |
| Draw laser line | Right-click drag |
| Rotate selection | `R` / `Shift` + `R` |
| Flip vertically | `V` |
| Opacity ± | `[` / `]` |
| Copy / Paste / Duplicate | `Ctrl+C` / `Ctrl+V` / `Ctrl+D` |
| Delete | `Delete` |
| Move to next/prev layer | `PageUp` / `PageDown` |
| Save / Open / Export | `Ctrl+S` / `Ctrl+O` / `Ctrl+E` |

## Troubleshooting & Notes

- PNG assets with transparent backgrounds yield the cleanest results. Large sprites may need manual scaling via `Ctrl` + mouse wheel.
- Projects created with earlier versions lacking embedded PNG data can still be loaded if the referenced files remain in `components/`.
- If PySide6 is missing, the app will not start; reinstall via `pip install PySide6`.

---

For quick orientation, keep `optical_scheme.png` nearby as a visual reference for what a finished layout can look like.
