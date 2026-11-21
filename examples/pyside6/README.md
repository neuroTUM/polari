# PySide6 examples

Small, self-contained PySide6 / PyQtGraph scripts, one building block each, for trying out ideas for polari.
They are learning code, not part of the app.

## Run

Each script lists its own dependencies, so no setup is needed:

```bash
cd examples/pyside6
uv run ex04_thread_live_plot.py
```

Example 06 can use the real form validation from `polari-app` (needs `polari_app.experiment`, PR #1).
Without it, the script falls back to a small stand-in:

```bash
PYTHONPATH=../../packages/polari-app/src uv run ex06_form_validation.py
```

Tests:

```bash
uv run --with PySide6-Essentials==6.12.0 --with pyqtgraph==0.14.0 --with numpy \
    --with pytest --with pytest-qt pytest test_gui_with_pytest_qt.py
```

## Examples

| Script | Building block | polari use |
|---|---|---|
| `ex01_layouts.py` | Main window, layouts, splitter, `QAction` | Every screen |
| `ex02_docks_settings.py` | `QDockWidget`, `QSettings` | Recording screen panels that remember their place |
| `ex03_signals_timer.py` | Signals and slots, `QTimer` | Device code that never imports widgets |
| `ex04_thread_live_plot.py` | `QThread`, ring buffer, 30 fps PyQtGraph redraw, NaN gaps | Live EEG plot |
| `ex05_model_view.py` | `QAbstractTableModel`, sort/filter proxy | Experiments list |
| `ex06_form_validation.py` | Form with per-field errors, wired to `validate()` | New Experiment form |
| `ex07_screens_navigation.py` | `QStackedWidget` | The 4-screen flow |
| `ex08_head_map.py` | PyQtGraph scatter plot with live colours | Electrode / impedance map |
| `ex09_export.py` | PNG, SVG and PDF export | Save Experiment screen |
| `ex10_asyncio_qasync.py` | asyncio on the Qt loop (qasync) | Async device shell |
| `ex11_custom_widget_theme.py` | `paintEvent`, style sheets | Stream health LEDs, dark theme |
| `test_gui_with_pytest_qt.py` | `pytest-qt` | GUI tests in CI |

Each script starts with what it shows and one thing to try.

## Rules of thumb

1. Only the GUI thread touches widgets. Workers send data through signals.
2. Send chunks (one per packet), never one signal per sample.
3. Redraw on a timer at about 30 fps, independent of the sample rate.
4. Stop a `QThread` from inside its own thread and `wait()` for it, or the app crashes on quit.
5. Screens emit signals; one main window decides the navigation.

## Findings

Tested on Linux (headless) and on a MacBook Pro M3 Pro, Python 3.14, PySide6 6.12.0, PyQtGraph 0.14.0.

- ex04, 64 channels at 1000 Hz: about 3-4 ms per frame on the Mac, far below the 33 ms of 30 fps.
- pyqtgraph's `SVGExporter` crashes with Qt 6.12; `QSvgGenerator` works (ex09).
- In macOS dark mode the splitter handle in ex01 is hard to see, but it can still be dragged.
