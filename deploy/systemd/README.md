# SCLib systemd units

Hourly incremental ingest, triggered at `:10` every hour.

## Install (one-time)

```bash
# As root on VPS2
ln -sf /opt/SCLib_JZIS/deploy/systemd/sclib-ingest.service /etc/systemd/system/sclib-ingest.service
ln -sf /opt/SCLib_JZIS/deploy/systemd/sclib-ingest.timer   /etc/systemd/system/sclib-ingest.timer
systemctl daemon-reload
systemctl enable --now sclib-ingest.timer
```

## Inspect

```bash
systemctl list-timers sclib-ingest.timer          # next scheduled firing
systemctl status sclib-ingest.service              # last run summary
journalctl -u sclib-ingest.service -n 100 --no-pager
tail -n 100 /var/log/sclib/hourly.log
psql -U sclib sclib -c "SELECT id, started_at, status, papers_succeeded, papers_failed, duration_sec FROM ingest_runs ORDER BY started_at DESC LIMIT 10;"
```

## Manual run

```bash
systemctl start sclib-ingest.service
# or run the shell script directly:
/opt/SCLib_JZIS/scripts/sclib-hourly-ingest.sh
```

## Pause / resume

```bash
systemctl stop sclib-ingest.timer           # no new runs, current run (if any) continues
systemctl disable sclib-ingest.timer        # don't start on reboot
systemctl start sclib-ingest.timer          # resume
```

## Alerting

Three consecutive non-zero runs trigger an email to `info@jzis.org`
via Resend. The counter lives in `/var/lib/sclib/consecutive_failures`
and resets to 0 on any successful run (or after firing the alert, so
we don't spam hourly). Customize via env in the service override:

```ini
# /etc/systemd/system/sclib-ingest.service.d/override.conf
[Service]
Environment=SCLIB_ALERT_THRESHOLD=5
Environment=SCLIB_ALERT_EMAIL=admin@example.com
```
