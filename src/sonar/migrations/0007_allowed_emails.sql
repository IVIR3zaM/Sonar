-- Allow-list of emails that may sign in with Google (SPEC.md §13 Access list).
--
-- Hand-entered data (SPEC.md §3), managed only through the `sonar` CLI. Emails are
-- stored trimmed and lowercased (auth.emails.normalize_email), so the primary key
-- makes adding one twice a no-op.
CREATE TABLE allowed_emails (
    email TEXT PRIMARY KEY,
    added_at TEXT NOT NULL
);
