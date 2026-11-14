# Tests

```bash
python tests/run_all.py            # unit + integration (never touches your screen)
python tests/run_all.py --desktop  # also OCR + real-window UI tests (hands off the PC while they run)
python tests/run_all.py workflows  # only files matching a name
```

| Folder | What | Needs |
|---|---|---|
| `unit/` | routing, safety, memory, workflows, agent loop, listener (fake Telegram / fake desktop) | nothing |
| `integration/` | Video Studio start/stop, ONLINE/OFFLINE indicator, async approvals (fake Telegram server + a temp copy of the pipeline's `tools/`) | pipeline folder (`VIDEOSTUDIO_DIR`, default `D:\VideoStudio_Mac`); skipped if absent |
| `integration/test_ocr.py`, `test_ui_actions_live.py` | real windows / OCR | Windows, `--desktop` |
| `fixtures/` | test form/web pages used by the desktop tests | - |
| `live/` | manual harnesses against the real services (e.g. a real private YouTube upload) - run by hand only | real accounts |

Tests isolate memory into a temp dir and disable real UI actions; they send nothing to your real Telegram.
