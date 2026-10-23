-- Admin queries for Prep reviews. Run them with psql against the database.
-- Each query starts with a "-- name:" line. Phase 6 adds one query per metric in SPEC.md.

-- name: stuck_emails
-- Emails that weren't sent: 'claimed' rows (the job stopped mid-send, so the email may or may not
-- have gone out; never resent automatically) and 'failed' rows (Resend refused the email; retried
-- until the send window closes). A row claimed in the last few minutes may still be sending.
SELECT es.user_id, u.email, es.local_date, es.status, es.review_count, es.claimed_at, es.error
FROM email_sends AS es
JOIN users AS u ON u.id = es.user_id
WHERE es.status <> 'sent'
ORDER BY es.local_date DESC, es.claimed_at DESC;
