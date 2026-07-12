# tulkan

Self-hosted tools, combined in one repo:

- **[mkan/](mkan/)** — Multi-Kanban board with file management (FastAPI + SQLite, single-file
  frontend). See [mkan/README.md](mkan/README.md) for a standalone quickstart.
- **[tul_s/](tul_s/)** — A small suite of self-hosted panel tools sharing a common auth/theme/file
  layer: audio transcription, PDF optimization, flashcard creation, kiln-log curve analysis,
  a lightweight HTML hoster, and more. See [tul_s/CLAUDE.md](tul_s/CLAUDE.md) for the architecture.

`mkan` and `tul_s` can optionally be wired together (a "DV" file-bridge lets mkan cards share
files with the tul_s tools) — see `tul_s/DV_PROTOKOLL.md` for that integration, but each half
also works standalone.

## License

AGPLv3 — see [LICENSE](LICENSE).

## Looking for just the kanban board?

If you only want the kanban tool without the rest of the suite, there's a smaller,
standalone mirror: [mkan](https://github.com/mithubin/mkan).
