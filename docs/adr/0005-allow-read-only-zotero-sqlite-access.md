# Allow read-only Zotero SQLite access

Fast inventory and navigation inherited from upstream may read `zotero.sqlite` with `mode=ro&immutable=1`; all direct SQLite mutation code is removed. Because this snapshot can be stale and the schema is internal, every mutation re-reads and validates live state through Zotero, and unsupported schemas fail explicitly. Zotero must be running even though some reads use SQLite.
